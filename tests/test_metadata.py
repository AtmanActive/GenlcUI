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
