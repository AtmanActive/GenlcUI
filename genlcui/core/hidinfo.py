"""Where the adapter actually is, for diagnostics.

Answers "which device am I talking to" in terms a user can check against
lsusb and ls -l /dev/hidraw*, which is the first thing worth knowing when
something does not work.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SYS_HIDRAW = Path("/sys/class/hidraw")


def enumerate_adapter(vid: int, pid: int) -> Dict[str, str]:
    """Descriptive fields for the first matching HID device.

    Never raises: this is diagnostics, and failing to describe the device
    must not stop us from using it.
    """
    info: Dict[str, str] = {}
    try:
        import hid

        for entry in hid.enumerate(vid, pid):
            path = entry.get("path")
            info = {
                "path": path.decode() if isinstance(path, bytes) else str(path or ""),
                "manufacturer": entry.get("manufacturer_string") or "",
                "product": entry.get("product_string") or "",
                "serial": entry.get("serial_number") or "",
            }
            break
    except Exception:  # noqa: BLE001
        logger.debug("could not enumerate HID devices", exc_info=True)
    return info


def usb_location(hid_path: str) -> Optional[str]:
    """"bus 003 device 005" for a /dev/hidrawN path, or None.

    Walks up the sysfs tree from the hidraw node to the USB device that owns
    it, which is where busnum and devnum live.
    """
    if not hid_path:
        return None
    node = SYS_HIDRAW / os.path.basename(hid_path) / "device"
    try:
        current = node.resolve()
    except OSError:
        return None
    for _ in range(12):
        bus, dev = current / "busnum", current / "devnum"
        try:
            if bus.exists() and dev.exists():
                return (f"bus {int(bus.read_text()):03d} "
                        f"device {int(dev.read_text()):03d}")
        except (OSError, ValueError):
            return None
        if current.parent == current:
            break
        current = current.parent
    return None


def find_hidraw(vid: int, pid: int) -> Optional[str]:
    """The /dev/hidrawN node for a USB id, found without opening anything.

    Reads sysfs rather than using hidapi, so it works even when the node is
    unreadable -- which is exactly the case we need to detect.
    """
    try:
        entries = sorted(SYS_HIDRAW.iterdir())
    except OSError:
        return None
    for entry in entries:
        try:
            uevent = (entry / "device" / "uevent").read_text()
        except OSError:
            continue
        for line in uevent.splitlines():
            if not line.startswith("HID_ID="):
                continue
            # HID_ID=0003:00001781:00000E39 -- bus, vendor, product, each
            # zero padded to eight hex digits, so compare as numbers.
            parts = line.split("=", 1)[1].split(":")
            if len(parts) != 3:
                continue
            try:
                if int(parts[1], 16) == vid and int(parts[2], 16) == pid:
                    return f"/dev/{entry.name}"
            except ValueError:
                continue
    return None


def diagnose(vid: int, pid: int) -> Tuple[str, Optional[str]]:
    """Why can we not talk to the adapter? Returns (state, device path).

    States:
      "ok"          the node exists and we can read and write it
      "permission"  it is there, but not ours to open -- the udev rule is
                    missing, which is the usual first-run failure
      "missing"     no such device; not plugged in, or not a GLM adapter
    """
    path = find_hidraw(vid, pid)
    if path is None:
        return "missing", None
    if os.access(path, os.R_OK | os.W_OK):
        return "ok", path
    return "permission", path


#: Written verbatim into the fix-it command, so it works regardless of where
#: the application was installed from -- there may be no rules file on disk
#: to point at.
UDEV_RULE_PATH = "/etc/udev/rules.d/70-genelec-glm.rules"
UDEV_RULE_BODY = """\
# Genelec GLM network adapter (Gnet USB adapter)
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1781", ATTRS{idProduct}=="0e39", \
MODE="0660", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="1781", ATTRS{idProduct}=="0e39", \
MODE="0660", GROUP="plugdev", TAG+="uaccess"
"""


def udev_fix_command() -> str:
    """A self-contained shell snippet the user can paste to fix permissions.

    Deliberately writes the rule inline rather than copying a packaged file:
    the same text then works for a .deb, an AppImage, a tarball or a git
    checkout, none of which put the rule in the same place.
    """
    return (f"sudo tee {UDEV_RULE_PATH} > /dev/null <<'EOF'\n"
            f"{UDEV_RULE_BODY}"
            f"EOF\n"
            f"sudo udevadm control --reload-rules && sudo udevadm trigger")


def firmware_version(software: str) -> Optional[str]:
    """Pull the version out of a GLM software string.

    Format: "c-0;model-GLM Adapter;ver-1.3.2.5053;hw-0.0.137;build-..."
    """
    for field in (software or "").split(";"):
        if field.startswith("ver-"):
            return field[4:].strip() or None
    return None
