"""Session tests against a scripted fake adapter.

These cover the behaviours that were expensive to discover on real hardware
and would be expensive to rediscover: lease recovery, empty-ACK handling,
volume clamping, and wake ordering.
"""

import pytest

from genlcui.core import commands as cid
from genlcui.core.crc import gsm16
from genlcui.core.devices import Monitor
from genlcui.core.protocol import (
    BROADCAST_ADDR, DeviceTimeout, GNET_ACK, GNET_TIMEOUT, ProtocolError,
    Request,
)
from genlcui.core.session import Session, db_to_sint24
from genlcui.core.transport import Transport


def frame(payload: bytes, code: int = GNET_ACK) -> bytes:
    """Build a well-formed response the transport will accept."""
    body = bytes((0x01, code)) + payload
    return body + gsm16(body).to_bytes(2, "big") + b"\x7e"


def packetise(msg: bytes) -> bytes:
    """Wrap a message the way the adapter's HID endpoint delivers it."""
    body = msg.replace(b"\x7d", b"\x7d\x5d")
    return bytes((63,)) + body + b"\x00" * (64 - 1 - len(body))


class FakeHid:
    """Scripted HID device. `replies` is consumed in order."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.written = []
        self.closed = False

    def write(self, data):
        self.written.append(bytes(data))
        return len(data)

    def read(self, size, timeout=None):
        if not self.replies:
            return b""
        item = self.replies.pop(0)
        return packetise(item) if item is not None else b""

    def close(self):
        self.closed = True

    # helpers for assertions
    def sent_requests(self):
        """Decode what was written, stripping the 2-byte USB prefix."""
        out = []
        for raw in self.written:
            msg = raw[2:]
            out.append((msg[0], msg[1]))
        return out


def make(replies=None):
    hid = FakeHid(replies)
    events = []
    session = Session(Transport(hid), on_event=lambda n, p: events.append((n, p)))
    return hid, session, events


# -- volume safety -------------------------------------------------------

def test_volume_is_clamped_to_the_documented_range():
    _, session, _ = make()
    session.max_volume_db = 0.0          # ceiling off, test the hard range
    assert session.set_volume(50.0) == 0.0
    assert session.set_volume(-999.0) == -130.0


def test_volume_encoding_matches_the_wire_format():
    assert db_to_sint24(0.0) == 2 ** 23 - 1
    assert db_to_sint24(-120.0) == 8
    assert db_to_sint24(-20.0) == pytest.approx(838860, rel=1e-3)


def test_set_volume_broadcasts():
    hid, session, _ = make()
    session.set_volume(-50.0)
    assert hid.sent_requests() == [(BROADCAST_ADDR, cid.CID_VOLUME_GLM)]


# -- wake ordering -------------------------------------------------------

def test_wake_ducks_before_waking():
    """Monitors boot at maximum level, so silence must precede the wakeup."""
    hid, session, _ = make([None])          # RACE finds nothing
    session.wake(-50.0, settle_s=0.05)
    kinds = hid.sent_requests()
    first_volume = next(i for i, (_, c) in enumerate(kinds)
                        if c == cid.CID_VOLUME_GLM)
    first_wake = next(i for i, (_, c) in enumerate(kinds)
                      if c == cid.CID_WAKEUP)
    assert first_volume < first_wake


def test_wake_holds_silence_across_the_whole_boot_window():
    """One duck before the wakeup protects nothing: a booting monitor cannot
    hear it. The safe level must be re-sent while they come up."""
    hid, session, _ = make([None] * 40)
    session.wake(-50.0, settle_s=0.6)
    kinds = hid.sent_requests()
    last_wake = max(i for i, (_, c) in enumerate(kinds) if c == cid.CID_WAKEUP)
    after = [c for _, c in kinds[last_wake:] if c == cid.CID_VOLUME_GLM]
    assert len(after) >= 3


def test_wake_reasserts_volume_afterwards():
    hid, session, _ = make([None] * 40)
    session.wake(-50.0, settle_s=0.05)
    volumes = [i for i, (_, c) in enumerate(hid.sent_requests())
               if c == cid.CID_VOLUME_GLM]
    wakes = [i for i, (_, c) in enumerate(hid.sent_requests())
             if c == cid.CID_WAKEUP]
    assert volumes[-1] > wakes[-1]


def test_wake_drains_after_broadcasts():
    """Unread replies to a broadcast would be handed to the next request."""
    hid, session, _ = make([None] * 40)
    session.wake(-50.0, settle_s=0.05)
    assert session.volume_db is not None


# -- polling -------------------------------------------------------------

def test_empty_ack_retains_the_previous_reading():
    """A bare ACK is a rate limit, not a dropout."""
    hid, session, events = make([frame(b"")])
    monitor = Monitor(serial=1, address=2, temperature_c=37)
    session.monitors[1] = monitor
    assert session.poll_monitor(monitor) is None
    assert monitor.temperature_c == 37
    assert not [e for e in events if e[0] == "monitor_status"]


def test_poll_decodes_temperature_from_tags():
    hid, session, _ = make([frame(bytes([0x41, 0x2D, 0x42, 0xC9]))])
    monitor = Monitor(serial=1, address=2)
    session.monitors[1] = monitor
    assert session.poll_monitor(monitor).temperature_c == 45
    assert monitor.tags[0x42] == 0xC9


def test_knob_movement_is_reported_but_only_on_change():
    payload = bytes(15) + (-843).to_bytes(4, "big", signed=True)
    hid, session, events = make([frame(payload), frame(payload)])
    session.poll_adapter()          # first reading establishes a baseline
    session.poll_adapter()          # identical, so no movement
    assert not [e for e in events if e[0] == "knob_moved"]
    assert session.adapter.knob_db == pytest.approx(-84.3)


def test_knob_movement_emits_when_the_pot_actually_moves():
    a = bytes(15) + (-843).to_bytes(4, "big", signed=True)
    b = bytes(15) + (-511).to_bytes(4, "big", signed=True)
    hid, session, events = make([frame(a), frame(b)])
    session.poll_adapter()
    session.poll_adapter()
    moved = [e for e in events if e[0] == "knob_moved"]
    assert moved and moved[0][1] == pytest.approx(-51.1)


# -- lease recovery ------------------------------------------------------

def test_lease_expiry_triggers_rediscovery_and_retry():
    """The measured failure mode: address goes silent after ~2-3s idle."""
    replies = [
        frame(b"", code=GNET_TIMEOUT),        # poll -> lease expired
        frame(b"\x00\x11\x22"),               # RACE -> serial 0x001122
        frame(b"\x02"),                       # SET_RID accepted
        None,                                 # RACE -> nothing left
        frame(bytes([0x41, 0x25])),           # retried poll succeeds
    ]
    hid, session, _ = make(replies)
    monitor = Monitor(serial=0x001122, address=2, model="8330A")
    session.monitors[0x001122] = monitor

    assert session.poll_monitor(monitor).temperature_c == 37


def test_rediscovery_preserves_identity_across_a_new_lease():
    """Addresses change; serials do not. Settings must survive."""
    replies = [
        frame(b"\x00\x11\x22"),   # RACE
        frame(b"\x02"),           # SET_RID -> address 2
        None,                     # no more monitors
    ]
    hid, session, _ = make(replies)
    monitor = Monitor(serial=0x001122, address=99, model="8330A",
                      online=False)                    # lease expired
    session.monitors[0x001122] = monitor

    session.discover()
    assert session.monitors[0x001122] is monitor      # same object
    assert monitor.address == 2                        # fresh lease
    assert monitor.online is True
    assert monitor.model == "8330A"                     # identity survived


def test_device_timeout_propagates_when_recovery_also_fails():
    """A genuinely absent speaker must not retry forever."""
    replies = [
        frame(b"", code=GNET_TIMEOUT),   # poll fails
        None,                            # RACE finds nothing
        frame(b"", code=GNET_TIMEOUT),   # retry fails too
    ]
    hid, session, _ = make(replies)
    monitor = Monitor(serial=1, address=2)
    session.monitors[1] = monitor
    with pytest.raises(DeviceTimeout):
        session.poll_monitor(monitor)


# -- mute ---------------------------------------------------------------

def test_mute_uses_volume_not_the_unverified_bypass_command():
    """0x2B is not a verified mute; 0x02 froze volume control on real hardware."""
    hid, session, _ = make()
    session.set_volume(-50.0)
    session.mute()
    commands = {c for _, c in hid.sent_requests()}
    assert cid.CID_BYPASS_QUERY not in commands
    assert cid.CID_VOLUME_GLM in commands


def test_mute_then_unmute_restores_the_previous_level():
    _, session, _ = make()
    session.set_volume(-42.0)
    session.mute()
    assert session.muted and session.volume_db == -130.0
    assert session.unmute() == -42.0
    assert not session.muted


def test_unmute_falls_back_to_the_default_when_there_is_no_history():
    _, session, _ = make()
    assert session.unmute() == session.default_volume_db


def test_mute_is_idempotent_and_does_not_lose_the_restore_point():
    _, session, _ = make()
    session.set_volume(-45.0)
    session.mute()
    session.mute()
    assert session.unmute() == -45.0


def test_setting_volume_clears_mute():
    _, session, _ = make()
    session.set_volume(-45.0)
    session.mute()
    session.set_volume(-60.0)
    assert not session.muted


def test_volume_is_clamped_to_the_users_safety_ceiling():
    """Agreed limit: -30 dBFS is the loudest the user tolerates."""
    _, session, _ = make()
    assert session.max_volume_db == -30.0
    assert session.set_volume(0.0) == -30.0
    assert session.set_volume(-10.0) == -30.0


def test_clear_monitor_state_sends_only_the_verified_value():
    hid, session, _ = make([frame(b"")])
    monitor = Monitor(serial=1, address=2)
    session.monitors[1] = monitor
    session.clear_monitor_state(monitor)
    payload = hid.written[-1][2:]
    assert payload[1] == cid.CID_BYPASS_QUERY
    assert payload[2] == cid.STATE_NORMAL == 0x00


# -- identity ------------------------------------------------------------

def test_subwoofer_is_detected_from_the_model_number():
    assert Monitor(serial=1, address=2, model="7350A").is_subwoofer
    assert not Monitor(serial=1, address=3, model="8330A").is_subwoofer


def test_monitor_key_is_serial_not_address():
    a = Monitor(serial=1128979, address=2)
    b = Monitor(serial=1128979, address=7)
    assert a.key == b.key == "#1128979"


def test_addresses_do_not_climb_across_repeated_recoveries():
    """Regression: counting offline monitors as holding addresses exhausted
    the 128-address space after a few dozen lease expiries."""
    hid, session, _ = make()
    monitor = Monitor(serial=1, address=2)
    session.monitors[1] = monitor

    for _ in range(30):
        monitor.online = False
        hid.replies = [frame(b"\x00\x00\x01"), frame(b"\x02"), None]
        session.discover()
        assert monitor.address == 2


def test_device_timeout_does_not_drain_the_queue():
    """A timeout response is well formed; draining would eat the next reply."""
    hid, session, _ = make([frame(b"", code=GNET_TIMEOUT), frame(b"\x41\x25")])
    with pytest.raises(DeviceTimeout):
        Transport(hid).request(Request(2, cid.CID_POLL))
    assert len(hid.replies) == 1, "the following reply must survive"


def test_wake_defaults_to_the_pot_position():
    """The knob is master, so waking should land where it points."""
    _, session, _ = make([None] * 40)
    session.adapter.knob_db = -55.0
    session.wake(settle_s=0.05)
    assert session.volume_db == -55.0


def test_wake_falls_back_to_the_default_when_the_pot_is_unknown():
    _, session, _ = make([None] * 40)
    session.wake(settle_s=0.05)
    assert session.volume_db == session.default_volume_db


def test_wake_settles_to_the_pot_position_not_the_ceiling():
    """The knob mirror is unclamped, so the steady state with the knob here is
    this level. Clamping only at wake would create a jump the moment the user
    next touched the pot -- a hazard, not a protection. The protection is
    holding silence until the monitors are answering."""
    _, session, _ = make([None] * 40)
    session.adapter.knob_db = -5.0
    session.wake(settle_s=0.05)
    assert session.volume_db == -5.0


# -- knob mirroring ------------------------------------------------------
#
# While software holds the bus the adapter stops applying the pot itself, so
# GenlcUI has to. Regression coverage for the failure the author hit: the
# readout tracked the knob while the speakers ignored it entirely.

def _knob_frame(db):
    return frame(bytes(15) + int(db * 10).to_bytes(4, "big", signed=True))


def test_first_adapter_poll_applies_the_knob_position():
    """On taking the bus we must assert the pot's position immediately."""
    hid, session, _ = make([_knob_frame(-51.1)])
    session.poll_adapter()
    assert session.volume_db == pytest.approx(-51.1)
    assert any(c == cid.CID_VOLUME_GLM for _, c in hid.sent_requests())


