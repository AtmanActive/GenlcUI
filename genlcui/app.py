"""Application entry point."""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import APP_TITLE, __version__
from .core.settings import Settings
from .resources import app_icon
from .ui.bridge import Bridge
from .ui.tray import Tray

logger = logging.getLogger(__name__)


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if "--debug" in argv else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    # QApplication (not QGuiApplication) because QSystemTrayIcon is a widget.
    app = QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_TITLE)
    app.setDesktopFileName("genlcui")
    app.setWindowIcon(app_icon())

    # Closing the window normally hides to tray. But if there is no tray to
    # hide into, that leaves an invisible process the user cannot get back to
    # or stop except with Ctrl-C -- so fall back to quitting on close.
    has_tray = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not has_tray)
    if not has_tray:
        logger.warning("no system tray available; the window will quit the "
                       "application when closed")

    settings = Settings.load()
    bridge = Bridge(settings)

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "ui" / "Main.qml")))
    if not engine.rootObjects():
        print("Failed to load QML", file=sys.stderr)
        return 1

    window = engine.rootObjects()[0]
    tray = Tray(bridge, window) if has_tray else None

    if has_tray and settings.start_minimised and "--show" not in argv:
        window.hide()

    bridge.start()
    if settings.wake_on_start:
        bridge.wake()

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    app.aboutToQuit.connect(bridge.stop)

    status = app.exec()

    # Tear the QML engine down *synchronously*, while `bridge` is still
    # referenced. Otherwise Python collects the bridge first and every QML
    # binding re-evaluates against a null context property on the way out,
    # spraying "Cannot read property of null" across the terminal.
    # deleteLater() is no use here: the event loop that would run it has
    # already exited, so the deletion must come from the refcount dropping.
    del tray, window
    engine.clearComponentCache()
    del engine
    return status


if __name__ == "__main__":
    sys.exit(main())
