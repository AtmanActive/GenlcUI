"""D-Bus control interface and KDE shortcut registration.

The registration itself needs a live KDE session, so these cover the parts
that do not: the action list, dispatch, and that nothing touches the desktop
unless asked.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication            # noqa: E402

from genlcui.core.settings import Settings            # noqa: E402
from genlcui.ui import ipc                            # noqa: E402
from genlcui.ui.bridge import Bridge                  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def service(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    bridge = Bridge(Settings())
    return ipc.ControlService(bridge), bridge


# -- the action list -----------------------------------------------------

def test_all_eleven_actions_are_offered():
    labels = [label for _, label in ipc.ACTIONS]
    assert labels == [
        "Bring to front", "Minimize to tray", "Mute", "Unmute", "Mute toggle",
        "Level preset Blue", "Level preset Purple", "Level preset Yellow",
        "Level preset Cyan", "Wake", "Sleep",
    ]


def test_every_action_has_a_method(service):
    control, _ = service
    for method, _ in ipc.ACTIONS:
        assert callable(getattr(control, method, None)), f"{method} missing"


def test_preset_actions_match_the_dot_colours():
    """The shortcut labels name colours, so they must be the same four, in
    the same order, as the preset indicators and tray icons."""
    from genlcui.resources import PRESET_COLOURS

    named = [label.replace("Level preset ", "").lower()
             for _, label in ipc.ACTIONS if label.startswith("Level preset")]
    assert named == list(PRESET_COLOURS)


# -- dispatch ------------------------------------------------------------

def test_invoke_runs_a_known_action(service):
    control, bridge = service
    seen = []
    bridge.showWindowRequested.connect(lambda: seen.append("shown"))
    assert control.invoke("BringToFront")
    assert seen == ["shown"]


def test_invoke_rejects_an_unknown_action(service):
    control, _ = service
    assert control.invoke("DropTheBass") is False


def test_invoke_refuses_methods_that_are_not_actions(service):
    """Dispatch is by name, so it must not reach arbitrary attributes."""
    control, _ = service
    assert control.invoke("invoke") is False
    assert control.invoke("deleteLater") is False


def test_minimize_and_front_are_separate_signals(service):
    control, bridge = service
    seen = []
    bridge.showWindowRequested.connect(lambda: seen.append("show"))
    bridge.hideWindowRequested.connect(lambda: seen.append("hide"))
    control.invoke("BringToFront")
    control.invoke("MinimizeToTray")
    assert seen == ["show", "hide"]


def test_preset_actions_target_the_right_index(service, monkeypatch):
    control, bridge = service
    called = []
    monkeypatch.setattr(bridge, "recallPreset", lambda i: called.append(i))
    for method in ("PresetBlue", "PresetPurple", "PresetYellow", "PresetCyan"):
        control.invoke(method)
    assert called == [0, 1, 2, 3]


# -- opt-in behaviour ----------------------------------------------------

def test_shortcuts_are_off_on_factory_settings():
    assert Settings().kde_shortcuts is False


def test_enabling_is_persisted_and_disabling_clears_it(service, monkeypatch):
    _, bridge = service
    calls = []

    class FakeShortcuts:
        def register(self): calls.append("register"); return True
        def unregister(self): calls.append("unregister"); return True
        def open_editor(self): calls.append("editor"); return True

    bridge._shortcuts = FakeShortcuts()

    bridge.setKdeShortcuts(True)
    assert bridge.kdeShortcutsEnabled
    assert calls == ["register", "editor"]      # editor opens on enable only

    bridge.setKdeShortcuts(False)
    assert not bridge.kdeShortcutsEnabled
    assert calls[-1] == "unregister"


def test_a_failed_registration_does_not_claim_success(service):
    _, bridge = service

    class Refuses:
        def register(self): return False
        def unregister(self): return False
        def open_editor(self): return False

    bridge._shortcuts = Refuses()
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge.setKdeShortcuts(True)
    assert not bridge.kdeShortcutsEnabled
    assert errors


def test_toggling_without_a_shortcut_service_reports_rather_than_crashes(service):
    _, bridge = service
    bridge._shortcuts = None
    errors = []
    bridge.errorRaised.connect(errors.append)
    bridge.setKdeShortcuts(True)
    assert errors and not bridge.kdeShortcutsEnabled


def test_action_ids_are_namespaced_to_this_app():
    ids = ipc.KdeShortcuts._action_id("Mute", "Mute")
    assert ids[0] == "genlcui" and ids[1] == "Mute"
    assert len(ids) == 4          # KGlobalAccel wants exactly four strings


# -- shortcut editor launch ----------------------------------------------

def test_editor_is_asked_for_our_component_first(monkeypatch):
    """Landing on the general list and making the user hunt for GenlcUI is a
    poor handoff when we know which component they want."""
    launched = []
    monkeypatch.setattr(ipc.shutil, "which", lambda p: "/usr/bin/" + p)
    monkeypatch.setattr(ipc.QProcess, "startDetached",
                        staticmethod(lambda p, a: launched.append((p, a)) or True))
    assert ipc.KdeShortcuts.open_editor()
    program, args = launched[0]
    assert args[0] == "kcm_keys"
    assert args[1:] == ["--args", "genlcui"]


def test_editor_falls_back_to_opening_unfiltered(monkeypatch):
    """The argument is a hint; a Plasma version that rejects it must still
    get the user to the shortcuts page."""
    launched = []

    def start(program, args):
        launched.append((program, args))
        return "--args" not in args          # refuse the targeted form

    monkeypatch.setattr(ipc.shutil, "which", lambda p: "/usr/bin/" + p)
    monkeypatch.setattr(ipc.QProcess, "startDetached", staticmethod(start))
    assert ipc.KdeShortcuts.open_editor()
    assert launched[-1][1] == ["kcm_keys"]


def test_editor_reports_failure_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(ipc.shutil, "which", lambda p: None)
    assert ipc.KdeShortcuts.open_editor() is False