def test_knob_movement_is_mirrored_to_volume():
    hid, session, _ = make([_knob_frame(-60.0), _knob_frame(-45.0)])
    session.poll_adapter()
    session.poll_adapter()
    assert session.volume_db == pytest.approx(-45.0)


def test_unchanged_knob_does_not_resend_volume():
    """Mirroring must be edge-triggered, not a 20 Hz write storm."""
    hid, session, _ = make([_knob_frame(-60.0)] * 5)
    for _ in range(5):
        session.poll_adapter()
    writes = [c for _, c in hid.sent_requests() if c == cid.CID_VOLUME_GLM]
    assert len(writes) == 1


def test_knob_mirroring_ignores_the_safety_ceiling():
    """The ceiling guards programmatic writes. Clamping the user's own hand
    would make the knob feel broken and regress standalone behaviour."""
    _, session, _ = make([_knob_frame(-10.0)])
    session.poll_adapter()
    assert session.volume_db == pytest.approx(-10.0)   # not clamped to -30


def test_programmatic_writes_still_respect_the_ceiling():
    _, session, _ = make()
    assert session.set_volume(-5.0) == -30.0


def test_knob_mirroring_can_be_disabled():
    _, session, _ = make([_knob_frame(-60.0)])
    session.follow_knob = False
    session.poll_adapter()
    assert session.volume_db is None


