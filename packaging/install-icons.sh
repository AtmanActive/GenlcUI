#!/usr/bin/env bash
# Install the application icon into the user's hicolor theme, plus the
# desktop entry. Without an installed .desktop matching the app id, Wayland
# portals log "App info not found for 'genlcui'" and the taskbar shows no icon.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$here/genlcui/resources/genlcui.png"
theme="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

python3 - "$src" "$theme" <<'PY'
import sys, os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

src, theme = QImage(sys.argv[1]), Path(sys.argv[2])
for size in (16, 22, 24, 32, 48, 64, 128, 256):
    d = theme / f"{size}x{size}" / "apps"
    d.mkdir(parents=True, exist_ok=True)
    src.scaled(size, size, Qt.KeepAspectRatio,
               Qt.SmoothTransformation).save(str(d / "genlcui.png"))
PY

mkdir -p "$apps"
install -m 0644 "$here/packaging/desktop/genlcui.desktop" "$apps/"
command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -f -t "$theme" || true
command -v update-desktop-database >/dev/null && \
    update-desktop-database "$apps" || true
echo "Installed icons into $theme and desktop entry into $apps"
