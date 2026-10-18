"""docs/CAPABILITIES.md is checked, not trusted (task rows DIYA-009 and DIYA-222).

What this proves: every code file and test file the capability table names exists; every row has a date and one of the four labels; no row is both "Untried" and described as measured live; and the README
points at the table and says what the labels mean. It does not prove that a row's label is *right*: a person decides that, and the table says how.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
LABELS = {"Live", "Own code", "Stand-in", "Untried"}


def rows():
    text = (ROOT / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")
    found = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 6 and cells[0] not in ("Capability", "Label", "---") and not set(cells[0]) <= set("-"):
            found.append(cells)
    return found


def test_the_table_has_a_row_for_each_kind_of_proof():
    labels = {row[4] for row in rows()}
    assert labels == LABELS and len(rows()) >= 30


def test_every_file_a_row_names_exists():
    missing = []
    for capability, code, tests, date, label, note in rows():
        for path in re.findall(r"`([^`]+\.(?:py|mjs|js))`", code + " " + tests):
            if not (ROOT / path).is_file():
                missing.append((capability, path))
    assert missing == []


def test_every_row_has_code_tests_a_date_and_a_known_label():
    for capability, code, tests, date, label, note in rows():
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", date), capability
        assert label in LABELS, capability
        assert "`" in code and "tests/" in tests, capability


def test_an_untried_row_never_claims_a_live_measurement():
    for capability, code, tests, date, label, note in rows():
        if label == "Untried":
            assert "measured with the real" not in note.lower(), capability


def test_every_doc_a_row_points_to_exists():
    missing = []
    for capability, code, tests, date, label, note in rows():
        for path in re.findall(r"`(docs/[^`]+\.md)`", note):
            if not (ROOT / path).is_file():
                missing.append((capability, path))
    assert missing == []


def test_the_readme_links_the_table_and_names_the_labels():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/CAPABILITIES.md" in readme
    for label in ("Live", "Own code", "Stand-in", "Untried"):
        assert f"**{label}**" in readme
