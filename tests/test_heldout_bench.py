"""The held-out routing benchmark (diya_heldout_bench.py, tests/labelled_heldout.py; docs/HELDOUT_BENCH.md; DIYA-191), added 2026-10-26.

What this proves, without any model: the cases are well formed (each says which tool must be called or that none may, uses only tools the benchmark's agent has, and asks for nothing the grader cannot check); no
message in them repeats one in any other labelled set or in the development evals, so the numbers are about messages nothing was tuned on; the grader separates routing from answer and finds each kind of
fault; the same temperature and seed go with every request whatever the agent asked for, and every other setting is passed on; a whole run on a scripted model gives the right pass counts, writes every answer to
the file after each message, and prints each failure in full; and several models are compared on the same messages. It does not say how any real model does: that is what running the benchmark is for.
"""
import ast
import dataclasses
import json
import re
from pathlib import Path

import pytest

import diya_heldout_bench as hb
from fakes import FakeClient, text_reply, tool_reply

ROOT = Path(__file__).resolve().parent.parent
KNOWN_TOOLS = {"search_notes", "get_weather", "list_files", "add_reminder", "list_reminders", "add_task", "list_tasks"}
CASES = hb.load_cases()


def normal(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def test_the_cases_are_well_formed():
    assert len(CASES) >= 40
    assert len({c["id"] for c in CASES}) == len(CASES) and len({normal(c["prompt"]) for c in CASES}) == len(CASES)
    for case in CASES:
        assert set(case) <= {"id", "category", "prompt", "tool", "forbidden_tools", "args_have", "answer_any", "answer_none", "max_words", "min_words", "allowed_tools"}, case["id"]
        assert case["tool"] is None or case["tool"] in KNOWN_TOOLS, case["id"]
        assert set(case.get("forbidden_tools", [])) <= KNOWN_TOOLS and case["tool"] not in case.get("forbidden_tools", []), case["id"]
        assert not case.get("args_have") or case["tool"], f"{case['id']}: words in the call, but no call is expected"
        assert case["prompt"].strip() and case["category"], case["id"]
    assert {c["category"] for c in CASES} >= {"answer", "fact-share", "notes", "weather", "files", "reminder-asked", "reminder-unasked", "task-asked", "task-unasked", "other"}


def test_no_message_repeats_one_in_any_other_labelled_set_or_in_the_development_evals():
    """Every string literal of at least 8 letters in the other labelled files and in diya_evals.py: none may equal a held-out prompt, and none may hold a whole one of them (24 characters or more) or sit whole inside one."""
    others = []
    for path in sorted((ROOT / "tests").glob("labelled_*.py")) + [ROOT / "diya_evals.py"]:
        if path.name == "labelled_heldout.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(normal(node.value)) >= 8:
                others.append((path.name, normal(node.value)))
    assert others, "found nothing to compare with"
    for case in CASES:
        mine = normal(case["prompt"])
        for name, theirs in others:
            if len(mine) >= 8 and mine == theirs:
                pytest.fail(f"{case['id']} {case['prompt']!r} is also in {name}")
            if (len(mine) >= 14 and mine in theirs) or (len(theirs) >= 24 and theirs in mine):  # a whole held-out message inside another message, or a whole other message inside it (not a short time phrase)
                pytest.fail(f"{case['id']} {case['prompt']!r} overlaps {theirs!r} in {name}")


def case(**fields):
    base = {"id": "x", "category": "c", "prompt": "p", "tool": None}
    base.update(fields)
    return base


def kinds(issues):
    return sorted(kind for kind, _ in issues)


def test_the_grader_finds_each_kind_of_fault_and_keeps_routing_apart_from_the_answer():
    assert hb.grade(case(tool=None, answer_any=["36"]), "It is 36.", [], {}) == []
    assert kinds(hb.grade(case(tool=None), "It is 36.", ["web_search"], {})) == ["tool"]
    assert kinds(hb.grade(case(tool="add_reminder"), "ok", [], {})) == ["tool"]
    assert hb.grade(case(tool=None, allowed_tools=["list_calendar_events"]), "ok", ["list_calendar_events"], {}) == []  # a read-only look the case allows
    assert kinds(hb.grade(case(tool=None, allowed_tools=["list_calendar_events"]), "ok", ["list_calendar_events", "add_reminder"], {})) == ["tool"]
    assert kinds(hb.grade(case(tool=None, forbidden_tools=["add_reminder"]), "ok", ["add_reminder"], {})) == ["forbidden", "tool"]
    assert kinds(hb.grade(case(tool="search_notes", forbidden_tools=["add_reminder"]), "the vet", ["search_notes", "add_reminder"], {})) == ["forbidden"]
    assert hb.grade(case(tool="add_reminder", args_have=["lab report"]), "ok", ["add_reminder"], {"add_reminder": ["content=Submit the Lab Report, due_at=..."]}) == []
    assert kinds(hb.grade(case(tool="add_reminder", args_have=["passport"]), "ok", ["add_reminder"], {"add_reminder": ["content=call mom"]})) == ["args"]
    assert kinds(hb.grade(case(answer_any=["36"]), "It is 35.", [], {})) == ["answer"]
    assert kinds(hb.grade(case(answer_none=["deleted all"]), "I deleted all of them", [], {})) == ["answer"]
    assert kinds(hb.grade(case(max_words=3), "one two three four", [], {})) == ["answer"]
    assert kinds(hb.grade(case(min_words=5), "one two", [], {})) == ["answer"]


def test_the_same_temperature_and_seed_go_with_every_request_and_everything_else_is_passed_on():
    client = FakeClient([text_reply("a"), text_reply("b")])
    fixed = hb.FixedConditions(client, temperature=0.0, seed=11)
    fixed.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi"}], temperature=0.9, tools=None)  # the agent asked for 0.9 (small talk): the benchmark's conditions win
    assert client.chat_calls[0]["options"] == {"temperature": 0.0, "seed": 11} and client.chat_calls[0]["model"] == "m"
    assert fixed.embeddings is client.embeddings  # anything else is the real client's


def agent_with(tmp_path, replies):
    client = FakeClient(replies)
    return hb.make_agent(str(tmp_path), "scripted", client), client


def test_a_whole_run_on_a_scripted_model_counts_passes_and_failures_and_prints_each_failure_in_full(tmp_path):
    cases = [
        case(id="a", category="answer", prompt="whats 15% of 240", tool=None, answer_any=["36"]),
        case(id="b", category="notes", prompt="what did i write about the garden?", tool="search_notes", args_have=["garden"], answer_any=["tomato"]),
        case(id="c", category="reminder-asked", prompt="remind me to submit the lab report tomorrow at 5pm", tool="add_reminder", args_have=["lab report"]),
    ]
    agent, client = agent_with(tmp_path, [
        text_reply("It is 36."),
        tool_reply("search_notes", json.dumps({"query": "garden"})), text_reply("You plan to plant tomatoes and basil."),
        text_reply("Sure, I will remind you."),  # the model said it would and called nothing: a routing fault
    ])
    lines = []
    records = hb.run(agent, cases, 1, say=lines.append, save=None)
    assert [r["passed"] for r in records] == [True, True, False]
    assert records[1]["tools"] == ["search_notes"] and "garden" in " ".join(records[1]["previews"]["search_notes"]).lower()
    assert records[2]["routing_ok"] is False and records[2]["answer_ok"] is True
    table = hb.summarize(records)
    assert table["all"] == (2, 2, 3, 3) and table["reminder-asked"] == (0, 0, 1, 1)
    report = hb.render("scripted", records, {"cases_hash": hb.cases_hash(cases), "runs": 1, "temperature": 0.0, "seed": 7})
    assert "1 failure(s)" in report and "c (reminder-asked, trial 1)" in report and "expected add_reminder, got no tool" in report and "Sure, I will remind you." in report
    assert sum(1 for line in lines if line.startswith("[PASS]")) == 2 and sum(1 for line in lines if line.startswith("[FAIL]")) == 1
    assert len(client.chat_calls) == 4


def test_a_crash_is_a_failure_to_report_and_the_run_goes_on(tmp_path):
    agent, _client = agent_with(tmp_path, [])  # no reply is left to give: the stand-in raises
    record = hb.run_case(agent, case(id="z", prompt="hi", tool=None))
    assert record["passed"] is False and record["issues"][0][1].startswith("crashed with")


def test_the_command_runs_every_model_on_the_same_messages_writes_the_file_after_each_message_and_compares(tmp_path, capsys):
    out = tmp_path / "result.json"
    scripted = {"one": FakeClient([text_reply("It is 36."), text_reply("Leap years have 366 days.")]), "two": FakeClient([text_reply("It is 35."), text_reply("366")])}
    lines = []
    code = hb.main(["--model", "one,two", "--category", "answer", "--limit", "2", "--out", str(out)], client_factory=lambda model: scripted[model], say=lines.append, warm=False)
    assert code == 0
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["settings"]["cases"] == 2 and saved["settings"]["temperature"] == 0.0 and set(saved["results"]) == {"one", "two"}
    assert [r["passed"] for r in saved["results"]["one"]] == [True, True] and [r["passed"] for r in saved["results"]["two"]] == [False, True]
    joined = "\n".join(lines)
    assert "Comparison (same messages, tools and conditions)" in joined and "one" in joined and "passed 2/2" in joined and "passed 1/2" in joined


def test_the_hash_names_the_cases_and_changes_when_a_case_does():
    assert hb.cases_hash(CASES) == hb.cases_hash(list(CASES))
    changed = [dict(CASES[0], prompt=CASES[0]["prompt"] + "?")] + CASES[1:]
    assert hb.cases_hash(changed) != hb.cases_hash(CASES)
