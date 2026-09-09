"""Adapter location diagnostics."""

from genlcui.core import hidinfo


def test_firmware_version_is_extracted():
    assert hidinfo.firmware_version(
        "c-0;model-GLM Adapter;ver-1.3.2.5053;hw-0.0.137;build-2022.11.10"
    ) == "1.3.2.5053"


def test_firmware_version_handles_missing_or_empty_input():
    assert hidinfo.firmware_version("") is None
    assert hidinfo.firmware_version("c-0;model-GLM Adapter") is None
    assert hidinfo.firmware_version("ver-") is None


def test_usb_location_of_nothing_is_none():
    assert hidinfo.usb_location("") is None
    assert hidinfo.usb_location("/dev/does-not-exist") is None


def test_usb_location_reads_busnum_and_devnum(tmp_path, monkeypatch):
    """Walks up from the hidraw node to the USB device that owns it."""
    usb = tmp_path / "usb1" / "1-2"
    usb.mkdir(parents=True)
    (usb / "busnum").write_text("3\n")
    (usb / "devnum").write_text("5\n")
    node = usb / "1-2:1.0" / "0003:1781:0E39.000A"
    node.mkdir(parents=True)

    hidraw = tmp_path / "class" / "hidraw" / "hidraw5"
    hidraw.mkdir(parents=True)
    (hidraw / "device").symlink_to(node)
    monkeypatch.setattr(hidinfo, "SYS_HIDRAW", tmp_path / "class" / "hidraw")

    assert hidinfo.usb_location("/dev/hidraw5") == "bus 003 device 005"


def test_enumerate_never_raises_without_hardware(monkeypatch):
    """Diagnostics must not be able to stop us using the device."""
    import builtins
    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "hid":
            raise ImportError("no hid module")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    assert hidinfo.enumerate_adapter(0x1781, 0x0E39) == {}


# -- permission diagnosis ------------------------------------------------
#
# The first-run failure is "plugged in but root-only", which has an exact fix.
# Telling that apart from "not plugged in" is what makes the fix-it dialog
# honest rather than a guess.

def _fake_hidraw(tmp_path, monkeypatch, hid_id, name="hidraw5"):
    root = tmp_path / "class" / "hidraw"
    node = root / name
    node.mkdir(parents=True)
    (node / "device").mkdir()
    (node / "device" / "uevent").write_text(f"HID_ID={hid_id}\nHID_NAME=x\n")
    monkeypatch.setattr(hidinfo, "SYS_HIDRAW", root)
    return node


def test_find_hidraw_matches_zero_padded_ids(tmp_path, monkeypatch):
    """sysfs writes HID_ID=0003:00001781:00000E39 -- eight hex digits each."""
    _fake_hidraw(tmp_path, monkeypatch, "0003:00001781:00000E39")
    assert hidinfo.find_hidraw(0x1781, 0x0E39) == "/dev/hidraw5"


def test_find_hidraw_ignores_other_devices(tmp_path, monkeypatch):
    _fake_hidraw(tmp_path, monkeypatch, "0003:0000046D:0000C539")
    assert hidinfo.find_hidraw(0x1781, 0x0E39) is None


def test_find_hidraw_survives_a_malformed_uevent(tmp_path, monkeypatch):
    _fake_hidraw(tmp_path, monkeypatch, "not:hex:at-all")
    assert hidinfo.find_hidraw(0x1781, 0x0E39) is None


def test_diagnose_reports_missing_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(hidinfo, "SYS_HIDRAW", tmp_path / "empty")
    assert hidinfo.diagnose(0x1781, 0x0E39) == ("missing", None)


def test_diagnose_reports_permission_when_unreadable(tmp_path, monkeypatch):
    _fake_hidraw(tmp_path, monkeypatch, "0003:00001781:00000E39")
    monkeypatch.setattr(hidinfo.os, "access", lambda *_: False)
    state, path = hidinfo.diagnose(0x1781, 0x0E39)
    assert state == "permission" and path == "/dev/hidraw5"


def test_diagnose_reports_ok_when_accessible(tmp_path, monkeypatch):
    _fake_hidraw(tmp_path, monkeypatch, "0003:00001781:00000E39")
    monkeypatch.setattr(hidinfo.os, "access", lambda *_: True)
    assert hidinfo.diagnose(0x1781, 0x0E39)[0] == "ok"


# -- the fix-it command --------------------------------------------------

def test_fix_command_is_self_contained():
    """It must work from a .deb, an AppImage, a tarball or a checkout, none
    of which put the rules file in the same place -- so it writes the rule
    inline rather than copying one from disk."""
    command = hidinfo.udev_fix_command()
    assert "tee /etc/udev/rules.d/70-genelec-glm.rules" in command
    assert "1781" in command and "0e39" in command
    assert "udevadm control --reload-rules" in command
    assert "udevadm trigger" in command
    assert "packaging/" not in command      # no path into our source tree


def test_fix_command_grants_access_both_ways():
    """uaccess covers the logged-in user; the group covers the rest."""
    command = hidinfo.udev_fix_command()
    assert 'TAG+="uaccess"' in command
    assert 'GROUP="plugdev"' in command


def test_fix_command_covers_hidraw_and_usb():
    command = hidinfo.udev_fix_command()
    assert 'SUBSYSTEM=="hidraw"' in command
    assert 'SUBSYSTEM=="usb"' in command
