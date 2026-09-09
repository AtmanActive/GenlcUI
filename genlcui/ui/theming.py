"""Colour palettes and text scaling.

Palettes are derived in Python rather than QML so they can be unit tested --
a theme that renders unreadable text is a bug worth catching without a
display attached.

Each palette is built from one accent colour. The neutrals are shared, then
tinted very slightly toward the accent so a theme reads as a whole rather than
as a grey app with a coloured button.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

__all__ = [
    "THEME_NAMES", "TEXT_SIZES", "TEXT_SIZE_NAMES", "MODES",
    "build_palette", "resolve_mode",
]

MODES = ("system", "light", "dark")

# name -> accent
THEMES: Dict[str, str] = {
    "Slate":    "#5c9ded",
    "Ocean":    "#21a5b8",
    "Forest":   "#4caf6d",
    "Amber":    "#e0a458",
    "Crimson":  "#e05a5a",
    "Violet":   "#9b7ede",
    "Rose":     "#e07aa8",
    "Copper":   "#d2814e",
    "Lime":     "#a3c33f",
    "Graphite": "#9aa3b2",
}
THEME_NAMES: List[str] = list(THEMES)

# name -> multiplier applied to every font size
TEXT_SIZES: Dict[str, float] = {
    "nano": 0.70,
    "micro": 0.80,
    "small": 0.90,
    "default": 1.00,
    "large": 1.12,
    "kilo": 1.28,
    "mega": 1.50,
}
TEXT_SIZE_NAMES: List[str] = list(TEXT_SIZES)


def _to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore


def _to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def _mix(a: str, b: str, t: float) -> str:
    """Blend b into a by t (0..1)."""
    ra, rb = _to_rgb(a), _to_rgb(b)
    return _to_hex(ra[i] + (rb[i] - ra[i]) * t for i in range(3))


# Neutral bases, before tinting.
_DARK = {
    "bg": "#16181d", "surface": "#1e2128", "line": "#2c313a",
    "text": "#e6e9ef", "dim": "#8b93a3",
}
_LIGHT = {
    "bg": "#f4f6f9", "surface": "#ffffff", "line": "#dde2ea",
    "text": "#1b1f27", "dim": "#68707e",
}

# How far each neutral leans toward the accent. Backgrounds take the most so
# the tint is felt rather than seen; text takes almost none so contrast holds.
_TINT = {"bg": 0.06, "surface": 0.07, "line": 0.12, "text": 0.02, "dim": 0.10}


def build_palette(theme: str, dark: bool) -> Dict[str, str]:
    """Return the full colour set for a theme in one mode."""
    accent = THEMES.get(theme, THEMES["Slate"])
    base = _DARK if dark else _LIGHT
    palette = {key: _mix(value, accent, _TINT[key]) for key, value in base.items()}
    palette["accent"] = accent
    # Status colours stay recognisable across themes: an amber warning must
    # not turn green because the user picked the Forest theme.
    palette["warn"] = "#e0a458" if dark else "#b9721f"
    palette["ok"] = "#6cc17f" if dark else "#2f8f4e"
    palette["danger"] = "#e05a5a" if dark else "#c03a3a"
    palette["isDark"] = "1" if dark else "0"
    return palette


def resolve_mode(mode: str, system_is_dark: bool) -> bool:
    """True when the effective mode is dark."""
    if mode == "dark":
        return True
    if mode == "light":
        return False
    return system_is_dark
