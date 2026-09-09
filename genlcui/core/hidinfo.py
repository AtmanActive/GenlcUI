"""Where the adapter actually is, for diagnostics.

Answers "which device am I talking to" in terms a user can check against
lsusb and ls -l /dev/hidraw*, which is the first thing worth knowing when
something does not work.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional

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


def firmware_version(software: str) -> Optional[str]:
    """Pull the version out of a GLM software string.

    Format: "c-0;model-GLM Adapter;ver-1.3.2.5053;hw-0.0.137;build-..."
    """
    for field in (software or "").split(";"):
        if field.startswith("ver-"):
            return field[4:].strip() or None
    return None
