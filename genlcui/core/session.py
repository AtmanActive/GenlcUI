"""A live session on the GNet bus.

Owns discovery, the keepalive heartbeat, and all command dispatch. Single
threaded by design: call it from one worker thread only (see controller.py).

The behaviours encoded here were measured, not assumed -- see
docs/PROTOCOL.md for the captures behind each constant.
"""

from __future__ import annotations

import logging
import math
import time
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional

from . import commands as cid
from .devices import Adapter, Monitor
from .protocol import (
    ADAPTER_ADDR, BROADCAST_ADDR, MULTICAST_ADDR, VOLUME_MAX_DB, VOLUME_MIN_DB,
    DeviceTimeout, ProtocolError, Request, decode_adapter_status,
    decode_monitor_status,
)
from .transport import Transport, TransportError

logger = logging.getLogger(__name__)

MAX_ADDRESS = 128

# The shortest possible tag-value item: one tag byte plus one value byte.
# Anything below this is a different kind of reply, not a malformed one.
MIN_TLV_PAYLOAD = 2

# Agreed with the user: -30 dBFS is the loudest they ever tolerate, and -50
# is a comfortable default. The ceiling applies to every write.
SAFETY_MAX_DB = -30.0
DEFAULT_VOLUME_DB = -50.0

# Every operation that disturbs the bus ducks to this first and restores
# afterwards. Genelec SAM monitors boot at MAXIMUM level in standalone mode,
# so any window where a monitor is coming up and we are not in control of its
# level is a window where the room gets full-scale noise. Ducking costs
# nothing and removes that window entirely.
SAFE_DUCK_DB = -120.0

# Waking is slow: monitors boot over several seconds and answer nothing until
# they do. Keep re-asserting the safe level throughout, then settle.
WAKE_SETTLE_S = 8.0
WAKE_POLL_S = 0.25

# A lease expiry re-discovers, but a booting or absent monitor would otherwise
# trigger that on every poll -- three times a second, indefinitely.
REDISCOVER_COOLDOWN_S = 2.0

# How long the bus must have had nothing online before we deliberately stop
# the keepalive, and for how long. The silence must outlast the lease
# (~2-3s) for a stranded monitor to reset and answer RACE again.
ORPHAN_RESYNC_AFTER_S = 10.0
ORPHAN_QUIET_S = 4.0


def db_to_sint24(db: float) -> int:
    """Master volume as the adapter expects it: linear, 24-bit signed."""
    return int((10 ** (db / 20.0)) * (2 ** 23 - 1))


def pct_to_db(pct: float) -> float:
    return 20 * math.log10(max(pct, 1e-4) / 100.0)


