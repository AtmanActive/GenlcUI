"""D-Bus control interface and opt-in KDE global shortcuts.

Two separate things, deliberately:

* The D-Bus service is always available. It exports nothing but method calls
  on the session bus, costs nothing, and makes the app scriptable.
* KDE global shortcut registration is **off by default and never automatic**.
  Registering actions with someone's desktop without being asked is rude, so
  it happens only when the user turns it on, and turning it off removes the
  registration again rather than leaving orphans behind.
"""

from __future__ import annotations

import logging
import shutil
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import SLOT, ClassInfo, QObject, QProcess, Slot

logger = logging.getLogger(__name__)

try:
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    DBUS_AVAILABLE = True
except ImportError:            # pragma: no cover - QtDBus is normally present
    QDBusConnection = QDBusInterface = None    # type: ignore
    DBUS_AVAILABLE = False

SERVICE_NAME = "org.genlcui.GenlcUI"
OBJECT_PATH = "/org/genlcui/GenlcUI"
INTERFACE = "org.genlcui.Control"

KDE_SERVICE = "org.kde.kglobalaccel"
KDE_PATH = "/kglobalaccel"
KDE_INTERFACE = "org.kde.KGlobalAccel"
KDE_COMPONENT_INTERFACE = "org.kde.kglobalaccel.Component"

COMPONENT_ID = "genlcui"
COMPONENT_NAME = "GenlcUI"

#: (method name, human label). The label is what appears in the KDE
#: shortcuts editor, so it reads as a sentence rather than an identifier.
ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("BringToFront", "Bring to front"),
    ("MinimizeToTray", "Minimize to tray"),
    ("Mute", "Mute"),
    ("Unmute", "Unmute"),
    ("ToggleMute", "Mute toggle"),
    ("PresetBlue", "Level preset Blue"),
    ("PresetPurple", "Level preset Purple"),
    ("PresetYellow", "Level preset Yellow"),
    ("PresetCyan", "Level preset Cyan"),
    ("Wake", "Wake"),
    ("Sleep", "Sleep"),
)


@ClassInfo({"D-Bus Interface": INTERFACE})
class ControlService(QObject):
    """The methods exposed on the session bus and to global shortcuts."""

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self._bridge = bridge

    # -- window ----------------------------------------------------------

    @Slot()
    def BringToFront(self) -> None:          # noqa: N802 - D-Bus naming
        self._bridge.showWindowRequested.emit()

    @Slot()
    def MinimizeToTray(self) -> None:        # noqa: N802
        self._bridge.hideWindowRequested.emit()

    # -- level -----------------------------------------------------------

    @Slot()
    def Mute(self) -> None:                  # noqa: N802
        self._bridge.controller.mute()

    @Slot()
    def Unmute(self) -> None:                # noqa: N802
        self._bridge.controller.unmute()

    @Slot()
    def ToggleMute(self) -> None:            # noqa: N802
        self._bridge.toggleMute()

    @Slot()
    def PresetBlue(self) -> None:            # noqa: N802
        self._bridge.recallPreset(0)

    @Slot()
    def PresetPurple(self) -> None:          # noqa: N802
        self._bridge.recallPreset(1)

    @Slot()
    def PresetYellow(self) -> None:          # noqa: N802
        self._bridge.recallPreset(2)

    @Slot()
    def PresetCyan(self) -> None:            # noqa: N802
        self._bridge.recallPreset(3)

    # -- power -----------------------------------------------------------

    @Slot()
    def Wake(self) -> None:                  # noqa: N802
        self._bridge.wake()

    @Slot()
    def Sleep(self) -> None:                 # noqa: N802
        self._bridge.sleep()

    # -- dispatch --------------------------------------------------------

    def invoke(self, action: str) -> bool:
        """Run one action by name. Used by the global shortcut handler."""
        handler: Optional[Callable[[], None]] = getattr(self, action, None)
        if handler is None or action not in dict(ACTIONS):
            logger.warning("unknown action %r", action)
            return False
        handler()
        return True


def publish(service: ControlService) -> bool:
    """Put the control interface on the session bus."""
    if not DBUS_AVAILABLE:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        logger.info("no session bus; D-Bus interface unavailable")
        return False
    if not bus.registerService(SERVICE_NAME):
        logger.info("could not take %s (already running?)", SERVICE_NAME)
        return False
    if not bus.registerObject(OBJECT_PATH, service,
                              QDBusConnection.ExportAllSlots):
        logger.warning("could not export %s", OBJECT_PATH)
        return False
    logger.info("D-Bus interface on %s %s", SERVICE_NAME, OBJECT_PATH)
    return True


