"""Tray icon state mapping.

Pure path/colour logic, so it runs without a display.
"""

import pytest

from genlcui.resources import (
    ICON_FILE, PRESET_COLOURS, STATE_ASLEEP, STATE_MUTED, icon_file,
    state_colour,
)


def test_default_state_has_no_colour():
    assert state_colour() is None
    assert icon_file(None) == ICON_FILE


def test_muted_is_red():
    assert state_colour(muted=True) == "red" == STATE_MUTED


def test_asleep_is_black():
    assert state_colour(asleep=True) == "black" == STATE_ASLEEP


def test_presets_are_colour_coded_in_order():
    """1 blue, 2 purple, 3 yellow, 4 cyan."""
    assert PRESET_COLOURS == ("blue", "purple", "yellow", "cyan")
    for index, colour in enumerate(PRESET_COLOURS):
        assert state_colour(preset=index) == colour


def test_asleep_outranks_mute_and_presets():
    assert state_colour(asleep=True, muted=True, preset=2) == "black"


def test_mute_outranks_a_preset():
    assert state_colour(muted=True, preset=1) == "red"


def test_no_preset_selected_is_the_default():
    assert state_colour(preset=-1) is None


def test_out_of_range_preset_falls_back_rather_than_raising():
    assert state_colour(preset=99) is None


@pytest.mark.parametrize("colour", list(PRESET_COLOURS) + ["red", "black"])
def test_every_state_ships_an_icon(colour):
    path = icon_file(colour)
    assert path.exists(), f"missing icon for {colour}"
    assert path != ICON_FILE, f"{colour} silently fell back to the default"


def test_unknown_colour_falls_back_to_the_default_icon():
    assert icon_file("chartreuse") == ICON_FILE


# -- preset indicator dots -----------------------------------------------

def test_there_is_a_dot_colour_per_preset():
    from genlcui.resources import PRESET_DOT_COLOURS
    assert len(PRESET_DOT_COLOURS) == len(PRESET_COLOURS) == 4


def test_dot_colours_are_valid_and_distinct():
    from genlcui.resources import PRESET_DOT_COLOURS
    assert len(set(PRESET_DOT_COLOURS)) == 4
    for value in PRESET_DOT_COLOURS:
        assert value.startswith("#") and len(value) == 7
        int(value[1:], 16)


def test_dot_colours_match_the_named_identities():
    """Blue, purple, yellow, cyan -- in that order, matching the tray icons."""
    from genlcui.resources import PRESET_DOT_COLOURS as dots

    def rgb(v):
        return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))

    b, p, y, c = (rgb(v) for v in dots)
    assert b[2] > b[0] and b[2] > b[1]            # blue: blue dominant
    assert p[0] > p[1] and p[2] > p[1]            # purple: red+blue over green
    assert y[0] > 200 and y[1] > 150 and y[2] < 100   # yellow: red+green
    assert c[1] > 150 and c[2] > 150 and c[0] < 100   # cyan: green+blue


def test_dot_colours_do_not_depend_on_the_theme():
    """They are an identity, not decoration; a themed dot would stop telling
    you which preset you are looking at."""
    from genlcui.ui.theming import THEME_NAMES, build_palette
    from genlcui.resources import PRESET_DOT_COLOURS

    for theme in THEME_NAMES:
        for dark in (True, False):
            palette = build_palette(theme, dark)
            assert not set(PRESET_DOT_COLOURS) & set(palette.values())
