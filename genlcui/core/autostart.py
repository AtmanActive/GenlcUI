"""XDG autostart entry management.

Writes a desktop file to $XDG_CONFIG_HOME/autostart. The Exec line points at
however this copy is actually runnable: the installed console script if there
is one, otherwise the interpreter and module that are running right now, so a
checkout started with `python -m genlcui` autostarts correctly too.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

from .. import APP_TITLE

logger = logging.getLogger(__name__)

ENTRY_NAME = "genlcui.desktop"


def autostart_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "autostart"


def entry_path() -> Path:
    return autostart_dir() / ENTRY_NAME


def exec_command() -> str:
    script = shutil.which("genlcui")
    if script:
        return script
    return f"{sys.executable} -m genlcui"


def is_enabled() -> bool:
    return entry_path().exists()


def set_enabled(enabled: bool) -> bool:
    """Create or remove the autostart entry. Returns the resulting state."""
    path = entry_path()
    if not enabled:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning("could not remove %s", path, exc_info=True)
            return is_enabled()
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_TITLE}\n"
            "Comment=Control Genelec SAM monitors through the GLM adapter\n"
            f"Exec={exec_command()}\n"
            "Icon=genlcui\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
    except OSError:
        logger.warning("could not write %s", path, exc_info=True)
    return is_enabled()