def test_moving_the_knob_cancels_a_mute():
    hid, session, _ = make([_knob_frame(-60.0), _knob_frame(-55.0)])
    session.poll_adapter()
    session.mute()
    assert session.muted
    session.poll_adapter()
    assert not session.muted
    assert session.volume_db == pytest.approx(-55.0)


# -- desync and storm protection -----------------------------------------
#
# Regression coverage for the incident where clicking Wake desynchronised the
# bus, triggered several rediscoveries a second, and left the speakers at
# their factory-maximum startup level emitting full-scale noise.

def test_shutdown_ducks_before_sleeping():
    """A monitor that ignores the sleep must not be left sitting loud."""
    hid, session, _ = make()
    session.set_volume(-40.0)
    before = len(hid.written)
    session.shutdown()
    kinds = [c for _, c in hid.sent_requests()[before:]]
    assert kinds.index(cid.CID_VOLUME_GLM) < kinds.index(cid.CID_WAKEUP)


def test_rediscovery_is_rate_limited():
    """Without a cooldown, a booting or absent monitor re-discovers on every
    poll -- three times a second, indefinitely, drowning the bus."""
    replies = [frame(b"", code=GNET_TIMEOUT)] * 40
    hid, session, _ = make(replies)
    monitor = Monitor(serial=1, address=2)
    session.monitors[1] = monitor

    with pytest.raises(DeviceTimeout):
        session.poll_monitor(monitor)          # first one may re-discover
    races_after_first = sum(1 for _, c in hid.sent_requests()
                            if c == cid.CID_RACE)
    for _ in range(5):
        with pytest.raises(DeviceTimeout):
            session.poll_monitor(monitor)
    races_total = sum(1 for _, c in hid.sent_requests() if c == cid.CID_RACE)
    assert races_total == races_after_first, "re-discovered inside the cooldown"


