"""The licence review is checked, not trusted (docs/LICENCES.md; task DIYA-225), added 2026-10-21.

What this proves: Diya's own licence is what the review and the README say (all rights reserved: no LICENSE file is tracked); the numbers the review states about the Python lock and the web UI's lock are
the numbers in those files; the web UI's lock holds no GPL, AGPL or SSPL package and no LGPL package except the optional `@img/sharp-*` image tools the review explains (so a new one cannot arrive unnoticed),
and every locked package states a licence; every Python package installed here that Diya's lock names has no GPL, AGPL, LGPL or SSPL licence; every package pyproject names appears in the review; every icon
Diya ships from another author is in THIRD_PARTY_NOTICES.md; and no tracked file carries the markers of the blueprint's pasted third-party pages, which must stay on the owner's computer. It does not
prove a licence is *correctly* stated by its package: that is the package author's claim.
"""
import json
import re
import subprocess
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REVIEW = (ROOT / "docs" / "LICENCES.md").read_text(encoding="utf-8")
LOCK = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
COPYLEFT = re.compile(r"\b(?:AGPL|GPL|SSPL)\b", re.IGNORECASE)


def tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    return [ROOT / line for line in out if line]


def test_diya_is_all_rights_reserved_and_no_licence_file_is_tracked():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "All rights reserved" in readme and "no LICENSE file" in REVIEW
    names = {path.name.upper() for path in tracked() if path.parent == ROOT}
    assert not names & {"LICENSE", "LICENSE.MD", "LICENSE.TXT", "COPYING"}


def test_the_numbers_the_review_states_about_the_python_lock_are_the_locks():
    pins = [line for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines() if re.match(r"^[A-Za-z0-9_.\-]+==", line)]
    assert f"`requirements.lock` pins {len(pins)} packages" in REVIEW


def test_the_numbers_the_review_states_about_the_web_uis_lock_are_the_locks():
    packages = {path: info for path, info in LOCK.items() if path}
    assert f"locks {len(packages)} packages besides the project itself" in REVIEW
    lgpl = [path for path, info in packages.items() if "LGPL" in str(info.get("license"))]
    assert f"**{len(lgpl)}**: " in REVIEW


def test_the_web_uis_lock_has_no_strong_copyleft_and_no_unlicensed_package():
    packages = {path: info for path, info in LOCK.items() if path}
    assert [path for path, info in packages.items() if not info.get("license")] == []
    strong = [path for path, info in packages.items() if COPYLEFT.search(str(info["license"]).replace("LGPL", "L-G-P-L"))]
    assert strong == []


def test_the_only_lgpl_packages_are_the_optional_image_tools_the_review_explains():
    lgpl = {path: info for path, info in LOCK.items() if path and "LGPL" in str(info.get("license"))}
    assert lgpl and all(path.startswith("node_modules/@img/sharp-") and info.get("optional") for path, info in lgpl.items())
    assert "LGPL group" in REVIEW


def installed_licence_text(name):
    try:
        md = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return None
    classifiers = " ".join(c for c in md.get_all("Classifier") or [] if c.startswith("License ::"))
    return " ".join([md.get("License-Expression") or "", classifiers, (md.get("License") or "")[:120]])


def locked_names():
    return [m.group(1) for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines() if (m := re.match(r"^([A-Za-z0-9_.\-]+)==", line))]


def test_no_installed_python_package_in_the_lock_is_under_a_strong_copyleft_licence():
    checked, bad = 0, []
    for name in locked_names():
        text = installed_licence_text(name)
        if text is None:
            continue
        checked += 1
        if COPYLEFT.search(text.replace("LGPL", "L-G-P-L")) or "LGPL" in text or "Lesser General Public" in text:
            bad.append((name, text.strip()[:80]))
    assert checked > 20  # the check looked at something
    assert bad == []


def test_every_package_pyproject_names_is_in_the_review():
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lines = data["dependencies"] + [line for extra in data.get("optional-dependencies", {}).values() for line in extra]
    names = [re.split(r"[=<>!~\[ ]", line, maxsplit=1)[0] for line in lines]
    assert len(names) >= 12
    assert [name for name in names if f"`{name}`" not in REVIEW] == []


def test_every_icon_from_another_author_is_in_the_notices():
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    icons = sorted(path.name for path in (ROOT / "frontend" / "public" / "icons").iterdir())
    assert icons and [name for name in icons if name not in notices] == []


@pytest.mark.parametrize("marker", ["Original PDF page", "## Original PDF"])
def test_no_tracked_file_carries_the_markers_of_the_blueprints_pasted_third_party_pages(marker):
    offenders = []
    for path in tracked():
        if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".zip", ".lock"} or not path.is_file() or "node_modules" in path.parts:
            continue
        if path.name == "test_licences.py" or str(path.relative_to(ROOT)).replace("\\", "/").startswith("harness/"):
            continue
        try:
            if marker in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
        except (UnicodeDecodeError, OSError):
            continue
    assert offenders == []


def test_the_harness_folder_is_a_plain_copy_that_carries_its_own_licence_and_no_link_back():
    """The owner's rule of 2026-10-21 (docs/DSH_PLAN.md): the code is copied into Diya as its own folder, not used as a dependency and not linked to where it came from. The MIT licence that comes with
    the code stays in the folder and in THIRD_PARTY_NOTICES.md: MIT requires the notice to travel with every copy."""
    assert not (ROOT / ".gitmodules").exists()  # no submodule
    assert not (ROOT / "harness" / ".git").exists() and not (ROOT / "harness" / "node_modules").exists()  # no history, nothing installed
    licence = (ROOT / "harness" / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in licence and "Permission is hereby granted" in licence and "above copyright notice" in licence
    assert "harness/LICENSE" in (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower() + (ROOT / "frontend" / "package.json").read_text(encoding="utf-8").lower()
    assert "deepseek-harness" not in pyproject and "@deepseek-ai" not in pyproject  # nothing depends on the original
