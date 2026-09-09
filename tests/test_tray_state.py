"""Bridge state that drives the tray icon.

Exercises the real Bridge event path without a tray, so a failure here means
our state plumbing is wrong and a pass means the problem is the desktop shell.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication          # noqa: E402

from genlcui.core.settings import Settings          # noqa: E402
from genlcui.resources import state_colour          # noqa: E402
from genlcui.ui.bridge import Bridge                # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bridge(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return Bridge(Settings())


def colour_of(bridge):
    return state_colour(asleep=bridge.asleep, muted=bridge.muted,
                        preset=bridge.activePreset)


def test_resting_state_is_the_default_icon(bridge):
    assert colour_of(bridge) is None


def test_selecting_a_preset_changes_the_colour(bridge):
    bridge._on_event("selection_changed", ("preset", 0))
    assert bridge.activePreset == 0
    assert colour_of(bridge) == "blue"

    bridge._on_event("selection_changed", ("preset", 3))
    assert colour_of(bridge) == "cyan"


def test_muting_changes_the_colour(bridge):
    bridge._on_event("selection_changed", ("mute",))
    bridge._on_event("mute_changed", True)
    assert bridge.muted
    assert colour_of(bridge) == "red"


def test_sleeping_changes_the_colour(bridge):
    bridge._on_event("sleep_changed", True)
    assert bridge.asleep
    assert colour_of(bridge) == "black"


def test_clearing_a_selection_returns_to_the_default(bridge):
    bridge._on_event("selection_changed", ("preset", 1))
    assert colour_of(bridge) == "purple"
    bridge._on_event("selection_changed", None)
    assert bridge.activePreset == -1
    assert colour_of(bridge) is None


def test_state_changes_emit_the_signals_the_tray_listens_to(bridge):
    """The tray only re-syncs on these; a silent change leaves it stale."""
    seen = []
    bridge.activePresetChanged.connect(lambda: seen.append("preset"))
    bridge.mutedChanged.connect(lambda: seen.append("muted"))
    bridge.asleepChanged.connect(lambda: seen.append("asleep"))

    bridge._on_event("selection_changed", ("preset", 2))
    bridge._on_event("mute_changed", True)
    bridge._on_event("sleep_changed", True)

    assert "preset" in seen and "muted" in seen and "asleep" in seen


# -- the tray itself -----------------------------------------------------
#
# These exist because the icon-switching code was silently absent for two
# rounds: an edit failed to apply, and syntax checks plus 254 other tests all
# passed regardless. Nothing asserted the tray reacts to state at all.

class FakeIcon:
    """Stands in for QSystemTrayIcon, recording what it was told."""

    def __init__(self, *_args):
        self.icons = []
        self.tooltips = []
        self.menu = None
        self.shown = False

    def setIcon(self, icon): self.icons.append(icon)
    def setToolTip(self, text): self.tooltips.append(text)
    def setContextMenu(self, menu): self.menu = menu
    def show(self): self.shown = True

    class _Signal:
        def connect(self, *_): pass
    activated = _Signal()


@pytest.fixture
def tray(app, bridge, monkeypatch):
    from genlcui.ui import tray as tray_module
    monkeypatch.setattr(tray_module, "QSystemTrayIcon", FakeIcon)
    return tray_module.Tray(bridge, window=None)


def test_tray_changes_icon_when_a_preset_is_selected(tray, bridge):
    before = len(tray._icon.icons)
    bridge._on_event("selection_changed", ("preset", 0))
    assert len(tray._icon.icons) > before, "tray did not react to the preset"
    assert tray._colour == "blue"


def test_tray_changes_icon_on_mute(tray, bridge):
    bridge._on_event("selection_changed", ("mute",))
    bridge._on_event("mute_changed", True)
    assert tray._colour == "red"


def test_tray_changes_icon_on_sleep(tray, bridge):
    bridge._on_event("sleep_changed", True)
    assert tray._colour == "black"


def test_tray_returns_to_default_when_the_selection_clears(tray, bridge):
    bridge._on_event("selection_changed", ("preset", 2))
    assert tray._colour == "yellow"
    bridge._on_event("selection_changed", None)
    assert tray._colour == ""


def test_tray_walks_every_preset_colour(tray, bridge):
    for index, colour in enumerate(("blue", "purple", "yellow", "cyan")):
        bridge._on_event("selection_changed", ("preset", index))
        assert tray._colour == colour


def test_disconnected_tooltip_takes_priority(tray, bridge):
    """Knowing the adapter is unreachable matters more than the level."""
    bridge._on_event("selection_changed", ("preset", 0))
    assert any("not available" in text for text in tray._icon.tooltips)


def test_tray_does_not_reassign_an_unchanged_icon(tray, bridge):
    """The poll loop runs at 20 Hz; churning the tray would be wasteful."""
    bridge._on_event("selection_changed", ("preset", 1))
    count = len(tray._icon.icons)
    for _ in range(5):
        tray._sync()
    assert len(tray._icon.icons) == count


def test_tooltip_names_the_active_preset(tray, bridge):
    bridge._on_event("connected", None)      # otherwise it reports the adapter
    bridge._settings.capture_preset(0, -42.0)
    bridge._settings.presets[0].name = "Mixing"
    bridge._on_event("selection_changed", ("preset", 0))
    assert any("Mixing" in text and "-42.0" in text
               for text in tray._icon.tooltips)


def test_tooltip_reports_sleep(tray, bridge):
    bridge._on_event("connected", None)
    bridge._on_event("sleep_changed", True)
    assert any("asleep" in text for text in tray._icon.tooltips)


# -- adapter info tooltip ------------------------------------------------

def test_adapter_info_explains_a_missing_adapter(bridge):
    text = bridge.adapterInfo
    assert "not reachable" in text and "1781:0e39" in text
    assert "udev" in text          # points at the usual cause


def test_adapter_info_reports_where_the_device_is(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from genlcui.core.devices import Adapter
    from genlcui.core.settings import Settings
    from genlcui.ui.bridge import Bridge

    bridge = Bridge(Settings())

    class FakeSession:
        adapter = Adapter(
            serial="00000000011C", manufacturer="Genelec",
            product="Gnet Adapter", hid_path="/dev/hidraw5",
            usb_location="bus 003 device 005", mic_serial="208354",
            software="c-0;model-GLM Adapter;ver-1.3.2.5053;hw-0.0.137")
        monitors = {}

    bridge.controller._session = FakeSession()
    bridge._on_event("connected", None)

    text = bridge.adapterInfo
    for expected in ("Genelec Gnet Adapter", "00000000011C", "1.3.2.5053",
                     "bus 003 device 005", "/dev/hidraw5", "208354"):
        assert expected in text, f"{expected!r} missing from:\n{text}"
