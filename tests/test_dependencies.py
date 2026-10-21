"""Dependencies are exact, hashed and scanned (pyproject.toml, requirements.lock, frontend/package*.json, .github/workflows/ci.yml, docs/DEPENDENCIES.md; task DIYA-213), added 2026-10-21.

What this proves: every package Diya names in pyproject.toml is pinned with `==`; the hashed lock holds the same version as pyproject for each of them (the optional `push` and `dossier` extras are not
in the lock, as pyproject says) and every lock entry carries at least one hash and is pinned; the web UI's lock satisfies package.json (so `npm ci` will install it) and keeps the postcss override that
closed the audited advisories; CI runs a Python and a web UI audit; and the advisories CI ignores are exactly the ones docs/DEPENDENCIES.md explains, one reason each. It does not prove the packages
have no advisories: that is what the CI scans do, against lists that change daily.
"""
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "DEPENDENCIES.md").read_text(encoding="utf-8")


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements():
    """{extra or 'core': [(normalised name, version)]} for every pin in pyproject.toml; a requirement that is not an exact pin comes back with version None."""
    found = {"core": [], **{extra: [] for extra in PYPROJECT["project"].get("optional-dependencies", {})}}
    groups = {"core": PYPROJECT["project"]["dependencies"], **PYPROJECT["project"].get("optional-dependencies", {})}
    for group, lines in groups.items():
        for line in lines:
            m = re.match(r"^([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*==\s*([^\s;]+)$", line.strip())
            found[group].append((norm(re.split(r"[=<>!~\[ ]", line.strip(), maxsplit=1)[0]), m.group(2) if m else None))
    return found


def lock_entries():
    """{normalised name: (version, number of hashes)} from requirements.lock."""
    found, current = {}, None
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\]+)", line)
        if m:
            current = norm(m.group(1))
            found[current] = [m.group(2), 0]
        elif current and line.strip().startswith("--hash=sha256:"):
            found[current][1] += 1
    return {name: tuple(value) for name, value in found.items()}


def test_every_package_pyproject_names_is_pinned_exactly():
    loose = [(group, name) for group, items in requirements().items() for name, version in items if version is None]
    assert loose == []


def test_the_lock_holds_the_same_version_as_pyproject_for_every_package_it_covers():
    lock = lock_entries()
    wrong = []
    for group in ("core", "dev"):
        for name, version in requirements()[group]:
            if lock.get(name, (None,))[0] != version:
                wrong.append((name, version, lock.get(name)))
    assert wrong == []


def test_every_lock_entry_is_pinned_and_has_hashes():
    lock = lock_entries()
    assert len(lock) > 50
    assert [name for name, (_version, hashes) in lock.items() if hashes < 1] == []


def test_the_web_uis_lock_satisfies_package_json_and_keeps_the_postcss_override():
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))["packages"]
    assert lock[""]["dependencies"] == package["dependencies"]  # `npm ci` refuses to run if these differ
    for name, wanted in package["dependencies"].items():
        major = int(re.search(r"\d+", wanted).group(0))
        assert int(lock[f"node_modules/{name}"]["version"].split(".")[0]) == major
    assert package["overrides"] == {"postcss": "^8.5.23"}
    postcss = tuple(int(part) for part in lock["node_modules/postcss"]["version"].split("."))
    assert postcss >= (8, 5, 23)  # below that, `npm audit` reports high-severity advisories


def test_ci_scans_the_python_and_the_web_ui_packages():
    assert "pip-audit" in CI and "npm audit --audit-level=high" in CI
    assert re.search(r"pip install pip-audit==\d+\.\d+\.\d+", CI)  # the scanner itself is pinned


def ignored_in_ci():
    return set(re.findall(r"--ignore-vuln\s+(PYSEC-[0-9]+-[0-9]+|GHSA-[\w-]+|CVE-[\d-]+)", CI))


def test_the_advisories_ci_ignores_are_exactly_the_ones_the_page_explains():
    ignored = ignored_in_ci()
    assert len(ignored) == 6
    explained = set(re.findall(r"PYSEC-[0-9]+-[0-9]+", DOC.split("## The advisories that are ignored on purpose", 1)[1].split("## Licences", 1)[0]))
    assert ignored == explained


def test_every_ignored_advisory_has_a_reason_in_its_row():
    table = DOC.split("## The advisories that are ignored on purpose", 1)[1].split("## Licences", 1)[0]
    for line in table.splitlines():
        if line.startswith("| PYSEC"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            assert len(cells) == 3 and len(cells[2]) > 60, line
