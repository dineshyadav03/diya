"""pyproject.toml claims to pin every direct dependency to an exact, working version. This checks
that the claim is actually true of the environment the suite just ran in, not just plausible --
if a dependency is ever upgraded here without updating the pin, this fails loudly rather than
letting the file quietly go stale.
"""
import pathlib
import re
import tomllib
from importlib import metadata

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load():
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def test_pyproject_is_valid_toml_with_the_expected_shape():
    data = load()
    assert data["project"]["name"] == "diya"
    assert isinstance(data["project"]["dependencies"], list) and data["project"]["dependencies"]


def test_every_dependency_is_pinned_to_one_exact_version_not_a_range():
    for spec in load()["project"]["dependencies"]:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.!+-]+", spec), spec


def test_every_pinned_version_matches_what_is_actually_installed():
    """The whole point: these are the versions verified working today, not a wishlist."""
    for spec in load()["project"]["dependencies"]:
        name, version = spec.split("==")
        assert metadata.version(name) == version, (name, "installed", metadata.version(name), "pinned", version)


def test_optional_extras_are_pinned_too():
    for group in load()["project"]["optional-dependencies"].values():
        for spec in group:
            name, version = spec.split("==")
            assert metadata.version(name) == version, (name, metadata.version(name), version)


def test_no_two_dependencies_are_pinned_more_than_once():
    names = [spec.split("==")[0].lower() for spec in load()["project"]["dependencies"]]
    assert len(names) == len(set(names))


def test_the_degenerate_package_setup_that_lets_pip_install_dot_work_is_still_there():
    """This is a flat folder of scripts, not an importable package: pip needs to be told there is
    no package to discover, or it errors on the several top-level directories (frontend/, tests/,
    sample_notes/, docs/, archive/) that look like candidates. See the comment in pyproject.toml."""
    data = load()
    assert data["tool"]["setuptools"]["packages"] == []
    assert "setuptools" in data["build-system"]["requires"][0]


def test_requires_python_matches_what_the_readme_tells_people_to_install():
    data = load()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert data["project"]["requires-python"] == ">=3.10"
    assert "Python 3.10+" in readme


def test_the_readme_installs_from_pyproject_toml_not_a_bare_pip_list():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "pip install ." in readme
    assert re.search(r"pip install [\"']?fastapi", readme) is None  # the old, unpinned line
