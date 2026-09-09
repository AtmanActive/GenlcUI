#!/usr/bin/env bash
# Assemble a self-contained runtime tree under build/bundle/.
#
# Contains its own CPython and a pruned PySide6, so it depends on nothing
# from the host but glibc and libhidapi. The .deb, the AppImage and the
# tarball are all thin wrappers around this same tree.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$here/build/bundle"
version="$(cd "$here" && python3 -c 'import re,pathlib;print(re.search(r"__version__ = \"([^\"]+)\"", pathlib.Path("genlcui/__init__.py").read_text()).group(1))')"

echo "Building GenlcUI $version bundle"
rm -rf "$out"
mkdir -p "$out"

# 1. A relocatable CPython. uv's builds are already relocatable.
python_src="$(uv python find 3.12 2>/dev/null || true)"
[ -z "$python_src" ] && { echo "error: no uv-managed Python 3.12" >&2; exit 1; }
python_root="$(dirname "$(dirname "$(readlink -f "$python_src")")")"
echo "  python: $python_root"
cp -a "$python_root" "$out/python"
chmod -R u+w "$out/python"

# The copy is ours to modify, so drop uv's PEP 668 marker.
find "$out/python/lib" -maxdepth 2 -name EXTERNALLY-MANAGED -delete

# 2. Dependencies into that interpreter's site-packages.
"$out/python/bin/python3" -m pip install --quiet --no-warn-script-location \
    --disable-pip-version-check "$here" >/dev/null

site="$(find "$out/python/lib" -maxdepth 2 -name site-packages -type d | head -1)"
echo "  site-packages: ${site#"$out"/}"

# 3. Prune Qt components the app never loads.
before="$(du -sm "$site/PySide6" | cut -f1)"
while IFS= read -r pattern; do
    case "$pattern" in ''|'#'*) continue ;; esac
    # shellcheck disable=SC2086
    rm -rf $site/PySide6/$pattern
done < "$here/packaging/prune-list.txt"
after="$(du -sm "$site/PySide6" | cut -f1)"
echo "  PySide6: ${before} MB -> ${after} MB"

# 4. Strip bytecode caches and test suites that ride along.
find "$out" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$out/python/lib/python3.12/test" "$out/python/lib/python3.12/idlelib" \
       "$out/python/lib/python3.12/tkinter" "$out/python/lib/python3.12/turtledemo" \
       "$site/pip" "$site/setuptools" "$site/pkg_resources" 2>/dev/null || true

# 5. Shared data: icons, desktop entry, udev rule.
mkdir -p "$out/share"
cp -a "$here/gfx/icons" "$out/share/icons"
cp -a "$here/packaging/desktop/genlcui.desktop" "$out/share/"
mkdir -p "$out/share/udev"
cp -a "$here/packaging/udev/70-genelec-glm.rules" "$out/share/udev/"

# 6. Launcher.
cat > "$out/genlcui" <<'LAUNCHER'
#!/bin/sh
# Resolve through symlinks so the launcher works from /usr/bin.
self="$0"
while [ -L "$self" ]; do self="$(readlink -f "$self")"; done
root="$(dirname "$self")"
export PYTHONDONTWRITEBYTECODE=1
exec "$root/python/bin/python3" -m genlcui "$@"
LAUNCHER
chmod +x "$out/genlcui"

echo "  total: $(du -sh "$out" | cut -f1)"
echo "$version" > "$here/build/VERSION"
echo "Bundle ready at build/bundle"
