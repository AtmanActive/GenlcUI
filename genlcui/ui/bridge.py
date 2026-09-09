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
from PySide6.QtGui import QGuiApplication

from .. import APP_HOMEPAGE, APP_TITLE, __version__
from ..core import autostart
from ..core.hidinfo import firmware_version
from ..core.controller import Controller
from ..core.settings import Settings
from ..core.util import mic_raw_to_dbspl
from ..resources import PRESET_DOT_COLOURS
from .theming import (
    MODES, TEXT_SIZES, TEXT_SIZE_NAMES, THEME_NAMES, build_palette, resolve_mode,
)

logger = logging.getLogger(__name__)


class Bridge(QObject):
    """Everything QML can see or do."""

    connectedChanged = Signal()
    knobChanged = Signal()
    volumeChanged = Signal()
    micChanged = Signal()
    mutedChanged = Signal()
    asleepChanged = Signal()
    speakersChanged = Signal()
    presetsChanged = Signal()
    statusChanged = Signal()
    activePresetChanged = Signal()

    # Transient, for toasts and confirmation prompts
    errorRaised = Signal(str)
    presetCaptured = Signal(int, float, bool)   # index, dB, exceedsCeiling
    ceilingCaptured = Signal(float)
    repairRequested = Signal()
    showWindowRequested = Signal()
    permissionProblem = Signal(str)      # the device path we cannot open
    hideWindowRequested = Signal()
    shortcutsChanged = Signal()
    appearanceChanged = Signal()
    settingsChanged = Signal()

    _event = Signal(str, object)

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._connected = False
        self._knob_db = None
        self._volume_db = None
        self._mic_raw = None
        self._muted = False
        self._asleep = False
        self._identifying = ""
        self._shortcuts = None        # set by app.py once D-Bus is up
        self._permission_warned = False
        self._status = "Starting…"
        self._active_preset = -1
        self._speakers: List[Dict[str, Any]] = []

        self.controller = Controller(settings, on_event=self._from_worker)
        self._event.connect(self._on_event, Qt.QueuedConnection)

        # "system" mode follows the desktop. Qt reports this and signals when
        # it changes, so a Plasma night-colour switch is picked up live.
        hints = QGuiApplication.styleHints()
        if hints is not None:
            try:
                hints.colorSchemeChanged.connect(
                    lambda *_: self.appearanceChanged.emit())
            except AttributeError:      # older Qt without the signal
                logger.debug("colorSchemeChanged unavailable")

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
            pass        # the controller clears the selection; see above
        elif name in ("devices_changed", "monitor_status"):
            self._refresh_speakers()
        elif name == "volume_set":
            self._volume_db = payload
            self.volumeChanged.emit()
        elif name == "permission_denied":
            if not self._permission_warned:
                self._permission_warned = True    # once per run, not per retry
                self.permissionProblem.emit(str(payload or ""))
        elif name == "identifying":
            self._identifying = "" if payload is None else str(payload)
            self.speakersChanged.emit()
        elif name == "sleep_changed":
            self._asleep = bool(payload)
            self._set_status("Speakers asleep" if self._asleep else "Connected")
            self.asleepChanged.emit()
            self._refresh_speakers()
        elif name == "mute_changed":
            self._muted = bool(payload)
            self.mutedChanged.emit()
        elif name == "selection_changed":
            # payload: None | ("preset", i) | ("mute",)
            index = payload[1] if (payload and payload[0] == "preset") else -1
            if index != self._active_preset:
                self._active_preset = index
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
            self.connectedChanged.emit()   # adapterInfo names the count

    def _set_status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    # -- properties ------------------------------------------------------

    @Property(bool, notify=connectedChanged)
    def connected(self) -> bool:
        return self._connected

    @Property(str, notify=connectedChanged)
    def adapterInfo(self) -> str:
        """Which adapter, where. Checkable against lsusb and /dev/hidraw*."""
        session = self.controller._session
        if session is None or not self._connected:
            return ("GLM adapter not reachable\n\n"
                    "Expected USB 1781:0e39. If it is plugged in, the HID "
                    "node is probably root-only — see packaging/udev/.")

        a = session.adapter
        lines = ["Connected to the GLM adapter"]
        name = " ".join(x for x in (a.manufacturer, a.product) if x)
        if name:
            lines.append(name)
        if a.serial:
            lines.append(f"serial #{a.serial}")
        version = firmware_version(a.software)
        if version:
            lines.append(f"firmware {version}")
        where = ["USB 1781:0e39"]
        if a.usb_location:
            where.append(a.usb_location)
        lines.append("  ·  ".join(where))
        if a.hid_path:
            lines.append(a.hid_path)
        if a.mic_serial:
            lines.append(f"microphone #{a.mic_serial}")
        count = len(self._speakers)
        lines.append(f"{count} speaker{'' if count == 1 else 's'} on the network")
        return "\n".join(lines)

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

    @Property(bool, notify=asleepChanged)
    def asleep(self) -> bool:
        return self._asleep

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

    @Property(str, constant=True)
    def appName(self) -> str:
        return APP_TITLE

    @Property(str, constant=True)
    def appVersion(self) -> str:
        return __version__

    @Property(str, constant=True)
    def appHomepage(self) -> str:
        return APP_HOMEPAGE

    # -- appearance ------------------------------------------------------

    def _system_is_dark(self) -> bool:
        hints = QGuiApplication.styleHints()
        scheme = getattr(hints, "colorScheme", None)
        if scheme is None:
            return True
        try:
            return scheme() == Qt.ColorScheme.Dark
        except Exception:  # noqa: BLE001
            return True

    @Property("QVariantMap", notify=appearanceChanged)
    def palette(self):
        dark = resolve_mode(self._settings.theme_mode, self._system_is_dark())
        return build_palette(self._settings.theme_name, dark)

    @Property(float, notify=appearanceChanged)
    def fontScale(self) -> float:
        return TEXT_SIZES.get(self._settings.text_size, 1.0)

    @Property("QStringList", constant=True)
    def presetColours(self):
        """Fixed identity colours for the preset dots.

        Constant, and deliberately not part of the palette: these mark which
        preset is which and must not shift with the theme.
        """
        return list(PRESET_DOT_COLOURS)

    @Property("QStringList", constant=True)
    def themeNames(self):
        return list(THEME_NAMES)

    @Property("QStringList", constant=True)
    def textSizeNames(self):
        return list(TEXT_SIZE_NAMES)

    @Property("QStringList", constant=True)
    def modeNames(self):
        return list(MODES)

    @Property(str, notify=appearanceChanged)
    def themeMode(self) -> str:
        return self._settings.theme_mode

    @Property(str, notify=appearanceChanged)
    def themeName(self) -> str:
        return self._settings.theme_name

    @Property(str, notify=appearanceChanged)
    def textSize(self) -> str:
        return self._settings.text_size

    @Slot(str)
    def setThemeMode(self, mode: str) -> None:
        if mode in MODES:
            self._settings.theme_mode = mode
            self._settings.save()
            self.appearanceChanged.emit()

    @Slot(str)
    def setThemeName(self, name: str) -> None:
        if name in THEME_NAMES:
            self._settings.theme_name = name
            self._settings.save()
            self.appearanceChanged.emit()

    @Slot(str)
    def setTextSize(self, size: str) -> None:
        if size in TEXT_SIZES:
            self._settings.text_size = size
            self._settings.save()
            self.appearanceChanged.emit()

    # -- autostart -------------------------------------------------------

    @Property(bool, notify=settingsChanged)
    def autostartEnabled(self) -> bool:
        return autostart.is_enabled()

    @Slot(bool)
    def setAutostart(self, enabled: bool) -> None:
        autostart.set_enabled(enabled)
        self.settingsChanged.emit()

    # -- ceiling ---------------------------------------------------------

    @Property(float, notify=settingsChanged)
    def ceilingDb(self) -> float:
        return self._settings.max_volume_db

    @Slot()
    def captureCeiling(self) -> None:
        """Set the ceiling from the knob, never from a typed number.

        Same rule as presets: a limit nobody has heard is not a limit.
        """
        def go(session):
            knob = session.adapter.knob_db
            if knob is None:
                raise RuntimeError("knob position not known yet")
            return knob
        try:
            knob = self.controller.call("read_knob", go)
        except Exception as exc:  # noqa: BLE001
            self.errorRaised.emit(f"Could not read the knob: {exc}")
            return
        self._settings.capture_ceiling(knob)
        self._settings.save()
        self.controller.submit("apply_ceiling",
                               lambda s: setattr(s, "max_volume_db", knob))
        self.settingsChanged.emit()
        self.ceilingCaptured.emit(knob)

    # -- global shortcuts ------------------------------------------------

    @Property(bool, notify=shortcutsChanged)
    def kdeShortcutsEnabled(self) -> bool:
        return self._settings.kde_shortcuts

    @Property(bool, constant=True)
    def kdeShortcutsAvailable(self) -> bool:
        from .ipc import KdeShortcuts

        return KdeShortcuts.available()

    @Property("QVariantList", constant=True)
    def shortcutActions(self):
        from .ipc import ACTIONS

        return [{"id": method, "label": label} for method, label in ACTIONS]

    @Slot(bool)
    def setKdeShortcuts(self, enabled: bool) -> None:
        """Register or remove the KDE shortcut actions.

        Enabling also opens the shortcuts editor: registration deliberately
        binds no keys, so without that the actions would exist but appear to
        do nothing.
        """
        if self._shortcuts is None:
            self.errorRaised.emit("Global shortcuts are not available here")
            return

        try:
            ok = (self._shortcuts.register() if enabled
                  else self._shortcuts.unregister())
        except Exception as exc:  # noqa: BLE001
            logger.exception("global shortcut toggle failed")
            self.errorRaised.emit(f"Global shortcuts: {exc}")
            self.shortcutsChanged.emit()
            return
        if not ok:
            self.errorRaised.emit(
                "KDE's shortcut service did not respond")
            self.shortcutsChanged.emit()
            return

        self._settings.kde_shortcuts = bool(enabled)
        self._settings.save()
        self.shortcutsChanged.emit()
        if enabled:
            self._shortcuts.open_editor()

    @Slot()
    def openShortcutEditor(self) -> None:
        if self._shortcuts is not None:
            self._shortcuts.open_editor()

    @Property(str, constant=True)
    def udevFixCommand(self) -> str:
        from ..core.hidinfo import udev_fix_command

        return udev_fix_command()

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

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
    def openHomepage(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(APP_HOMEPAGE))

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

    @Property(str, notify=speakersChanged)
    def identifyingSerial(self) -> str:
        return self._identifying or ""

    @Slot(str)
    def identifySpeaker(self, serial: str) -> None:
        self.controller.identify_speaker(int(serial))

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
    def repair(self) -> None:
        """Return every monitor to normal operation.

        The escape hatch for a speaker left in the volume-frozen state --
        which Identify deliberately uses, so a failed restore is a real
        possibility rather than a hypothetical one.
        """
        def go(session):
            session.clear_all_state()
            return len(session.monitors)

        self.controller.submit("repair", go)
        self.repairRequested.emit()

    @Slot(float)
    def setMaxVolume(self, db: float) -> None:
        self._settings.max_volume_db = db
        self._settings.save()
        session = self.controller._session
        if session is not None:
            self.controller.submit(
                "apply_ceiling",
                lambda s: setattr(s, "max_volume_db", db))
