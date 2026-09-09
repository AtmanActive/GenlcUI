#!/usr/bin/env bash
# A relocatable tar.gz: unpack anywhere, run ./genlcui, no root needed.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(cat "$here/build/VERSION")"
stage="$here/build/tar/genlcui-$version"

rm -rf "$here/build/tar"; mkdir -p "$stage"
cp -a "$here/build/bundle/." "$stage/"
cp -a "$here/LICENSE" "$here/README.md" "$stage/"

# Per-user installer, so the tarball is not just a pile of files.
cat > "$stage/install.sh" <<'INSTALL'
#!/usr/bin/env sh
# Install for the current user into ~/.local. No root required.
set -eu
here="$(cd "$(dirname "$0")" && pwd)"
prefix="${XDG_DATA_HOME:-$HOME/.local/share}"
bin="$HOME/.local/bin"

mkdir -p "$prefix/genlcui" "$bin" "$prefix/applications"
cp -a "$here/." "$prefix/genlcui/"
ln -sf "$prefix/genlcui/genlcui" "$bin/genlcui"
cp -a "$here/share/icons/hicolor" "$prefix/icons/" 2>/dev/null || \
    cp -a "$here/share/icons/hicolor/." "$prefix/icons/hicolor/"
cp -a "$here/share/genlcui.desktop" "$prefix/applications/"
command -v update-desktop-database >/dev/null && \
    update-desktop-database "$prefix/applications" 2>/dev/null || true

echo "Installed to $prefix/genlcui"
echo "Run: genlcui   (ensure $bin is on your PATH)"
echo
echo "The GLM adapter needs a udev rule to be usable without root."
echo "GenlcUI will show you the exact command if it cannot open the device."
INSTALL
chmod +x "$stage/install.sh"

out="$here/dist/genlcui-$version-linux-x86_64.tar.gz"
mkdir -p "$here/dist"
tar -C "$here/build/tar" -czf "$out" "genlcui-$version"
echo "$(du -h "$out" | cut -f1)  $out"
