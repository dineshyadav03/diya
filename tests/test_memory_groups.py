"""Grouping the Memory page's accepted facts by who they are about (frontend/lib/memory-groups.mjs),
the pure logic behind docs/PERSON_MEMORY_DESIGN.md's D5 (unit M3). Tested under Node, the same way
frontend/lib/api-failure.mjs is (tests/test_frontend_failure_messages.py): a pure function is easier
to prove right in isolation than by rendering the page, which has no design-rig coverage today.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
MODULE = FRONTEND / "lib" / "memory-groups.mjs"
PAGE = FRONTEND / "app" / "memory" / "page.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

CODE = (
    "import { pathToFileURL } from 'node:url'\n"
    "const m = await import(pathToFileURL(process.argv[1]).href)\n"
    "const facts = JSON.parse(process.argv[2])\n"
    "process.stdout.write(JSON.stringify(m.groupByPerson(facts)))\n"
)


def groups(*facts):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", CODE, str(MODULE), json.dumps(list(facts))],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def fact(id, person=None):
    return {"id": id, "person": person}


@needs_node
def test_no_facts_is_no_groups():
    assert groups() == []


@needs_node
def test_untagged_facts_are_the_you_group_first():
    result = groups(fact(1), fact(2, "Maya"))
    assert [g["label"] for g in result] == ["You", "Maya"]
    assert [f["id"] for f in result[0]["facts"]] == [1]
    assert [f["id"] for f in result[1]["facts"]] == [2]


@needs_node
def test_named_people_are_alphabetical_case_insensitively():
    result = groups(fact(1, "Zed"), fact(2, "maya"), fact(3, "Sam"))
    assert [g["label"] for g in result] == ["maya", "Sam", "Zed"]


@needs_node
def test_a_group_with_no_facts_is_left_out_not_shown_empty():
    result = groups(fact(1, "Maya"))  # nothing untagged at all
    assert [g["label"] for g in result] == ["Maya"]  # no "You" group


@needs_node
def test_each_group_keeps_its_facts_in_the_order_given():
    result = groups(fact(1, "Maya"), fact(2), fact(3, "Maya"), fact(4))
    you = next(g for g in result if g["label"] == "You")
    maya = next(g for g in result if g["label"] == "Maya")
    assert [f["id"] for f in you["facts"]] == [2, 4]
    assert [f["id"] for f in maya["facts"]] == [1, 3]


@needs_node
def test_a_person_literally_named_you_gets_its_own_group_not_merged_with_the_self_group():
    """check_person_name forbids control characters, so the self group's key (a NUL prefix) can never
    collide with a real name -- even one spelled exactly like the self group's own label."""
    result = groups(fact(1), fact(2, "you"))
    labels = [g["label"] for g in result]
    assert labels.count("You") == 1 and "you" in labels
    you_group = next(g for g in result if g["label"] == "You")
    named_group = next(g for g in result if g["label"] == "you")
    assert [f["id"] for f in you_group["facts"]] == [1]
    assert [f["id"] for f in named_group["facts"]] == [2]


def test_the_memory_page_imports_the_grouping_function():
    source = PAGE.read_text(encoding="utf-8")
    assert re.search(r"import \{ groupByPerson \} from '\.\./\.\./lib/memory-groups\.mjs'", source)
    assert "groupByPerson(accepted)" in source
