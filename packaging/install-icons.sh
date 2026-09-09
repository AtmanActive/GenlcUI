#!/usr/bin/env bash
# Install the icon theme and desktop entry for the current user.
#
# Pure file copies: every size is pre-generated and committed under
# gfx/icons/, so this needs no Python, no Qt and no image tooling. That
# matters because the same files are shipped by the .deb and the AppImage,
# where scaling at install time is not an option.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$here/gfx/icons/hicolor"
theme="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

if [ ! -d "$src" ]; then
    echo "error: $src is missing." >&2
    exit 1
fi

count=0
while IFS= read -r -d '' file; do
    rel="${file#"$src"/}"
    install -Dm 0644 "$file" "$theme/$rel"
    count=$((count + 1))
done < <(find "$src" -name '*.png' -print0)

install -Dm 0644 "$here/packaging/desktop/genlcui.desktop" "$apps/genlcui.desktop"

command -v gtk-update-icon-cache >/dev/null && \
    gtk-update-icon-cache -f -t "$theme" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null && \
    update-desktop-database "$apps" >/dev/null 2>&1 || true

echo "Installed $count icon files into $theme"
echo "Installed desktop entry into $apps"

# The desktop entry uses Exec=genlcui, which the .deb satisfies with
# /usr/bin/genlcui. From a source checkout nothing puts the console script on
# PATH, so the start menu entry would fail with "program not found" -- which
# is exactly what happened. Link it here.
bin="$HOME/.local/bin"
if command -v genlcui >/dev/null 2>&1; then
    echo "Launcher already on PATH: $(command -v genlcui)"
elif [ -x "$here/.venv/bin/genlcui" ]; then
    mkdir -p "$bin"
    ln -sf "$here/.venv/bin/genlcui" "$bin/genlcui"
    echo "Linked $bin/genlcui -> .venv/bin/genlcui"
    case ":$PATH:" in
        *":$bin:"*) ;;
        *) echo "NOTE: $bin is not on your PATH. The start menu will still"
           echo "      work, but 'genlcui' will not run from a shell until"
           echo "      you add it." ;;
    esac
else
    echo "WARNING: no 'genlcui' launcher found on PATH and no virtualenv at"
    echo "         $here/.venv -- the start menu entry will not work."
    echo "         Run 'uv pip install -e .' first, then re-run this script."
fi
