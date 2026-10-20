"""docs/THREAT_MODEL.md is checked, not trusted (tasks DIYA-212 and DIYA-049).

What this proves: every test the threat model cites by `tests/file.py::name` exists in that file; every document it points to exists; and it covers the paths the blueprint's task names (tokens, tools, the local
server, MCP, remote writes, memory poisoning) plus the two doors added since (episodic recall and playbooks). It does not prove the mitigations are enough: the table has a "residual" column for what they are not.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = (ROOT / "docs" / "THREAT_MODEL.md").read_text(encoding="utf-8")


def cited():
    return sorted(set(re.findall(r"`(tests/[a-z_0-9]+\.py)::([A-Za-z_0-9]+)`", TEXT)))


def test_the_model_cites_a_test_for_every_attack_path():
    rows = [line for line in TEXT.splitlines() if re.match(r"\| \d+ \|", line)]
    assert len(rows) >= 13
    for row in rows:
        assert re.search(r"`tests/[a-z_0-9]+\.py::", row), row[:60]


def test_every_cited_test_exists():
    missing = []
    for path, name in cited():
        source = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).is_file() else ""
        if not re.search(rf"^(?:async )?def {re.escape(name)}\(", source, re.M):
            missing.append((path, name))
    assert missing == [] and len(cited()) >= 25


def test_every_document_it_points_to_exists():
    missing = [path for path in re.findall(r"`(docs/[A-Za-z0-9_./-]+\.md)`", TEXT) if not (ROOT / path).is_file()]
    assert missing == []


def test_it_covers_what_the_task_names_and_the_new_doors():
    lowered = TEXT.lower()
    for word in ("token", "tool", "local server", "mcp", "remote write", "memory poisoning", "episodic recall", "playbooks", "pause", "supply chain", "not covered", "csrf"):
        assert word in lowered, word
