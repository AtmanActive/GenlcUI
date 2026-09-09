"""System tray icon.

Not a convenience: the process must stay resident to hold the address leases
alive (see docs/PROTOCOL.md), so the tray is the honest way to show that it
is running rather than having it lurk invisibly.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_HOMEPAGE, APP_TITLE, __version__

from ..resources import app_icon, state_colour, state_icon

logger = logging.getLogger(__name__)


class Tray(QObject):
    def __init__(self, bridge, window, parent=None):
        super().__init__(parent)
        self._bridge = bridge
        self._window = window
        self._icon = QSystemTrayIcon(app_icon(), self)
        self._icon.setToolTip(APP_TITLE)
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
        bridge.asleepChanged.connect(self._sync)
        bridge.activePresetChanged.connect(self._sync)
        self._colour = ""
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
        # Mute stands alone: it belongs to the same exclusive group as the
        # presets above it, not to the power actions below.
        self._menu.addSeparator()

        wake = QAction("Wake speakers", self)
        wake.triggered.connect(self._bridge.wake)
        self._menu.addAction(wake)

        sleep = QAction("Sleep speakers", self)
        sleep.triggered.connect(self._bridge.sleep)
        self._menu.addAction(sleep)

        self._menu.addSeparator()
        about = QAction(f"{APP_TITLE} {__version__}…", self)
        about.setToolTip(APP_HOMEPAGE)
        about.triggered.connect(self._bridge.openHomepage)
        self._menu.addAction(about)

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
        bridge = self._bridge
        self._mute_action.setText("Unmute" if bridge.muted else "Mute")
        self._apply_icon(bridge)
        self._icon.setToolTip(self._tooltip(bridge))

    def _apply_icon(self, bridge) -> None:
        colour = state_colour(asleep=bridge.asleep, muted=bridge.muted,
                              preset=bridge.activePreset)
        if (colour or "") == self._colour:
            return
        self._colour = colour or ""
        icon = state_icon(colour)
        logger.info("tray icon -> %s (themed=%r, null=%s)",
                    colour or "default", icon.name(), icon.isNull())
        self._icon.setIcon(icon)

    @staticmethod
    def _tooltip(bridge) -> str:
        if not bridge.connected:
            return f"{APP_TITLE} — adapter not available"
        if bridge.asleep:
            return f"{APP_TITLE} — speakers asleep"
        if bridge.muted:
            return f"{APP_TITLE} — muted"
        presets = bridge.presets
        if 0 <= bridge.activePreset < len(presets):
            preset = presets[bridge.activePreset]
            return f"{APP_TITLE} — {preset['name']}  {preset['db']:.1f} dB"
        if bridge.knobKnown:
            return f"{APP_TITLE} — {bridge.knobDb:.1f} dB"
        return APP_TITLE

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
