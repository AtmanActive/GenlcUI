#!/usr/bin/env bash
# Install the application icon into the user's hicolor theme, plus the
# desktop entry. Without an installed .desktop matching the app id, Wayland
# portals log "App info not found for 'genlcui'" and the taskbar shows no icon.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
theme="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

# Scaling uses Qt, so run under an interpreter that actually has PySide6 --
# the project venv if there is one, otherwise whatever PYTHON points at.
py="${PYTHON:-}"
if [ -z "$py" ] && [ -x "$here/.venv/bin/python" ]; then
    py="$here/.venv/bin/python"
fi
[ -z "$py" ] && py="python3"
if ! "$py" -c "import PySide6" 2>/dev/null; then
    echo "error: $py cannot import PySide6." >&2
    echo "Set PYTHON=/path/to/python and re-run." >&2
    exit 1
fi

"$py" - "$here/genlcui/resources" "$theme" <<'PY'
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

# Every state variant, not just the default: KDE's tray passes a themed icon
# by name, so an uninstalled variant simply will not appear when the state
# changes.
resources, theme = Path(sys.argv[1]), Path(sys.argv[2])
for source in sorted(resources.glob("genlcui*.png")):
    image = QImage(str(source))
    if image.isNull():
        print(f"  skipped unreadable {source.name}")
        continue
    for size in (16, 22, 24, 32, 48, 64, 128, 256):
        d = theme / f"{size}x{size}" / "apps"
        d.mkdir(parents=True, exist_ok=True)
        image.scaled(size, size, Qt.KeepAspectRatio,
                     Qt.SmoothTransformation).save(str(d / source.name))
    print(f"  installed {source.stem}")
PY

mkdir -p "$apps"
install -m 0644 "$here/packaging/desktop/genlcui.desktop" "$apps/"
command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -f -t "$theme" || true
command -v update-desktop-database >/dev/null && \
    update-desktop-database "$apps" || true
echo "Installed icons into $theme and desktop entry into $apps"