class KdeShortcuts(QObject):
    """Registers actions with KDE's global shortcut daemon, on request only.

    Nothing here runs unless the user turns the setting on. Registration
    creates the actions with *no* keys bound: choosing the keys is the user's
    business, which is why enabling it also opens the shortcuts editor.
    """

    def __init__(self, service: ControlService, parent=None):
        super().__init__(parent)
        self._service = service
        self._connected = False

    # -- availability ----------------------------------------------------

    @staticmethod
    def available() -> bool:
        """True when KDE's global shortcut daemon is on this session bus."""
        if not DBUS_AVAILABLE:
            return False
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        iface = QDBusInterface("org.freedesktop.DBus", "/org/freedesktop/DBus",
                               "org.freedesktop.DBus", bus)
        reply = iface.call("NameHasOwner", KDE_SERVICE)
        return bool(reply.arguments() and reply.arguments()[0])

    def _daemon(self):
        return QDBusInterface(KDE_SERVICE, KDE_PATH, KDE_INTERFACE,
                              QDBusConnection.sessionBus())

    @staticmethod
    def _action_id(method: str, label: str) -> List[str]:
        # KGlobalAccel identifies an action by four strings:
        # component id, action id, component label, action label.
        return [COMPONENT_ID, method, COMPONENT_NAME, label]

    # -- registration ----------------------------------------------------

    def register(self) -> bool:
        if not self.available():
            return False
        daemon = self._daemon()
        for method, label in ACTIONS:
            action = self._action_id(method, label)
            daemon.call("doRegister", action)
            # Empty key list: registered, unbound, waiting for the user.
            daemon.call("setShortcut", action, [], 0)
        try:
            self._subscribe()
        except Exception:  # noqa: BLE001
            # The actions are registered and visible in the editor either
            # way; losing delivery is worth a warning, not a failed toggle.
            logger.warning("registered, but could not subscribe to KDE's "
                           "shortcut signal", exc_info=True)
        logger.info("registered %d global shortcuts with KDE", len(ACTIONS))
        return True

    def unregister(self) -> bool:
        if not self.available():
            return False
        daemon = self._daemon()
        for method, label in ACTIONS:
            daemon.call("unRegister", self._action_id(method, label))
        try:
            self._unsubscribe()
        except Exception:  # noqa: BLE001
            logger.debug("could not unsubscribe", exc_info=True)
        logger.info("removed KDE global shortcut registration")
        return True

    # -- delivery --------------------------------------------------------

    def _component_path(self) -> Optional[str]:
        reply = self._daemon().call("getComponent", COMPONENT_ID)
        args = reply.arguments()
        if not args:
            return None
        value = args[0]
        return getattr(value, "path", lambda: str(value))()

    # QDBusConnection.connect wants a receiver object plus a slot *signature*,
    # not a Python callable. The signature must match the registered
    # meta-method exactly, which is why _on_pressed carries an explicit
    # @Slot decoration.
    _PRESSED_SLOT = SLOT("_on_pressed(QString,QString,qlonglong)")

    def _subscribe(self) -> None:
        if self._connected:
            return
        path = self._component_path()
        if not path:
            logger.warning("no KGlobalAccel component path; shortcuts will "
                           "register but not fire")
            return
        ok = QDBusConnection.sessionBus().connect(
            KDE_SERVICE, path, KDE_COMPONENT_INTERFACE,
            "globalShortcutPressed", self, self._PRESSED_SLOT)
        self._connected = bool(ok)
        if not ok:
            logger.warning("could not subscribe to globalShortcutPressed")

    def _unsubscribe(self) -> None:
        if not self._connected:
            return
        path = self._component_path()
        if path:
            QDBusConnection.sessionBus().disconnect(
                KDE_SERVICE, path, KDE_COMPONENT_INTERFACE,
                "globalShortcutPressed", self, self._PRESSED_SLOT)
        self._connected = False

    @Slot(str, str, "qlonglong")
    def _on_pressed(self, component: str, action: str, _timestamp) -> None:
        if component != COMPONENT_ID:
            return
        logger.debug("global shortcut: %s", action)
        self._service.invoke(action)

    # -- editor ----------------------------------------------------------

    #: Wrappers that can host the shortcuts KCM, best first.
    EDITORS = ("systemsettings", "kcmshell6", "systemsettings5", "kcmshell5")
    KCM = "kcm_keys"

    @classmethod
    def open_editor(cls, component: Optional[str] = COMPONENT_ID) -> bool:
        """Open KDE's shortcuts editor, scrolled to our actions.

        Registration binds no keys, so the user has to assign them -- landing
        on the general list and making them hunt for "GenlcUI" is a poor
        handoff. Both systemsettings and kcmshell take `--args`, and the
        shortcuts KCM exposes a showComponent hook that consumes it.

        The argument is a hint, not a contract: if a Plasma version ignores
        it the editor still opens, just unfiltered. So a failure to launch
        *with* the argument falls back to launching without it rather than
        leaving the user with nothing.
        """
        attempts = []
        if component:
            attempts.append(["--args", component])
        attempts.append([])

        for extra in attempts:
            for program in cls.EDITORS:
                if not shutil.which(program):
                    continue
                if QProcess.startDetached(program, [cls.KCM] + extra):
                    logger.info("opened %s %s %s", program, cls.KCM,
                                " ".join(extra))
                    return True
        logger.info("no KDE shortcuts editor found")
        return False


def action_labels() -> Dict[str, str]:
    return dict(ACTIONS)
