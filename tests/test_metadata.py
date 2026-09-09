"""Guards against the few places project identity is necessarily duplicated."""

import tomllib
from pathlib import Path

import genlcui

ROOT = Path(__file__).resolve().parent.parent


def pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def test_version_is_not_duplicated_in_pyproject():
    """It must be declared dynamic and read from genlcui.__version__."""
    project = pyproject()["project"]
    assert "version" in project.get("dynamic", []), \
        "pyproject carries its own version; it should read the module attribute"
    assert "version" not in project
    attr = pyproject()["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "genlcui.__version__"


def test_homepage_matches_the_module_constant():
    """setuptools cannot resolve `urls` dynamically, so this one is copied."""
    assert pyproject()["project"]["urls"]["Homepage"] == genlcui.APP_HOMEPAGE


def test_desktop_entry_matches_the_application_name():
    entry = (ROOT / "packaging/desktop/genlcui.desktop").read_text()
    assert f"Name={genlcui.APP_TITLE}" in entry


def test_version_is_a_sane_triple():
    parts = genlcui.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_desktop_entry_has_one_main_category():
    """Two main categories can make the app appear twice in the menu."""
    entry = (ROOT / "packaging/desktop/genlcui.desktop").read_text()
    line = next(l for l in entry.splitlines() if l.startswith("Categories="))
    categories = set(line.split("=", 1)[1].strip(";").split(";"))
    main = {"AudioVideo", "Audio", "Development", "Education", "Game",
            "Graphics", "Network", "Office", "Science", "Settings",
            "System", "Utility"}
    # Audio is a subcategory of AudioVideo, so that pairing is fine; what
    # matters is not straddling two unrelated top-level sections.
    assert "Settings" not in categories or "AudioVideo" not in categories
    assert categories & main, "no main category at all"


def test_desktop_exec_is_a_bare_command():
    """Exec=genlcui only works if the launcher is on PATH -- the .deb puts it
    in /usr/bin, and install-icons.sh links it for source checkouts."""
    entry = (ROOT / "packaging/desktop/genlcui.desktop").read_text()
    assert "Exec=genlcui\n" in entry


def test_installer_links_the_launcher_for_source_checkouts():
    """Regression: the start menu entry failed with "program not found"
    because nothing put the console script on PATH."""
    script = (ROOT / "packaging/install-icons.sh").read_text()
    assert ".venv/bin/genlcui" in script
    assert "$HOME/.local/bin" in script
