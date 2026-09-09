#!/usr/bin/env bash
# Build every release artefact, verifying the bundle before packaging it.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$here/packaging/build-bundle.sh"
bash "$here/packaging/verify-bundle.sh"      # a pruned Qt must still run
bash "$here/packaging/build-tarball.sh"
bash "$here/packaging/build-deb.sh"
bash "$here/packaging/build-appimage.sh" || \
    echo "(AppImage skipped: appimagetool not installed)"

version="$(cat "$here/build/VERSION")"
echo
echo "Artefacts for $version:"
ls -lh "$here/dist" | tail -n +2 | awk '{printf "  %-46s %s\n", $9, $5}'
