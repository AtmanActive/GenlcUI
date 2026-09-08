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

# Agreed with the user: -30 dBFS is the loudest they ever tolerate, and -50
# is a comfortable default. The ceiling applies to every write.
SAFETY_MAX_DB = -30.0
DEFAULT_VOLUME_DB = -50.0


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

    # -- events ----------------------------------------------------------

    def _emit(self, name: str, payload: object = None) -> None:
        try:
            self._on_event(name, payload)
        except Exception:  # noqa: BLE001 - a bad listener must not kill the bus
            logger.exception("event listener raised for %r", name)

    # -- addressing ------------------------------------------------------

    @property
    def by_address(self) -> Dict[int, Monitor]:
        return {m.address: m for m in self.monitors.values()}

    def heartbeat(self, *, force: bool = False) -> None:
        """Broadcast STAY_ONLINE if the interval has elapsed.

        Without this, addresses stop answering after ~2-3s. Cheap enough to
        call on every loop iteration.
        """
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
        self.heartbeat(force=True)
        # Only monitors still holding a live lease occupy an address. Counting
        # offline ones too would push each recovery cycle higher (2,3,4 ->
        # 5,6,7 -> ...) until numbering ran past MAX_ADDRESS and discovery
        # quietly stopped finding anything.
        taken = {m.address for m in self.monitors.values() if m.online}
        next_addr = max(taken, default=ADAPTER_ADDR) + 1
        found: List[Monitor] = []

        while next_addr < MAX_ADDRESS:
            serial = self._race()
            if serial is None:
                break
            self._assign(serial, next_addr)
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
                self._identify(monitor)
        if found:
            self._emit("devices_changed", list(self.monitors.values()))
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

    def _with_recovery(self, fn: Callable[[], object]) -> object:
        """Run fn, and on a lease expiry re-discover once and retry.

        Measured recovery cost is ~30ms, so this is invisible in the UI and
        does not warrant surfacing an error to the user.
        """
        try:
            return fn()
        except DeviceTimeout:
            logger.info("address lease expired; re-discovering")
            for monitor in self.monitors.values():
                monitor.online = False
            self.discover()
            return fn()

    # -- polling ---------------------------------------------------------

    def poll_adapter(self) -> Adapter:
        """Read the knob position and microphone level."""
        resp = self.transport.request(Request(ADAPTER_ADDR, cid.CID_POLL))
        status = decode_adapter_status(resp.payload)
        if status.volume_db is not None:
            previous = self.adapter.knob_db
            self.adapter.knob_db = status.volume_db
            if previous != status.volume_db:
                # The pot moved (or this is the first reading). Software
                # writes cannot move it, so this is the user's hand.
                if self.follow_knob:
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
        def go():
            return self.transport.request(Request(monitor.address, cid.CID_POLL))

        resp = self._with_recovery(go)
        if resp.is_empty_ack:
            # Rate limit, not a dropout: keep the previous reading.
            return None
        status = decode_monitor_status(resp.payload)
        monitor.temperature_c = status.temperature_c
        monitor.tags = status.tags
        monitor.online = True
        self._emit("monitor_status", monitor)
        return monitor

    # -- control ---------------------------------------------------------

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
        if not _keep_mute:
            self.muted = False
        request = Request(BROADCAST_ADDR, cid.CID_VOLUME_GLM,
                          db_to_sint24(db).to_bytes(3, "big", signed=True))
        self.transport.send(request)
        self._emit("volume_set", db)
        return db

    def wake(self, volume_db: Optional[float] = None) -> None:
        """Wake every monitor at a known volume.

        Volume first, deliberately. Genelec documents that SAM monitors start
        at *maximum* level by default in standalone mode, so a bare wakeup
        hands control to whatever is stored in speaker flash.

        With no level given, the pot's current position is used: it is where
        the physical control says the system should be, so it is both safe
        and unsurprising.
        """
        if volume_db is None:
            volume_db = (self.adapter.knob_db
                         if self.adapter.knob_db is not None
                         else self.default_volume_db)
        self.set_volume(volume_db)
        time.sleep(0.05)
        for data in (bytes([3, 0x7F]), bytes([3, 1])):
            request = Request(BROADCAST_ADDR, cid.CID_WAKEUP, data)
            self.transport.send(request)
            self.transport.send(request)
        time.sleep(0.5)
        self.discover()
        self.set_volume(volume_db)     # re-assert once they are listening
        self._emit("woken", volume_db)

    def shutdown(self) -> None:
        for data in (bytes([3, 2]), bytes([3, 0])):
            request = Request(BROADCAST_ADDR, cid.CID_WAKEUP, data)
            self.transport.send(request)
            self.transport.send(request)
        for monitor in self.monitors.values():
            monitor.online = False
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
        for monitor in self.monitors.values():
            self.clear_monitor_state(monitor)

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
