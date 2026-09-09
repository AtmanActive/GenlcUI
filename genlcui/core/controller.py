"""Background controller owning the bus.

One worker thread holds the HID device and drives everything: the keepalive
heartbeat, the two poll cadences, and every command the UI submits. Nothing
else may touch the transport -- responses carry no source address, so two
concurrent callers would silently swap replies.

Why a resident thread rather than connect-on-demand: address leases expire
after ~2-3s of bus silence (docs/PROTOCOL.md), so the heartbeat has to run
continuously or every user action would begin with a re-discovery.

No Qt here. The Qt layer subscribes via `on_event`.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import commands as cid
from . import hidinfo
from .protocol import DeviceTimeout, ProtocolError
from .session import Session
from .settings import Settings
from .transport import Transport, TransportError

logger = logging.getLogger(__name__)

GLM_VID = 0x1781
GLM_PID = 0x0E39

RECONNECT_DELAY_S = 2.0
IDLE_SLEEP_S = 0.02

# A desynchronised bus produces a decode error on every poll. Surfacing each
# one floods the log and the UI with the same message many times a second.
ERROR_REPEAT_S = 5.0

# How long a speaker's LED stays flagged during identify. Kept short: the
# command that lights it also freezes that monitor's volume stage.
IDENTIFY_SECONDS = 5.0


@dataclass
class Command:
    name: str
    fn: Callable[[Session], Any]
    reply: Optional["queue.Queue"] = None


class Controller:
    """Owns a worker thread that keeps the GLM bus alive."""

    def __init__(self, settings: Settings,
                 on_event: Optional[Callable[[str, Any], None]] = None,
                 open_device: Optional[Callable[[], Any]] = None):
        self.settings = settings
        self._on_event = on_event or (lambda *_: None)
        self._open_device = open_device or self._open_hid
        self._commands: "queue.Queue[Command]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._session: Optional[Session] = None
        self.connected = False
        self._recent_errors: dict = {}

        # The four presets and mute form one mutually exclusive group. None
        # selected means "following the knob", which is the resting state --
        # so cancelling any of them lands back on the knob's position.
        self.selection = None        # None | ("preset", int) | ("mute",)

    # -- lifecycle -------------------------------------------------------

    @staticmethod
    def _open_hid():
        import hid
        return hid.Device(GLM_VID, GLM_PID)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="glm-bus",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    # -- command submission ----------------------------------------------

    def submit(self, name: str, fn: Callable[[Session], Any]) -> None:
        """Queue work for the bus thread. Returns immediately."""
        self._commands.put(Command(name=name, fn=fn))

    def call(self, name: str, fn: Callable[[Session], Any],
             timeout: float = 5.0) -> Any:
        """Queue work and wait for its result. Never call from the bus thread."""
        reply: "queue.Queue" = queue.Queue(maxsize=1)
        self._commands.put(Command(name=name, fn=fn, reply=reply))
        ok, value = reply.get(timeout=timeout)
        if not ok:
            raise value
        return value

    # -- convenience actions ---------------------------------------------

    def set_volume(self, db: float) -> None:
        self.submit("set_volume", lambda s: s.set_volume(db))

    def _set_selection(self, selection) -> None:
        self.selection = selection
        self._emit("selection_changed", selection)

    def clear_selection(self) -> None:
        """Drop any preset or mute and go back to following the knob."""
        self._set_selection(None)
        self.submit("release_to_knob", lambda s: s.release_to_knob())

    def recall_preset(self, index: int) -> None:
        preset = self.settings.presets[index]
        if not preset.is_set:
            self._emit("error", f"Preset '{preset.name}' has no level stored yet")
            return
        if self.selection == ("preset", index):
            self.clear_selection()       # clicking the active one undoes it
            return
        self._set_selection(("preset", index))
        self.submit("recall_preset", lambda s: s.set_volume(preset.db))

    def capture_preset(self, index: int) -> None:
        """Store the knob's current position into a slot."""
        def go(session: Session):
            knob = session.adapter.knob_db
            if knob is None:
                raise RuntimeError("knob position not known yet")
            return knob
        try:
            knob = self.call("read_knob", go)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", f"Could not read the knob: {exc}")
            return
        self.settings.capture_preset(index, knob)
        self.settings.save()
        self._emit("preset_captured", (index, knob))

    def mute(self) -> None:
        self._set_selection(("mute",))
        self.submit("mute", lambda s: s.mute())

    def unmute(self) -> None:
        self.clear_selection()

    def toggle_mute(self) -> None:
        self.unmute() if self.selection == ("mute",) else self.mute()

    def wake(self) -> None:
        self.submit("wake", lambda s: s.wake())

    def shutdown_speakers(self) -> None:
        self.submit("shutdown", lambda s: s.shutdown())

    def identify_speaker(self, serial: int,
                         seconds: float = IDENTIFY_SECONDS) -> None:
        """Flag one speaker's LED so the user can see which cabinet it is."""
        self.submit("identify",
                    lambda s: s.start_identify(int(serial), seconds))

    def stop_identify(self) -> None:
        self.submit("stop_identify", lambda s: s.stop_identify())

    def clear_state(self) -> None:
        """Repair: return every monitor to normal operation."""
        self.submit("clear_state", lambda s: s.clear_all_state())

    # -- worker ----------------------------------------------------------

    def _emit(self, name: str, payload: Any = None) -> None:
        if name == "knob_moved" and self.selection is not None:
            # The hand on the knob outranks any override. Drop the selection
            # without writing a level -- the session has already applied the
            # knob's position by the time this fires.
            self.selection = None
            self._emit("selection_changed", None)
        if name == "error" and self._suppress_error(str(payload)):
            return
        try:
            self._on_event(name, payload)
        except Exception:  # noqa: BLE001
            logger.exception("event listener raised for %r", name)

    @staticmethod
    def _error_key(message: str) -> str:
        """Reduce an error to its shape, ignoring the bytes that vary.

        A desynchronised bus raises the same three or four failures over and
        over with different values each time ("checksum 0xa != computed 0xb",
        "truncated tag 0xe6 at offset 18 in b'...'"). Keying on the raw text
        would treat every one as new.
        """
        head = message.split(" in b", 1)[0].split(" for payload", 1)[0]
        return re.sub(r"0x[0-9a-fA-F]+|\d+", "#", head)[:60]

    def _suppress_error(self, message: str) -> bool:
        """Rate limit repeats of the same error shape."""
        key = self._error_key(message)
        now = time.monotonic()
        last = self._recent_errors.get(key)
        if last is not None and now - last < ERROR_REPEAT_S:
            logger.debug("suppressed repeat error: %s", message)
            return True
        self._recent_errors[key] = now
        return False

    def _connect(self) -> Optional[Session]:
        try:
            transport = Transport(self._open_device())
        except Exception as exc:  # noqa: BLE001
            self._emit("disconnected", str(exc))
            return None
        session = Session(transport, on_event=self._emit)
        details = hidinfo.enumerate_adapter(GLM_VID, GLM_PID)
        session.adapter.manufacturer = details.get("manufacturer", "")
        session.adapter.product = details.get("product", "")
        session.adapter.hid_path = details.get("path", "")
        session.adapter.usb_location = (
            hidinfo.usb_location(session.adapter.hid_path) or "")
        session.max_volume_db = self.settings.max_volume_db
        session.default_volume_db = self.settings.default_volume_db
        try:
            session.identify_adapter()
            session.discover()
            self._emit("devices_changed", list(session.monitors.values()))
        except (ProtocolError, TransportError) as exc:
            self._emit("error", f"Discovery failed: {exc}")
        self.connected = True
        self._emit("connected", session.adapter)
        return session

    def _drain_commands(self, session: Session) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                result = command.fn(session)
            except Exception as exc:  # noqa: BLE001
                logger.warning("command %r failed", command.name, exc_info=True)
                if command.reply is not None:
                    command.reply.put((False, exc))
                else:
                    self._emit("error", f"{command.name}: {exc}")
            else:
                if command.reply is not None:
                    command.reply.put((True, result))

    def _run(self) -> None:
        session: Optional[Session] = None
        next_adapter_poll = 0.0
        monitor_cursor = 0
        next_monitor_poll = 0.0
        next_discovery = 0.0

        while not self._stop.is_set():
            if session is None:
                session = self._connect()
                if session is None:
                    self._stop.wait(RECONNECT_DELAY_S)
                    continue
                self._session = session

            try:
                self._drain_commands(session)
                session.heartbeat()
                # Restores a flagged LED even if whoever asked has gone away.
                session.service_identify()

                now = time.monotonic()
                if now >= next_adapter_poll:
                    next_adapter_poll = now + cid.ADAPTER_POLL_INTERVAL_S
                    session.poll_adapter()

                # Pick up speakers switched on after launch. Nothing else
                # would: the poll loop only visits known monitors, so a new
                # one generates no timeout and never triggers recovery.
                # Suppressed while asleep -- RACE is a roll-call that wakes
                # the speakers we just shut down.
                if now >= next_discovery and not session.asleep:
                    next_discovery = now + cid.DISCOVERY_INTERVAL_S
                    session.discover()

                # Monitors refresh ~1 Hz, so poll them round-robin rather than
                # all at once: it spreads bus load and keeps latency even.
                monitors = list(session.monitors.values())
                if monitors and now >= next_monitor_poll and not session.asleep:
                    interval = cid.MONITOR_POLL_INTERVAL_S / len(monitors)
                    next_monitor_poll = now + interval
                    monitor_cursor %= len(monitors)
                    session.poll_monitor(monitors[monitor_cursor])
                    monitor_cursor += 1

            except (TransportError, OSError) as exc:
                logger.warning("bus lost: %s", exc)
                self.connected = False
                self._emit("disconnected", str(exc))
                try:
                    session.transport.close()
                except Exception:  # noqa: BLE001
                    pass
                session = self._session = None
                self._stop.wait(RECONNECT_DELAY_S)
                continue
            except DeviceTimeout:
                # A monitor stopped answering and re-discovery did not bring
                # it back; it is probably powered off. Not fatal.
                logger.debug("device timeout survived recovery", exc_info=True)
            except ProtocolError as exc:
                self._emit("error", str(exc))

            self._stop.wait(IDLE_SLEEP_S)

        if session is not None:
            # Never exit leaving a speaker flagged: that state also freezes
            # its volume, and nothing would be left running to undo it.
            try:
                session.stop_identify()
            except Exception:  # noqa: BLE001
                logger.debug("could not clear identify on exit", exc_info=True)
            # Leave the system matching the physical control. Once we release
            # the bus the adapter resumes applying the pot, but only from the
            # next time it moves -- so if we exit with a preset active, the
            # speakers would sit at the preset level until touched. Writing
            # the knob position on the way out makes exit predictable.
            try:
                if session.follow_knob and session.adapter.knob_db is not None:
                    session.set_volume(session.adapter.knob_db, clamp=False)
            except Exception:  # noqa: BLE001 - never block shutdown
                logger.debug("could not restore knob level on exit",
                             exc_info=True)
            session.transport.close()
        self.connected = False
        self._emit("stopped", None)
