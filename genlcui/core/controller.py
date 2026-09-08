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
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from . import commands as cid
from .protocol import DeviceTimeout, ProtocolError
from .session import Session
from .settings import Settings
from .transport import Transport, TransportError

logger = logging.getLogger(__name__)

GLM_VID = 0x1781
GLM_PID = 0x0E39

RECONNECT_DELAY_S = 2.0
IDLE_SLEEP_S = 0.02


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

    def recall_preset(self, index: int) -> None:
        preset = self.settings.presets[index]
        if not preset.is_set:
            self._emit("error", f"Preset '{preset.name}' has no level stored yet")
            return
        self.submit("recall_preset", lambda s: s.set_volume(preset.db))
        self._emit("preset_recalled", index)

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
        self.submit("mute", lambda s: s.mute())

    def unmute(self) -> None:
        self.submit("unmute", lambda s: s.unmute())

    def toggle_mute(self) -> None:
        self.submit("toggle_mute", lambda s: s.toggle_mute())

    def wake(self) -> None:
        self.submit("wake", lambda s: s.wake())

    def shutdown_speakers(self) -> None:
        self.submit("shutdown", lambda s: s.shutdown())

    def rediscover(self) -> None:
        self.submit("discover", lambda s: s.discover())

    def clear_state(self) -> None:
        """Repair: return every monitor to normal operation."""
        self.submit("clear_state", lambda s: s.clear_all_state())

    # -- worker ----------------------------------------------------------

    def _emit(self, name: str, payload: Any = None) -> None:
        try:
            self._on_event(name, payload)
        except Exception:  # noqa: BLE001
            logger.exception("event listener raised for %r", name)

    def _connect(self) -> Optional[Session]:
        try:
            transport = Transport(self._open_device())
        except Exception as exc:  # noqa: BLE001
            self._emit("disconnected", str(exc))
            return None
        session = Session(transport, on_event=self._emit)
        session.max_volume_db = self.settings.max_volume_db
        session.default_volume_db = self.settings.default_volume_db
        try:
            session.identify_adapter()
            session.discover()
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

                now = time.monotonic()
                if now >= next_adapter_poll:
                    next_adapter_poll = now + cid.ADAPTER_POLL_INTERVAL_S
                    session.poll_adapter()

                # Monitors refresh ~1 Hz, so poll them round-robin rather than
                # all at once: it spreads bus load and keeps latency even.
                monitors = list(session.monitors.values())
                if monitors and now >= next_monitor_poll:
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
