"""Autostart entry tests."""

from genlcui.core import autostart


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert not autostart.is_enabled()


def test_enable_then_disable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert autostart.set_enabled(True) is True
    assert autostart.is_enabled()
    assert autostart.set_enabled(False) is False
    assert not autostart.is_enabled()


def test_disabling_when_absent_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert autostart.set_enabled(False) is False


def test_entry_is_a_valid_desktop_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    autostart.set_enabled(True)
    text = autostart.entry_path().read_text()
    assert text.startswith("[Desktop Entry]")
    for key in ("Type=Application", "Name=GenlcUI", "Exec=", "Icon=genlcui"):
        assert key in text


def test_exec_command_is_runnable_as_written(tmp_path, monkeypatch):
    """A checkout run with `python -m genlcui` must autostart the same way,
    not point at a console script that was never installed."""
    monkeypatch.setattr(autostart.shutil, "which", lambda _: None)
    command = autostart.exec_command()
    assert command.endswith("-m genlcui")
    assert autostart.sys.executable in command


def test_exec_prefers_the_installed_script(monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda _: "/usr/bin/genlcui")
    assert autostart.exec_command() == "/usr/bin/genlcui"
