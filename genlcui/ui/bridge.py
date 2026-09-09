"""QObject bridge between the bus thread and QML.

Events arrive on the worker thread. They are re-emitted through a private
queued signal so every property change lands on the GUI thread -- touching Qt
properties directly from the worker would be a data race.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from PySide6.QtCore import (
    Property, QObject, Qt, Signal, Slot,
)

from ..core.controller import Controller
from ..core.settings import Settings
from ..core.util import mic_raw_to_dbspl

logger = logging.getLogger(__name__)


class Bridge(QObject):
    """Everything QML can see or do."""

    connectedChanged = Signal()
    knobChanged = Signal()
    volumeChanged = Signal()
    micChanged = Signal()
    mutedChanged = Signal()
    speakersChanged = Signal()
    presetsChanged = Signal()
    statusChanged = Signal()
    activePresetChanged = Signal()

    # Transient, for toasts and confirmation prompts
    errorRaised = Signal(str)
    presetCaptured = Signal(int, float, bool)   # index, dB, exceedsCeiling

    _event = Signal(str, object)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._connected = False
        self._knob_db = None
        self._volume_db = None
        self._mic_raw = None
        self._muted = False
        self._status = "Starting…"
        self._active_preset = -1
        self._speakers: List[Dict[str, Any]] = []

        self.controller = Controller(settings, on_event=self._from_worker)
        self._event.connect(self._on_event, Qt.QueuedConnection)

    # -- worker -> GUI ---------------------------------------------------

    def _from_worker(self, name: str, payload: Any) -> None:
        """Called on the bus thread. Hand off, do not touch state here."""
        self._event.emit(name, payload)

    @Slot(str, object)
    def _on_event(self, name: str, payload: Any) -> None:
        if name == "connected":
            self._connected = True
            self._set_status("Connected")
            self.connectedChanged.emit()
        elif name in ("disconnected", "stopped"):
            self._connected = False
            self._set_status("Adapter not available"
                             if name == "disconnected" else "Stopped")
            self.connectedChanged.emit()
        elif name == "adapter_status":
            self._update_adapter(payload)
        elif name == "knob_moved":
            # The pot took control back; any recalled preset is no longer
            # what you are hearing.
            if self._active_preset != -1:
                self._active_preset = -1
                self.activePresetChanged.emit()
        elif name in ("devices_changed", "monitor_status"):
            self._refresh_speakers()
        elif name == "volume_set":
            self._volume_db = payload
            self.volumeChanged.emit()
        elif name == "mute_changed":
            self._muted = bool(payload)
            self.mutedChanged.emit()
        elif name == "preset_recalled":
            self._active_preset = int(payload)
            self.activePresetChanged.emit()
        elif name == "preset_captured":
            index, db = payload
            self.presetsChanged.emit()
            self.presetCaptured.emit(index, db,
                                     self._settings.exceeds_ceiling(db))
        elif name == "error":
            logger.warning("controller error: %s", payload)
            self.errorRaised.emit(str(payload))

    def _update_adapter(self, adapter) -> None:
        if adapter.knob_db != self._knob_db:
            self._knob_db = adapter.knob_db
            self.knobChanged.emit()
        if adapter.mic_raw != self._mic_raw:
            self._mic_raw = adapter.mic_raw
            self.micChanged.emit()

    def _refresh_speakers(self) -> None:
        session = self.controller._session
        if session is None:
            return
        rows = []
        for monitor in sorted(session.monitors.values(),
                              key=lambda m: (not m.is_subwoofer, m.serial)):
            rows.append({
                "serial": str(monitor.serial),
                "name": self._settings.name_for(monitor.serial,
                                                monitor.display_name),
                "model": monitor.model or "SAM",
                "role": "Subwoofer" if monitor.is_subwoofer else "Monitor",
                "temperature": monitor.temperature_c if monitor.temperature_c
                               is not None else -1,
                "address": monitor.address,
                "online": monitor.online,
            })
        if rows != self._speakers:
            self._speakers = rows
            self.speakersChanged.emit()

    def _set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    # -- properties ------------------------------------------------------

    @Property(bool, notify=connectedChanged)
    def connected(self) -> bool:
        return self._connected

    @Property(float, notify=knobChanged)
    def knobDb(self) -> float:
        return self._knob_db if self._knob_db is not None else -130.0

    @Property(bool, notify=knobChanged)
    def knobKnown(self) -> bool:
        return self._knob_db is not None

    @Property(float, notify=volumeChanged)
    def volumeDb(self) -> float:
        return self._volume_db if self._volume_db is not None else -130.0

    @Property(float, notify=micChanged)
    def micDbSpl(self) -> float:
        return mic_raw_to_dbspl(self._mic_raw)

    @Property(bool, notify=micChanged)
    def micPresent(self) -> bool:
        return self._mic_raw is not None and self._mic_raw > 0

    @Property(bool, notify=mutedChanged)
    def muted(self) -> bool:
        return self._muted

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(int, notify=activePresetChanged)
    def activePreset(self) -> int:
        return self._active_preset

    @Property("QVariantList", notify=speakersChanged)
    def speakers(self) -> List[Dict[str, Any]]:
        return self._speakers

    @Property("QVariantList", notify=presetsChanged)
    def presets(self) -> List[Dict[str, Any]]:
        return [{"index": i, "name": p.name,
                 "db": p.db if p.db is not None else 0.0, "isSet": p.is_set}
                for i, p in enumerate(self._settings.presets)]

    @Property(float, constant=True)
    def maxVolumeDb(self) -> float:
        return self._settings.max_volume_db

    @Property(bool, constant=True)
    def trayAvailable(self) -> bool:
        """Whether hiding the window leaves anything to get back to."""
        from PySide6.QtWidgets import QSystemTrayIcon

        return QSystemTrayIcon.isSystemTrayAvailable()

    # -- slots -----------------------------------------------------------

    @Slot()
    def start(self) -> None:
        self.controller.start()

    @Slot()
    def stop(self) -> None:
        self.controller.stop()

    @Slot()
    def quitApplication(self) -> None:
        """Exit. The bus is released on the way out, which hands volume
        control back to the adapter -- the knob keeps working without us."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.quit()       # aboutToQuit stops the controller and restores
                             # the knob position before the thread joins

    @Slot(int)
    def recallPreset(self, index: int) -> None:
        self.controller.recall_preset(index)

    @Slot(int)
    def capturePreset(self, index: int) -> None:
        self.controller.capture_preset(index)

    @Slot(int, str)
    def renamePreset(self, index: int, name: str) -> None:
        self._settings.presets[index].name = name or f"Preset {index + 1}"
        self._settings.save()
        self.presetsChanged.emit()

    @Slot(str, str)
    def renameSpeaker(self, serial: str, name: str) -> None:
        self._settings.set_name(int(serial), name)
        self._settings.save()
        self._refresh_speakers()

    @Slot()
    def toggleMute(self) -> None:
        self.controller.toggle_mute()

    @Slot()
    def wake(self) -> None:
        self.controller.wake()

    @Slot()
    def sleep(self) -> None:
        self.controller.shutdown_speakers()

    @Slot()
    def rediscover(self) -> None:
        self.controller.rediscover()

    @Slot()
    def repair(self) -> None:
        """Return every monitor to normal operation."""
        self.controller.clear_state()

    @Slot(float)
    def setMaxVolume(self, db: float) -> None:
        self._settings.max_volume_db = db
        self._settings.save()
        session = self.controller._session
        if session is not None:
            self.controller.submit(
                "apply_ceiling",
                lambda s: setattr(s, "max_volume_db", db))