def test_decode_failure_resyncs_the_transport():
    """A wrong-device reply arrives after the transport has already returned,
    so its own resync never runs and the desync would persist."""
    hid, session, _ = make([frame(b"\x84\x01")])   # 16-bit tag, 1 byte of value
    monitor = Monitor(serial=1, address=2)
    session.monitors[1] = monitor
    before = len(hid.replies)
    with pytest.raises(ProtocolError):
        session.poll_monitor(monitor)
    assert len(hid.replies) <= before      # drain ran


def test_knob_is_not_mirrored_during_a_disruptive_operation():
    """Mirroring mid-wake would fight the safety duck."""
    _, session, _ = make([_knob_frame(-40.0)])
    session._busy = True
    session.poll_adapter()
    assert session.volume_db is None       # duck owns the level


def test_guarded_restores_the_intended_level():
    _, session, _ = make()
    session.set_volume(-45.0)
    with session.guarded():
        pass
    assert session.volume_db == pytest.approx(-45.0)


def test_guarded_ducks_while_inside():
    hid, session, _ = make()
    session.set_volume(-45.0)
    marker = len(hid.written)
    with session.guarded():
        sent = [w[2:] for w in hid.written[marker:]]
    assert sent, "nothing was written on entry"
    payload = sent[0]
    level = int.from_bytes(payload[2:5], "big", signed=True)
    assert level < db_to_sint24(-100.0) * 10   # deeply attenuated


def test_newly_discovered_monitor_is_brought_to_the_current_level():
    """A monitor that boots late comes up at its factory maximum. It must not
    stay there until the user happens to touch the knob."""
    replies = [frame(b"\x00\x00\x09"), frame(b"\x02"), None]
    hid, session, _ = make(replies)
    session.set_volume(-55.0)
    marker = len(hid.written)
    session.discover()
    levels = [w[2:] for w in hid.written[marker:]
              if len(w) > 3 and w[3] == cid.CID_VOLUME_GLM]
    assert levels, "no level asserted for the new monitor"


def test_discovery_during_a_guarded_operation_does_not_break_the_duck():
    replies = [frame(b"\x00\x00\x09"), frame(b"\x02"), None]
    hid, session, _ = make(replies)
    session.set_volume(-55.0)
    session._busy = True
    marker = len(hid.written)
    session.discover()
    levels = [w for w in hid.written[marker:]
              if len(w) > 3 and w[3] == cid.CID_VOLUME_GLM]
    assert not levels, "asserted a level while silence was being held"
