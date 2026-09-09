"""Palette and text-size tests.

Colours are derived in Python precisely so this can run without a display.
A theme that renders unreadable text is a real bug.
"""

import pytest

from genlcui.ui.theming import (
    MODES, TEXT_SIZE_NAMES, TEXT_SIZES, THEME_NAMES, build_palette, resolve_mode,
)

KEYS = {"bg", "surface", "line", "text", "dim", "accent", "warn", "ok",
        "danger", "isDark"}


def luminance(value: str) -> float:
    """Relative luminance, per WCAG."""
    value = value.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(value[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928
                        else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_there_are_ten_themes_and_seven_text_sizes():
    assert len(THEME_NAMES) == 10
    assert len(TEXT_SIZE_NAMES) == 7
    assert TEXT_SIZE_NAMES == ["nano", "micro", "small", "default",
                               "large", "kilo", "mega"]


def test_default_text_size_is_unity():
    assert TEXT_SIZES["default"] == 1.0


def test_text_sizes_increase_monotonically():
    values = [TEXT_SIZES[n] for n in TEXT_SIZE_NAMES]
    assert values == sorted(values)


@pytest.mark.parametrize("theme", THEME_NAMES)
@pytest.mark.parametrize("dark", [True, False])
def test_every_palette_is_complete(theme, dark):
    assert set(build_palette(theme, dark)) == KEYS


@pytest.mark.parametrize("theme", THEME_NAMES)
@pytest.mark.parametrize("dark", [True, False])
def test_body_text_is_readable_on_every_theme(theme, dark):
    """WCAG AA for body text is 4.5:1. This is a control surface glanced at
    mid-work, so falling below that is not cosmetic."""
    palette = build_palette(theme, dark)
    assert contrast(palette["text"], palette["bg"]) >= 4.5
    assert contrast(palette["text"], palette["surface"]) >= 4.5


@pytest.mark.parametrize("theme", THEME_NAMES)
@pytest.mark.parametrize("dark", [True, False])
def test_secondary_text_stays_legible(theme, dark):
    """Dim text is used for levels and status, so 3:1 is the floor."""
    palette = build_palette(theme, dark)
    assert contrast(palette["dim"], palette["bg"]) >= 3.0


@pytest.mark.parametrize("theme", THEME_NAMES)
@pytest.mark.parametrize("dark", [True, False])
def test_surface_is_distinguishable_from_the_background(theme, dark):
    palette = build_palette(theme, dark)
    assert palette["surface"] != palette["bg"]


@pytest.mark.parametrize("theme", THEME_NAMES)
def test_dark_and_light_actually_differ(theme):
    assert build_palette(theme, True) != build_palette(theme, False)
    assert luminance(build_palette(theme, True)["bg"]) < \
           luminance(build_palette(theme, False)["bg"])


@pytest.mark.parametrize("theme", THEME_NAMES)
@pytest.mark.parametrize("dark", [True, False])
def test_status_colours_do_not_follow_the_theme_hue(theme, dark):
    """An amber warning must not turn green because the user picked Forest."""
    reference = build_palette("Slate", dark)
    palette = build_palette(theme, dark)
    assert palette["warn"] == reference["warn"]
    assert palette["ok"] == reference["ok"]


def test_mode_resolution():
    assert resolve_mode("dark", False) is True
    assert resolve_mode("light", True) is False
    assert resolve_mode("system", True) is True
    assert resolve_mode("system", False) is False
    assert set(MODES) == {"system", "light", "dark"}


def test_unknown_theme_falls_back_rather_than_raising():
    assert build_palette("nonexistent", True) == build_palette("Slate", True)
