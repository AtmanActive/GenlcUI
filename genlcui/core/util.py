"""Small conversions shared by the core and the UI."""

from __future__ import annotations

import math
from typing import Optional

# The microphone reference. genlc uses 20 uPa with a FIXME noting that GLM
# sets the reference at 70; we have no GLM5 reading to calibrate against yet,
# so this stays a documented approximation rather than a claim.
MIC_REFERENCE = 20.0


def mic_raw_to_dbspl(raw: Optional[int]) -> float:
    """Convert the adapter's linear mic reading to approximate dB SPL.

    Z-weighted, per the GLM manual. Absolute accuracy is unverified -- treat
    it as a relative level indicator until calibrated against GLM5.
    """
    if not raw or raw <= 0:
        return 0.0
    return 20 * math.log10(float(raw) / MIC_REFERENCE)


def db_to_fraction(db: float, floor: float = -80.0, ceiling: float = 0.0) -> float:
    """Map a dBFS value onto 0..1 for meters and bars."""
    if db <= floor:
        return 0.0
    if db >= ceiling:
        return 1.0
    return (db - floor) / (ceiling - floor)
