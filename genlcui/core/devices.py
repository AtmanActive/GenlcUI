"""Device identity and state.

Serial numbers are identity; addresses are ephemeral. An address is a lease
handed out by RACE that expires after ~2-3s of bus silence, and re-discovery
may assign different addresses to the same physical speakers. Anything the
user sees -- ordering, names, per-speaker settings -- must therefore key off
`serial`, never `address`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Monitor:
    """One SAM monitor or subwoofer."""

    serial: int
    address: int
    model: str = ""
    barcode: str = ""
    software: str = ""

    # Live status
    temperature_c: Optional[int] = None
    tags: Dict[int, int] = field(default_factory=dict)
    online: bool = True

    # Mute is a group-level concept here: master volume is a broadcast, and
    # there is no verified per-monitor mute command. See commands.py.

    @property
    def key(self) -> str:
        """Stable identity for settings and UI ordering."""
        return f"#{self.serial}"

    @property
    def is_subwoofer(self) -> bool:
        # Genelec subwoofer model numbers are 73xx.
        return self.model.upper().startswith("73")

    @property
    def display_name(self) -> str:
        return self.model or f"SAM #{self.serial}"

    def __str__(self) -> str:
        return f"[{self.address}] {self.display_name} #{self.serial}"


@dataclass
class Adapter:
    """The GLM USB adapter itself (always address 1)."""

    serial: Optional[int] = None
    software: str = ""
    barcode: str = ""
    mic_serial: str = ""

    # Where it is, for diagnostics
    manufacturer: str = ""
    product: str = ""
    hid_path: str = ""
    usb_location: str = ""

    # Live status
    knob_db: Optional[float] = None
    mic_raw: Optional[int] = None

    @property
    def has_microphone(self) -> bool:
        return bool(self.mic_serial)
