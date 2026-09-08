"""Bundled assets."""

from __future__ import annotations

from pathlib import Path

RESOURCE_DIR = Path(__file__).parent
ICON_NAME = "genlcui"
ICON_FILE = RESOURCE_DIR / "genlcui.png"


def app_icon():
    """The application icon, preferring the installed theme icon.

    Using the theme name first lets a desktop environment substitute its own
    sizes and any user override; the bundled file is the fallback for a
    run-from-source checkout where nothing has been installed yet.
    """
    from PySide6.QtGui import QIcon

    themed = QIcon.fromTheme(ICON_NAME)
    if not themed.isNull():
        return themed
    return QIcon(str(ICON_FILE))
