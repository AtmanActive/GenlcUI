#!/usr/bin/env bash
# Prove the pruned bundle still works. A missing Qt library is a crash in a
# shipped binary, so this runs before any package is built from it.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bundle="$here/build/bundle"

[ -d "$bundle" ] || { echo "no bundle; run build-bundle.sh first" >&2; exit 1; }

QT_QPA_PLATFORM=offscreen "$bundle/python/bin/python3" - <<'PY'
import sys

# The app's own imports, through the bundled interpreter only.
sys.argv = ["genlcui-verify"]
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtDBus import QDBusConnection          # global shortcuts need this

import genlcui
from genlcui.core.settings import Settings
from genlcui.ui.bridge import Bridge
from genlcui.ui.tray import Tray
from genlcui.resources import PRESET_COLOURS, state_icon

app = QApplication(sys.argv)

warnings = []
engine = QQmlApplicationEngine()
engine.warnings.connect(lambda ws: warnings.extend(w.toString() for w in ws))
bridge = Bridge(Settings())
engine.rootContext().setContextProperty("bridge", bridge)

import pathlib
qml = pathlib.Path(genlcui.__file__).parent / "ui" / "Main.qml"
engine.load(QUrl.fromLocalFile(str(qml)))
assert engine.rootObjects(), f"QML failed to load: {warnings}"
assert not warnings, f"QML warnings: {warnings}"

# Every tray icon variant must be present, not silently falling back.
for colour in (None,) + PRESET_COLOURS + ("red", "black"):
    assert not state_icon(colour).isNull(), f"icon missing: {colour}"

print(f"  version      : {genlcui.__version__}")
print(f"  python       : {sys.version.split()[0]}")
print(f"  QML          : loaded, no warnings")
print(f"  icons        : all {len(PRESET_COLOURS) + 3} variants present")
print(f"  QtDBus       : available")
QTimer.singleShot(0, app.quit)
app.exec()
del bridge
engine.clearComponentCache()
del engine
PY

echo "  hid module   : $("$bundle/python/bin/python3" -c 'import hid; print("ok")')"
echo "Bundle verified"