class Session:
    """Discovery, keepalive and control for one adapter."""

    def __init__(self, transport: Transport,
                 on_event: Optional[Callable[[str, object], None]] = None):
        self.transport = transport
        self.adapter = Adapter()
        self.monitors: Dict[int, Monitor] = {}   # keyed by serial
        self._on_event = on_event or (lambda *_: None)
        self._last_heartbeat = 0.0

        # Volume is last-writer-wins between us and the hardware pot. The pot
        # reports its position but software cannot move it, so we hold the
        # authoritative value and adopt the knob's whenever it changes.
        self.volume_db: Optional[float] = None
        self.muted = False
        self.default_volume_db = DEFAULT_VOLUME_DB
        self.max_volume_db = SAFETY_MAX_DB
        self._pre_mute_db: Optional[float] = None

        # While a software controller holds the bus, the adapter STOPS
        # applying the potentiometer itself -- it only reports the position.
        # Measured: with GenlcUI running the knob moved the readout but not
        # the speakers; on exit, control returned to the adapter immediately.
        # So mirroring knob -> volume is our job, not the firmware's, and it
        # is what GLM5 must be doing too.
        self.follow_knob = True
        self._last_rediscover = 0.0
        self._busy = False        # a disruptive operation owns the volume

        # Sleep has to be a state the whole loop respects, not just a
        # broadcast. STAY_ONLINE keeps monitors online *by design*, and RACE
        # is a roll-call they answer -- so continuing either after a shutdown
        # wakes the speakers straight back up, which is exactly what happened.
        self.asleep = False

        # serial -> monotonic deadline at which the LED goes back to normal.
        # Identify is timed here rather than with a sleep because the bus
        # thread must keep the heartbeat going: blocking it for five seconds
        # would expire every address lease.
        self._identify_until: Dict[int, float] = {}
        self._devices_last = ()
        self._quiet_until = 0.0
        self._empty_since: Optional[float] = None

    # -- events ----------------------------------------------------------

    def _emit(self, name: str, payload: object = None) -> None:
        try:
            self._on_event(name, payload)
        except Exception:  # noqa: BLE001 - a bad listener must not kill the bus
            logger.exception("event listener raised for %r", name)

    # -- addressing ------------------------------------------------------

    @property
    def online_count(self) -> int:
        return sum(1 for m in self.monitors.values() if m.online)

    def _devices_signature(self):
        """What the UI would show. Used to emit only on real change."""
        return tuple(sorted((m.serial, m.address, m.online)
                            for m in self.monitors.values()))

    def _emit_devices_if_changed(self) -> None:
        """Announce the device list whenever it actually differs.

        Previously this fired only when discovery *found* something, so a
        speaker going away was never reported and the list went stale.
        """
        signature = self._devices_signature()
        if signature != self._devices_last:
            self._devices_last = signature
            self._emit("devices_changed", list(self.monitors.values()))

    @property
    def by_address(self) -> Dict[int, Monitor]:
        return {m.address: m for m in self.monitors.values()}

    def heartbeat(self, *, force: bool = False) -> None:
        """Broadcast STAY_ONLINE if the interval has elapsed.

        Without this, addresses stop answering after ~2-3s. Cheap enough to
        call on every loop iteration.
        """
        if self.asleep:
            return
        # A deliberate, bounded silence used to let a monitor we have lost
        # track of drop its lease so RACE can find it again. Never gated on
        # anything that changes moment to moment: a single failed poll used
        # to mark every monitor offline, which stopped the heartbeat, which
        # expired every real lease, which failed every poll. See maybe_resync.
        if time.monotonic() < self._quiet_until:
            return
        now = time.monotonic()
        if force or now - self._last_heartbeat >= cid.HEARTBEAT_INTERVAL_S:
            try:
                self.transport.send(Request(BROADCAST_ADDR, cid.CID_STAY_ONLINE))
            except TransportError:
                logger.debug("heartbeat failed", exc_info=True)
            else:
                self._last_heartbeat = now

    def _race(self) -> Optional[int]:
        """Ask unassigned monitors to identify themselves. None when none left."""
        try:
            resp = self.transport.request(Request(BROADCAST_ADDR, cid.CID_RACE))
        except (DeviceTimeout, TransportError):
            return None
        if len(resp.payload) != 3:
            raise ProtocolError(f"unexpected RACE reply: {resp.payload!r}")
        return int.from_bytes(resp.payload, "big")

    def _assign(self, serial: int, address: int) -> None:
        resp = self.transport.request(Request(
            MULTICAST_ADDR, cid.CID_SET_RID,
            serial.to_bytes(3, "big") + bytes((address,)),
        ))
        if resp.payload != bytes((address,)):
            raise ProtocolError(
                f"address {address} rejected for serial {serial}: {resp.payload!r}")

    def discover(self) -> List[Monitor]:
        """Find every monitor and give each a fresh address.

        Safe to re-run at any time: a monitor whose lease expired becomes
        immediately re-discoverable (measured T2 ~= 0s), and one that is still
        assigned simply will not answer RACE.
        """
        if self.asleep:
            # RACE would wake them. Discovery resumes on the next wake().
            return []
        self.heartbeat(force=True)
        # Only monitors still holding a live lease occupy an address. Counting
        # offline ones too would push each recovery cycle higher (2,3,4 ->
        # 5,6,7 -> ...) until numbering ran past MAX_ADDRESS and discovery
        # quietly stopped finding anything.
        taken = {m.address for m in self.monitors.values() if m.online}
        next_addr = max(taken, default=ADAPTER_ADDR) + 1
        found: List[Monitor] = []

        while next_addr < MAX_ADDRESS:
            try:
                serial = self._race()
            except ProtocolError:
                # A monitor mid-boot can answer RACE with something we cannot
                # read. Resynchronise and stop this pass; the next one is two
                # seconds away.
                logger.debug("malformed RACE reply", exc_info=True)
                self.transport.drain(timeout_ms=20)
                break
            if serial is None:
                break

            try:
                self._assign(serial, next_addr)
            except (ProtocolError, TransportError):
                # Critical: the monitor may have taken the address anyway. If
                # we abandon it here it stops answering RACE, and with the
                # heartbeat gated on online_count its lease expires within a
                # few seconds and the next pass finds it again. Recording it
                # as offline keeps it visible in the meantime.
                logger.warning("address %d not confirmed for serial %s; "
                               "will retry", next_addr, serial, exc_info=True)
                self.monitors.setdefault(
                    serial, Monitor(serial=serial, address=next_addr)
                ).online = False
                self.transport.drain(timeout_ms=20)
                break

            existing = self.monitors.get(serial)
            if existing is not None:
                # Same speaker, new lease. Preserve everything else.
                existing.address = next_addr
                existing.online = True
                monitor = existing
            else:
                monitor = Monitor(serial=serial, address=next_addr)
                self.monitors[serial] = monitor
            found.append(monitor)
            next_addr += 1
            self.heartbeat()

        for monitor in found:
            if not monitor.model:
                # Descriptive queries only; a failure here must not cost us
                # the monitor itself.
                self._identify(monitor)

        if found:
            # Anything that just joined the bus booted at its stored startup
            # level, which Genelec ships as MAXIMUM. Bring it to the level the
            # rest of the system is at before anyone hears it. Skipped while a
            # guarded operation owns the volume -- that path is already
            # holding silence deliberately.
            if not self._busy and self.volume_db is not None:
                self._write_volume(self.volume_db)

        # Announce whenever the list actually changed -- including speakers
        # that went away, which used to go unreported and leave the UI stale.
        self._emit_devices_if_changed()
        return found

    def _identify(self, monitor: Monitor) -> None:
        """One-off descriptive queries. Values never change, so cache them."""
        try:
            hw = self.transport.request(
                Request(monitor.address, cid.CID_HARDWARE_QUERY))
            monitor.model = hw.payload.rstrip(b"\0").decode(
                "utf-8", "replace").rsplit(" ", 5)[0]
            sw = self.transport.request(
                Request(monitor.address, cid.CID_SOFTWARE_QUERY2))
            monitor.software = sw.payload.rstrip(b"\0").strip().decode(
                "utf-8", "replace")
            bc = self.transport.request(
                Request(monitor.address, cid.CID_BAR_CODE, b"\x01"))
            monitor.barcode = bc.payload.decode("utf-8", "replace")
        except (DeviceTimeout, ProtocolError, TransportError):
            logger.debug("identification failed for %s", monitor, exc_info=True)

    def identify_adapter(self) -> Adapter:
        for attr, request, transform in (
            ("software", Request(ADAPTER_ADDR, cid.CID_SOFTWARE_QUERY2),
             lambda p: p.rstrip(b"\0").strip().decode("utf-8", "replace")),
            ("barcode", Request(ADAPTER_ADDR, cid.CID_BAR_CODE, b"\x01"),
             lambda p: p.decode("utf-8", "replace")),
            ("mic_serial", Request(ADAPTER_ADDR, cid.CID_MIC_SERIAL, b"\x82\x44"),
             lambda p: p.decode("utf-8", "replace").strip()),
        ):
            try:
                setattr(self.adapter, attr,
                        transform(self.transport.request(request).payload))
            except (DeviceTimeout, ProtocolError, TransportError):
                logger.debug("adapter query %r failed", attr, exc_info=True)
        return self.adapter

    # -- recovery --------------------------------------------------------

    def _with_recovery(self, fn: Callable[[], object],
                       offline: Optional[Monitor] = None) -> object:
        """Run fn, and on a lease expiry re-discover once and retry.

        Rate limited. A monitor that is booting, powered off or unplugged
        times out on every poll, and re-discovering each time produced a storm
        of several rediscoveries a second that drowned the bus and prevented
        any real work -- including getting freshly woken monitors down from
        their factory-maximum startup level.
        """
        try:
            return fn()
        except DeviceTimeout:
            now = time.monotonic()
            if now - self._last_rediscover < REDISCOVER_COOLDOWN_S:
                raise
            self._last_rediscover = now
            logger.info("address lease expired; re-discovering")
            if offline is not None:
                # Only the one that actually failed. Marking all of them was
                # harmless while the heartbeat ran unconditionally, but it is
                # a lie about the other speakers and it made every timeout
                # look like a total bus loss.
                offline.online = False
            self._emit_devices_if_changed()
            self.discover()
            return fn()

    # -- polling ---------------------------------------------------------

    def poll_adapter(self) -> Adapter:
        """Read the knob position and microphone level."""
        resp = self.transport.request(Request(ADAPTER_ADDR, cid.CID_POLL))
        try:
            status = decode_adapter_status(resp.payload)
        except ProtocolError:
            self.transport.drain(timeout_ms=20)
            raise
        if status.volume_db is not None:
            previous = self.adapter.knob_db
            self.adapter.knob_db = status.volume_db
            if previous != status.volume_db:
                # The pot moved (or this is the first reading). Software
                # writes cannot move it, so this is the user's hand.
                if self.follow_knob and not self._busy and not self.asleep:
                    # Deliberately unclamped: the ceiling guards programmatic
                    # writes, which have no physical act behind them. Clamping
                    # the knob would make the hardware feel broken above the
                    # limit and would be a regression from how it behaves with
                    # no software running at all.
                    self.set_volume(status.volume_db, clamp=False)
                if previous is not None:
                    self._emit("knob_moved", status.volume_db)
        self.adapter.mic_raw = status.mic_raw
        self._emit("adapter_status", self.adapter)
        return self.adapter

    def poll_monitor(self, monitor: Monitor) -> Optional[Monitor]:
        """Read one monitor. Returns None when it had nothing new to report."""
        if self.asleep:
            return None

        def go():
            return self.transport.request(Request(monitor.address, cid.CID_POLL))

        resp = self._with_recovery(go, offline=monitor)
        if resp.is_empty_ack:
            # Rate limit, not a dropout: keep the previous reading.
            return None

        if len(resp.payload) < MIN_TLV_PAYLOAD:
            # Intact (the CRC passed) but too short to be tag-value data: a
            # tag needs at least one value byte after it. Freshly woken
            # monitors answer a poll with a short status byte before they
            # have measurements to report. Not an error, and not a desync --
            # a desync hands us someone else's *well formed* payload, which
            # is caught below.
            logger.debug("%s: short poll reply %r, no measurements yet",
                         monitor, resp.payload)
            return None

        try:
            status = decode_monitor_status(resp.payload)
        except ProtocolError:
            # We were handed someone else's reply. The transport had already
            # returned by this point, so its own resync never ran.
            self.transport.drain(timeout_ms=20)
            raise
        monitor.temperature_c = status.temperature_c
        monitor.tags = status.tags
        monitor.online = True
        self._emit("monitor_status", monitor)
        return monitor

    # -- control ---------------------------------------------------------

    def _write_volume(self, db: float) -> None:
        """Send a level without touching the volume model.

        Used for safety ducking, where the user's intended level must survive
        the operation unchanged.
        """
        db = max(VOLUME_MIN_DB, min(VOLUME_MAX_DB, float(db)))
        self.transport.send(Request(
            BROADCAST_ADDR, cid.CID_VOLUME_GLM,
            db_to_sint24(db).to_bytes(3, "big", signed=True)))

    @contextmanager
    def guarded(self, settle: float = 0.0):
        """Duck to a safe level for the duration of a disruptive operation.

        Restores the user's intended level afterwards, re-asserting it a few
        times because monitors that were booting during the operation may not
        have been listening the first time.
        """
        intended = self.volume_db
        self._busy = True
        self._write_volume(SAFE_DUCK_DB)
        try:
            yield
        finally:
            self._busy = False
            target = intended
            if target is None:
                target = (self.adapter.knob_db
                          if self.adapter.knob_db is not None
                          else self.default_volume_db)
            if settle:
                deadline = time.monotonic() + settle
                while time.monotonic() < deadline:
                    self._write_volume(SAFE_DUCK_DB)
                    time.sleep(WAKE_POLL_S)
            for _ in range(3):
                self.set_volume(target, clamp=False)
                time.sleep(0.05)

    def set_volume(self, db: float, *, clamp: bool = True,
                   _keep_mute: bool = False) -> float:
        """Broadcast master volume, in dBFS. Returns the value actually sent.

        Always clamped to the documented protocol range. `clamp` additionally
        applies the user's safety ceiling, and should stay True for every
        programmatic write -- a stray value here is audible in the room. It is
        False only when mirroring the physical knob, whose position the user
        has by definition just chosen and heard.
        """
        ceiling = self.max_volume_db if clamp else VOLUME_MAX_DB
        db = max(VOLUME_MIN_DB, min(ceiling, float(db)))
        self.volume_db = db
        if not _keep_mute and self.muted:
            # Any level write cancels a mute -- including the knob mirror.
            # This has to be announced: silently flipping the flag left the
            # UI showing MUTED after the knob had already taken the level
            # back, because nothing told it otherwise.
            self.muted = False
            self._emit("mute_changed", False)
        request = Request(BROADCAST_ADDR, cid.CID_VOLUME_GLM,
                          db_to_sint24(db).to_bytes(3, "big", signed=True))
        self.transport.send(request)
        self._emit("volume_set", db)
        return db

    def wake(self, volume_db: Optional[float] = None,
             settle_s: Optional[float] = None) -> None:
        """Wake every monitor, holding them silent until they are under control.

        Genelec documents that SAM monitors start at *maximum* level in
        standalone mode. A monitor booting is therefore a full-scale noise
        source until something tells it otherwise, and it cannot hear us until
        it has finished booting -- so setting the level once before the wakeup
        (which is what an earlier version did) protects nothing.

        Instead we hold the safe level down across the whole boot window, then
        settle to the intended level once monitors are answering again.
        """
        target = volume_db
        if target is None:
            target = (self.adapter.knob_db
                      if self.adapter.knob_db is not None
                      else self.default_volume_db)

        intended = self.volume_db
        self._busy = True
        self.asleep = False          # re-enables the heartbeat and discovery
        self._emit("sleep_changed", False)
        try:
            self._write_volume(SAFE_DUCK_DB)
            for data in (bytes([3, 0x7F]), bytes([3, 1])):
                request = Request(BROADCAST_ADDR, cid.CID_WAKEUP, data)
                self.transport.send(request)
                self.transport.send(request)

            # Broadcasts may be answered. Anything left unread here would be
            # handed to the next request as if it were its reply, shifting
            # every request/response pair from now on.
            self.transport.drain(timeout_ms=50)

            window = WAKE_SETTLE_S if settle_s is None else settle_s
            deadline = time.monotonic() + window
            expected = len(self.monitors)
            while time.monotonic() < deadline:
                self._write_volume(SAFE_DUCK_DB)   # hammer it while they boot
                self.heartbeat(force=True)
                try:
                    for monitor in self.monitors.values():
                        monitor.online = False
                    found = self.discover()
                except (ProtocolError, TransportError):
                    self.transport.drain(timeout_ms=20)
                    found = []
                online = sum(1 for m in self.monitors.values() if m.online)
                # Everything we knew about is back, or something answered when
                # we knew of nothing at all.
                if (expected and online >= expected) or (not expected and found):
                    break
                time.sleep(WAKE_POLL_S)

            self._write_volume(SAFE_DUCK_DB)
        finally:
            self._busy = False
            settle = intended if intended is not None else target
            for _ in range(3):
                self.set_volume(settle, clamp=False)
                time.sleep(0.05)
        self._emit("woken", self.volume_db)

    def shutdown(self) -> None:
        """Put every monitor to sleep, quietly.

        Ducked first: if a monitor ignores the shutdown or wakes again later,
        it must not be sitting at a loud level when it does.
        """
        self._busy = True
        try:
            self._write_volume(SAFE_DUCK_DB)
            time.sleep(0.05)
            for data in (bytes([3, 2]), bytes([3, 0])):
                request = Request(BROADCAST_ADDR, cid.CID_WAKEUP, data)
                self.transport.send(request)
                self.transport.send(request)
            self.transport.drain(timeout_ms=50)
        finally:
            self._busy = False
        for monitor in self.monitors.values():
            monitor.online = False
        # Set last: heartbeat and discovery check this, and both must stay
        # quiet from here until the user asks for a wake.
        self.stop_identify()
        self.asleep = True
        self._emit("sleep_changed", True)
        self._emit("shutdown", None)

    def clear_monitor_state(self, monitor: Monitor) -> None:
        """Return a monitor to normal operation (CID_BYPASS_QUERY = 0x00).

        Repair path. genlc's bypass(led_color=...) sends other values here,
        one of which freezes volume control; see commands.py.
        """
        def go():
            return self.transport.request(Request(
                monitor.address, cid.CID_BYPASS_QUERY,
                bytes((cid.STATE_NORMAL,))))

        self._with_recovery(go)
        self._emit("monitor_status", monitor)

    def clear_all_state(self) -> None:
        self._identify_until.clear()
        for monitor in self.monitors.values():
            self.clear_monitor_state(monitor)

    # -- identify --------------------------------------------------------
    #
    # The only LED control we have is CID_BYPASS_QUERY, and its "red" value
    # (0x02) also freezes that monitor's volume stage -- see commands.py. So
    # identify is deliberately: one speaker at a time, time limited, restored
    # by the bus loop rather than by a caller that might go away, and cleared
    # on shutdown. A speaker left in this state ignores volume changes.

    def start_identify(self, serial: int, seconds: float) -> bool:
        """Flag one monitor's LED for `seconds`. Returns False if unknown."""
        monitor = self.monitors.get(serial)
        if monitor is None:
            return False
        self.stop_identify()          # never leave two speakers flagged
        try:
            self._with_recovery(lambda: self.transport.request(Request(
                monitor.address, cid.CID_BYPASS_QUERY,
                bytes((cid.STATE_IDENTIFY,)))))
        except (ProtocolError, TransportError):
            logger.warning("identify failed for %s", monitor, exc_info=True)
            return False
        self._identify_until[serial] = time.monotonic() + seconds
        self._emit("identifying", serial)
        return True

    def stop_identify(self, serial: Optional[int] = None) -> None:
        """Return flagged monitors to normal. All of them when serial is None."""
        targets = ([serial] if serial is not None
                   else list(self._identify_until))
        for target in targets:
            self._identify_until.pop(target, None)
            monitor = self.monitors.get(target)
            if monitor is None:
                continue
            try:
                self.clear_monitor_state(monitor)
            except (ProtocolError, TransportError):
                logger.warning("could not clear identify on %s", monitor,
                               exc_info=True)
        if targets:
            self._emit("identifying", None)

    def maybe_resync(self) -> bool:
        """Let a lost monitor's lease expire, so RACE can find it again.

        A monitor that was assigned an address but never recorded answers
        neither its address nor RACE, and our keepalive would hold it in that
        state indefinitely. The escape is a bounded silence -- but silence
        also drops the leases of monitors that are working, so it is only
        entered once the bus has had nothing online for a good while, when
        there is nothing left to lose.
        """
        now = time.monotonic()
        if self.asleep or self.online_count:
            self._empty_since = None
            return False
        if self._empty_since is None:
            self._empty_since = now
            return False
        if now - self._empty_since < ORPHAN_RESYNC_AFTER_S:
            return False
        if now < self._quiet_until:
            return False

        logger.info("nothing online for %.0fs; going quiet for %.1fs so any "
                    "stranded monitor drops its lease",
                    now - self._empty_since, ORPHAN_QUIET_S)
        self._quiet_until = now + ORPHAN_QUIET_S
        self._empty_since = now + ORPHAN_QUIET_S
        return True

    def service_identify(self) -> None:
        """Restore any monitor whose identify window has elapsed.

        Called from the bus loop, so the restore happens even if whoever
        started it has gone away.
        """
        if not self._identify_until:
            return
        now = time.monotonic()
        for serial, deadline in list(self._identify_until.items()):
            if now >= deadline:
                self.stop_identify(serial)

    # -- mute ------------------------------------------------------------
    #
    # Implemented with volume, not CID_BYPASS_QUERY. There is no verified
    # mute command: the byte genlc labels "mute" is untested, and the
    # neighbouring value freezes volume control instead of silencing audio.
    # set_volume(-130) is the documented bottom of the GLM fader, fully
    # reversible, and behaves identically from the listener's point of view.

    def mute(self) -> float:
        """Silence the group, remembering the level to come back to."""
        if not self.muted:
            self._pre_mute_db = self.volume_db
            self.muted = True
        self.set_volume(VOLUME_MIN_DB, _keep_mute=True)
        self._emit("mute_changed", True)
        return VOLUME_MIN_DB

    def unmute(self) -> float:
        """Restore the level from before the mute."""
        self.muted = False
        target = self._pre_mute_db
        if target is None or target <= VOLUME_MIN_DB:
            target = self.default_volume_db
        self._emit("mute_changed", False)
        return self.set_volume(target)

    def toggle_mute(self) -> bool:
        self.unmute() if self.muted else self.mute()
        return self.muted

    def release_to_knob(self) -> float:
        """Return the level to wherever the physical knob is pointing.

        The resting state of the system. Presets and mute are temporary
        overrides on top of it, so cancelling one lands back here.
        """
        self.muted = False
        target = (self.adapter.knob_db if self.adapter.knob_db is not None
                  else self.default_volume_db)
        self._emit("mute_changed", False)
        return self.set_volume(target, clamp=False)
