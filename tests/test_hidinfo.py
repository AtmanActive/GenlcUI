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
