"""System tray icon.

Not a convenience: the process must stay resident to hold the address leases
alive (see docs/PROTOCOL.md), so the tray is the honest way to show that it
is running rather than having it lurk invisibly.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..resources import app_icon


class Tray(QObject):
    def __init__(self, bridge, window, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._window = window
        self._icon = QSystemTrayIcon(app_icon(), self)
        self._icon.setToolTip("Genelec")
        self._menu = QMenu()
        self._preset_actions = []
        self._build()
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

        bridge.presetsChanged.connect(self._rebuild_presets)
        bridge.mutedChanged.connect(self._sync)
        bridge.knobChanged.connect(self._sync)
        bridge.connectedChanged.connect(self._sync)
        self._sync()

    def _build(self) -> None:
        self._show_action = QAction("Show window", self)
        self._show_action.triggered.connect(self._show_window)
        self._menu.addAction(self._show_action)
        self._menu.addSeparator()

        self._preset_menu_anchor = self._menu.addSeparator()
        self._rebuild_presets()

        self._mute_action = QAction("Mute", self)
        self._mute_action.triggered.connect(self._bridge.toggleMute)
        self._menu.addAction(self._mute_action)

        wake = QAction("Wake speakers", self)
        wake.triggered.connect(self._bridge.wake)
        self._menu.addAction(wake)

        sleep = QAction("Sleep speakers", self)
        sleep.triggered.connect(self._bridge.sleep)
        self._menu.addAction(sleep)

        self._menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)

    @Slot()
    def _rebuild_presets(self) -> None:
        for action in self._preset_actions:
            self._menu.removeAction(action)
        self._preset_actions = []
        for preset in self._bridge.presets:
            if not preset["isSet"]:
                continue
            label = f"{preset['name']}   {preset['db']:.1f} dB"
            action = QAction(label, self)
            index = preset["index"]
            action.triggered.connect(
                lambda checked=False, i=index: self._bridge.recallPreset(i))
            self._menu.insertAction(self._preset_menu_anchor, action)
            self._preset_actions.append(action)

    @Slot()
    def _sync(self) -> None:
        self._mute_action.setText("Unmute" if self._bridge.muted else "Mute")
        if not self._bridge.connected:
            self._icon.setToolTip("Genelec — adapter not available")
        elif self._bridge.muted:
            self._icon.setToolTip("Genelec — muted")
        elif self._bridge.knobKnown:
            self._icon.setToolTip(f"Genelec — {self._bridge.knobDb:.1f} dB")
        else:
            self._icon.setToolTip("Genelec")

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._show_window()

    def _show_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.requestActivate()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        self._bridge.stop()
        QApplication.instance().quit()
