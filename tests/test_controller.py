"""Controller and settings tests, using a fake HID device."""

import json
import queue
import time

import pytest

from genlcui.core.controller import Controller
from genlcui.core.settings import PRESET_COUNT, Preset, Settings
from tests.test_session import FakeHid, frame


class LoopingHid(FakeHid):
    """Answers every request with a plausible adapter poll, forever."""

    def __init__(self, knob_db=-51.1):
        super().__init__()
        self.knob_db = knob_db

    def read(self, size, timeout=None):
        payload = bytes(15) + int(self.knob_db * 10).to_bytes(4, "big", signed=True)
        from tests.test_session import packetise
        return packetise(frame(payload))


def make_controller(tmp_path, knob_db=-51.1):
    settings = Settings()
    hid = LoopingHid(knob_db)
    events = []
    ctl = Controller(settings, on_event=lambda n, p: events.append((n, p)),
                     open_device=lambda: hid)
    return ctl, settings, hid, events


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# -- settings ------------------------------------------------------------

def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = Settings()
    s.capture_preset(0, -55.0)
    s.set_name(1093534, "Left")
    s.save()

    loaded = Settings.load()
    assert loaded.presets[0].db == -55.0
    assert loaded.name_for(1093534, "?") == "Left"
    assert loaded.max_volume_db == -30.0


def test_settings_defaults_when_file_is_corrupt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = Settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert Settings.load().max_volume_db == -30.0


def test_settings_tolerates_unknown_keys(tmp_path, monkeypatch):
    """A file written by a newer version must not crash an older one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = Settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"max_volume_db": -25.0, "future_thing": 42}))
    assert Settings.load().max_volume_db == -25.0


def test_missing_presets_are_backfilled(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = Settings.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"presets": [{"name": "One", "db": -60.0}]}))
    loaded = Settings.load()
    assert len(loaded.presets) == PRESET_COUNT
    assert loaded.presets[0].db == -60.0
    assert loaded.presets[1].db is None


def test_capture_preset_does_not_clamp_to_the_ceiling():
    """The level came from the knob, so the user already heard it."""
    s = Settings()
    s.capture_preset(0, -12.0)
    assert s.presets[0].db == -12.0
    assert s.exceeds_ceiling(-12.0)      # the UI asks; it does not silently clamp


def test_unset_preset_reports_itself_as_unset():
    assert not Preset(name="x").is_set
    assert Preset(name="x", db=-50.0).is_set


# -- controller ----------------------------------------------------------

def test_controller_connects_and_reports_the_knob(tmp_path):
    ctl, _, _, events = make_controller(tmp_path)
    ctl.start()
    try:
        assert wait_for(lambda: any(n == "connected" for n, _ in events))
        assert wait_for(lambda: ctl._session is not None
                        and ctl._session.adapter.knob_db == pytest.approx(-51.1))
    finally:
        ctl.stop()


def test_capture_preset_stores_the_live_knob_position(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    ctl, settings, _, _ = make_controller(tmp_path, knob_db=-44.4)
    ctl.start()
    try:
        assert wait_for(lambda: ctl._session is not None
                        and ctl._session.adapter.knob_db is not None)
        ctl.capture_preset(1)
        assert settings.presets[1].db == pytest.approx(-44.4)
    finally:
        ctl.stop()


def test_recalling_an_empty_preset_reports_an_error(tmp_path):
    ctl, _, _, events = make_controller(tmp_path)
    ctl.recall_preset(2)
    assert any(n == "error" for n, _ in events)


def test_commands_run_on_the_bus_thread(tmp_path):
    ctl, _, _, _ = make_controller(tmp_path)
    ctl.start()
    try:
        assert wait_for(lambda: ctl.connected)
        seen = ctl.call("whoami", lambda s: __import__("threading")
                        .current_thread().name)
        assert seen == "glm-bus"
    finally:
        ctl.stop()


def test_failed_command_surfaces_as_an_error_event(tmp_path):
    ctl, _, _, events = make_controller(tmp_path)
    ctl.start()
    try:
        assert wait_for(lambda: ctl.connected)
        ctl.submit("boom", lambda s: (_ for _ in ()).throw(RuntimeError("nope")))
        assert wait_for(lambda: any(n == "error" and "nope" in str(p)
                                    for n, p in events))
    finally:
        ctl.stop()


def test_call_propagates_the_exception_to_the_caller(tmp_path):
    ctl, _, _, _ = make_controller(tmp_path)
    ctl.start()
    try:
        assert wait_for(lambda: ctl.connected)
        with pytest.raises(RuntimeError):
            ctl.call("boom", lambda s: (_ for _ in ()).throw(RuntimeError("x")))
    finally:
        ctl.stop()


def test_device_that_will_not_open_retries_rather_than_dying(tmp_path):
    settings = Settings()
    events = []

    def refuse():
        raise OSError("Permission denied: /dev/hidraw5")

    ctl = Controller(settings, on_event=lambda n, p: events.append((n, p)),
                     open_device=refuse)
    ctl.start()
    try:
        assert wait_for(lambda: any(n == "disconnected" for n, _ in events))
        assert ctl._thread.is_alive()      # still trying
    finally:
        ctl.stop()


def test_stop_is_clean_and_idempotent(tmp_path):
    ctl, _, _, events = make_controller(tmp_path)
    ctl.start()
    assert wait_for(lambda: ctl.connected)
    ctl.stop()
    ctl.stop()
    assert any(n == "stopped" for n, _ in events)
    assert not ctl.connected


def test_repeated_errors_are_rate_limited(tmp_path):
    """A desynchronised bus fails on every poll; the UI must not be flooded."""
    ctl, _, _, events = make_controller(tmp_path)
    for i in range(20):
        ctl._emit("error", f"checksum 0x{i:04x} != computed 0x5de7")
    errors = [e for e in events if e[0] == "error"]
    assert len(errors) == 1, f"emitted {len(errors)} copies of one failure"


def test_distinct_errors_are_still_reported(tmp_path):
    ctl, _, _, events = make_controller(tmp_path)
    ctl._emit("error", "checksum mismatch: aa")
    ctl._emit("error", "truncated tag 0x06 at offset 0")
    ctl._emit("error", "unexpected response code 0x19")
    assert len([e for e in events if e[0] == "error"]) == 3


def test_error_key_ignores_the_bytes_that_vary():
    k = Controller._error_key
    assert k("checksum 0x63ea != computed 0x761d for payload b'\\x01\\t'") == \
           k("checksum 0x5def != computed 0x5de7 for payload b'\\x01\\x09'")
    assert k("truncated tag 0xe6 at offset 18 in b'24\\xde'") == \
           k("truncated tag 0xfd at offset 17 in b'99\\xaa'")
    assert k("unexpected response code 0x19") != k("checksum 0x1 != computed 0x2")


def test_discovery_runs_periodically(tmp_path):
    """A speaker switched on after launch generates no timeout, so nothing
    else would ever notice it."""
    from genlcui.core import commands as cid

    ctl, _, _, _ = make_controller(tmp_path)
    calls = []
    ctl.start()
    try:
        assert wait_for(lambda: ctl._session is not None)
        original = ctl._session.discover
        ctl._session.discover = lambda: (calls.append(1), original())[1]
        assert wait_for(lambda: len(calls) >= 2,
                        timeout=cid.DISCOVERY_INTERVAL_S * 3 + 2)
    finally:
        ctl.stop()
