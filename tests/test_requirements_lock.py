"""requirements.lock pins the full transitive dependency tree with hashes. This checks it stays in
sync with pyproject.toml's own direct pins (nothing else enforces that -- a hand-edited pin drift
between the two files would otherwise go unnoticed), and that it really is hash-locked, not just
versioned.
"""
import pathlib
import re
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "requirements.lock"


def load_pyproject():
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)


def lock_versions():
    text = LOCK.read_text(encoding="utf-8")
    return dict(re.findall(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)", text, flags=re.M))


def test_the_lock_file_exists_and_is_not_empty():
    assert LOCK.is_file() and LOCK.stat().st_size > 0


def test_every_direct_dependency_is_in_the_lock_at_the_same_version():
    """Covers both pyproject.toml's main dependencies and its dev extra (pytest) -- the lock was
    generated with --extra dev specifically so the suite could run from it alone."""
    data = load_pyproject()
    versions = lock_versions()
    specs = list(data["project"]["dependencies"]) + list(data["project"]["optional-dependencies"]["dev"])
    for spec in specs:
        name, version = spec.split("==")
        assert versions.get(name) == version, (name, "lock has", versions.get(name), "pyproject wants", version)


def test_the_dossier_only_extra_is_not_in_the_lock():
    """reportlab is only needed to regenerate the PDF (render_pdf.py), not to run the app or the
    test suite -- leaving it out keeps the lock scoped to what "run the suite" actually needs."""
    assert "reportlab" not in lock_versions()


def test_every_pinned_package_in_the_lock_has_at_least_one_hash():
    text = LOCK.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)
    problems = [
        m.group(1)
        for block in blocks
        if (m := re.match(r"([A-Za-z0-9_.-]+)==", block)) and "--hash=sha256:" not in block
    ]
    assert not problems, problems
