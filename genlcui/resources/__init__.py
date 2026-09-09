"""Bundled assets."""

from __future__ import annotations

from pathlib import Path

RESOURCE_DIR = Path(__file__).parent
ICON_NAME = "genlcui"
ICON_FILE = RESOURCE_DIR / "genlcui.png"

#: Tray icon colour per state. The default (green) file carries no suffix.
#: Preset colours are positional: preset 1 is blue, 2 purple, 3 yellow,
#: 4 cyan, so the tray tells you which override is active at a glance.
PRESET_COLOURS = ("blue", "purple", "yellow", "cyan")

#: The same four identities as flat colours, for the indicator dots beside
#: each preset. Deliberately fixed: they are an identity, not decoration, so
#: they must read the same in every theme and mode. Nothing here derives from
#: the palette, and nothing in the palette may override them.
PRESET_DOT_COLOURS = ("#1e6bff", "#9b30ff", "#ffd000", "#00d0e0")
STATE_ASLEEP = "black"
STATE_MUTED = "red"


def icon_file(colour=None) -> Path:
    """Path to a colour variant, or the default icon when colour is None."""
    if not colour:
        return ICON_FILE
    candidate = RESOURCE_DIR / f"{ICON_NAME}-{colour}.png"
    return candidate if candidate.exists() else ICON_FILE


def state_colour(*, asleep: bool = False, muted: bool = False,
                 preset: int = -1):
    """Which colour represents this state, or None for the default.

    Precedence matters: asleep outranks everything, because a muted-and-
    asleep system is asleep first. Presets and mute are mutually exclusive
    upstream, so their order here is belt and braces.
    """
    if asleep:
        return STATE_ASLEEP
    if muted:
        return STATE_MUTED
    if 0 <= preset < len(PRESET_COLOURS):
        return PRESET_COLOURS[preset]
    return None


def icon_theme_name(colour=None) -> str:
    return ICON_NAME if not colour else f"{ICON_NAME}-{colour}"


def state_icon(colour=None):
    """A QIcon for one state, cached so tray updates cost nothing.

    Prefers the installed theme icon. KDE's tray uses StatusNotifierItem,
    which passes a themed icon by *name* and lets the shell load it; a QIcon
    built from a bare file has to travel as pixmap data instead, which some
    shells will not refresh on change. Installing the variants into hicolor
    (see packaging/install-icons.sh) is therefore what makes the tray colour
    actually update on Plasma.
    """
    from PySide6.QtGui import QIcon

    key = colour or ""
    icon = _ICON_CACHE.get(key)
    if icon is None:
        icon = QIcon.fromTheme(icon_theme_name(colour))
        if icon.isNull():
            icon = QIcon(str(icon_file(colour)))
        _ICON_CACHE[key] = icon
    return icon


_ICON_CACHE = {}


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
