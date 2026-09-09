#!/usr/bin/env bash
# A single-file AppImage.
#
# Note the limitation this format cannot escape: an AppImage runs unprivileged
# and cannot install the udev rule, so a first run on a fresh machine will hit
# the permission dialog. That is expected -- the dialog exists precisely for
# this case and hands over the exact command.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(cat "$here/build/VERSION")"
appdir="$here/build/AppDir"
tool="${APPIMAGETOOL:-$(command -v appimagetool || true)}"

rm -rf "$appdir"
mkdir -p "$appdir/usr" "$appdir/usr/share/applications" \
         "$appdir/usr/share/icons"

cp -a "$here/build/bundle" "$appdir/usr/genlcui"
cp -a "$here/build/bundle/share/icons/hicolor" "$appdir/usr/share/icons/"
cp -a "$here/packaging/desktop/genlcui.desktop" \
      "$appdir/usr/share/applications/"
cp -a "$here/packaging/desktop/genlcui.desktop" "$appdir/genlcui.desktop"
cp -a "$here/gfx/icons/hicolor/256x256/apps/genlcui.png" "$appdir/genlcui.png"
mkdir -p "$appdir/usr/share/icons/hicolor/256x256/apps"

cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
here="$(dirname "$(readlink -f "$0")")"
export PYTHONDONTWRITEBYTECODE=1
# The bundled icon theme, so the tray state colours resolve by name even
# when nothing is installed into the user's theme.
export XDG_DATA_DIRS="$here/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
exec "$here/usr/genlcui/python/bin/python3" -m genlcui "$@"
APPRUN
chmod +x "$appdir/AppRun"

mkdir -p "$here/dist"
out="$here/dist/GenlcUI-$version-x86_64.AppImage"

if [ -z "$tool" ]; then
    echo "appimagetool not found; AppDir is ready at build/AppDir" >&2
    echo "Install it and re-run, or set APPIMAGETOOL=/path/to/appimagetool" >&2
    exit 2
fi

# stderr is left alone: when this fails in CI the reason must be visible.
ARCH=x86_64 "$tool" --no-appstream "$appdir" "$out" >/dev/null
echo "$(du -h "$out" | cut -f1)  $out"
