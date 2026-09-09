#!/usr/bin/env bash
# A .deb wrapping the bundle at /opt/genlcui.
#
# Bundled Qt, so the only runtime dependency is libhidapi. The udev rule goes
# in with the package, which is the one setup step users would otherwise have
# to do by hand.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(cat "$here/build/VERSION")"
arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
root="$here/build/deb"

rm -rf "$root"
mkdir -p "$root/DEBIAN" "$root/opt/genlcui" "$root/usr/bin" \
         "$root/usr/share/applications" "$root/usr/share/icons" \
         "$root/lib/udev/rules.d" "$root/usr/share/doc/genlcui"

cp -a "$here/build/bundle/." "$root/opt/genlcui/"
ln -sf /opt/genlcui/genlcui "$root/usr/bin/genlcui"
cp -a "$here/build/bundle/share/icons/hicolor" "$root/usr/share/icons/"
cp -a "$here/packaging/desktop/genlcui.desktop" "$root/usr/share/applications/"
cp -a "$here/packaging/udev/70-genelec-glm.rules" "$root/lib/udev/rules.d/"
cp -a "$here/LICENSE" "$root/usr/share/doc/genlcui/copyright"

installed_kb="$(du -sk "$root" | cut -f1)"

cat > "$root/DEBIAN/control" <<CONTROL
Package: genlcui
Version: $version
Section: sound
Priority: optional
Architecture: $arch
Depends: libhidapi-hidraw0 | libhidapi-libusb0, libc6
Recommends: libxkbcommon0, libegl1, libfontconfig1
Installed-Size: $installed_kb
Maintainer: AtmanActive <noreply@users.noreply.github.com>
Homepage: https://github.com/AtmanActive/GenlcUI
Description: Desktop controller for Genelec SAM monitors
 GenlcUI controls Genelec SAM studio monitors through the GLM network
 adapter over USB. It provides level presets, mute, wake and sleep, live
 status and a system tray indicator, for Linux desktops where Genelec's
 own GLM software is not available.
 .
 It is a control surface, not a calibration tool: it never writes to
 speaker flash, so a calibration made with GLM stays intact.
 .
 Qt is bundled, so this package does not depend on a system Qt version.
CONTROL

cat > "$root/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    # Apply the udev rule now so the adapter is usable without a reboot.
    if command -v udevadm >/dev/null 2>&1; then
        udevadm control --reload-rules >/dev/null 2>&1 || true
        udevadm trigger --subsystem-match=hidraw >/dev/null 2>&1 || true
    fi
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
fi
POSTINST

cat > "$root/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && \
        update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && \
        gtk-update-icon-cache -qtf /usr/share/icons/hicolor || true
fi
POSTRM

chmod 0755 "$root/DEBIAN/postinst" "$root/DEBIAN/postrm"

mkdir -p "$here/dist"
out="$here/dist/genlcui_${version}_${arch}.deb"
dpkg-deb --build --root-owner-group -Zxz "$root" "$out" >/dev/null
echo "$(du -h "$out" | cut -f1)  $out"
