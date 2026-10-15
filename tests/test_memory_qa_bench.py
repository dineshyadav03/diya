"""The question-and-answer measurement of Diya's memory (diya_memory_qa_bench.py, tests/labelled_memory_qa.py; docs/MEMORY_BENCH.md), added 2026-10-16.

What this proves: the grading is what it says (every group of required words, none of the forbidden ones, and the memory itself checked, case ignored); the cases are well formed and cover every
kind; one case goes through the real pipeline (live reading, scheduled pass, the question put to the agent with the memory in its prompt) and is graded; and the report names the cases that went wrong.
It does not measure the model: that needs Ollama and is run by hand.
"""
import sys

import pytest

import diya_memory_qa_bench as bench
from fakes import ByQuestionClient
from labelled_memory_qa import ABSTAIN, CASES, case, kinds

KINDS = {"recall", "update", "addition", "person", "noise", "abstain", "privacy", "similar"}


def test_the_grade_needs_every_group_and_none_of_the_forbidden_words_case_ignored():
    c = case("addition", ["a"], "q", [["rocky"], ["hog", "hogs"]], must_not=["cat"], facts_not=["bakery"])
    assert bench.grade(c, "Your dogs are ROCKY and Hog.", [])["ok"]
    assert bench.grade(c, "Rocky.", [])["missing"] == [["hog", "hogs"]]
    assert bench.grade(c, "Rocky, Hog and a Cat.", [])["said"] == ["cat"]
    assert bench.grade(c, "Rocky and Hog.", ["works at a Bakery"])["kept"] == ["bakery"] and not bench.grade(c, "Rocky and Hog.", ["works at a Bakery"])["ok"]


def test_a_case_with_nothing_required_passes_only_if_nothing_forbidden_is_said_or_kept():
    c = case("privacy", ["a"], "q", must_not=["4821"], facts_not=["4821"])
    assert bench.grade(c, "I don't have that.", ["likes tea"])["ok"]
    assert not bench.grade(c, "It is 4821.", [])["ok"] and not bench.grade(c, "No.", ["pin is 4821"])["ok"]


@pytest.mark.parametrize("answer", ["I don't know your sister's name.", "You haven't told me that.", "I don’t have that information.", "That has not been mentioned."])
def test_not_knowing_is_recognised_in_the_usual_ways(answer):
    assert bench.grade(case("abstain", [], "q", [ABSTAIN]), answer, [])["ok"]


def test_an_answer_that_invents_what_was_never_told_is_not_an_abstention():
    assert not bench.grade(case("abstain", [], "q", [ABSTAIN]), "Your sister is called Anita.", [])["ok"]


def test_the_cases_are_well_formed_and_cover_every_kind():
    assert set(kinds()) == KINDS and len(CASES) >= 25
    for c in CASES:
        assert c["kind"] in KINDS and c["ask"].strip().endswith("?") and all(isinstance(t, str) and t.strip() for t in c["told"])
        assert c["must"] or c["must_not"] or c["facts_not"], c["ask"]  # something is graded
        assert all(group and all(isinstance(w, str) and w for w in group) for group in c["must"])
    assert len({(tuple(c["told"]), c["ask"]) for c in CASES}) == len(CASES)  # no case twice
    for kind in KINDS:
        assert sum(1 for c in CASES if c["kind"] == kind) >= 2


def test_every_secret_and_medical_case_forbids_the_value_in_the_memory_as_well_as_the_answer():
    for c in CASES:
        if c["kind"] == "privacy":
            assert c["facts_not"] and c["must_not"]


def test_one_case_goes_through_the_live_reading_the_scheduled_pass_and_the_question(tmp_path):
    model = ByQuestionClient(extraction=["- likes tea in the morning"], chat=["You like tea in the morning."])
    c = case("recall", ["I like tea in the morning."], "What do I like in the morning?", [["tea"]])
    result = bench.run_case("fake-model", c, str(tmp_path), client=model, privacy_model="")
    assert result["ok"] and result["accepted"] == ["likes tea in the morning"] and "tea" in result["answer"]
    assert [call["kind"] for call in model.chat_calls][:1] == ["extraction"] and model.asked("chat")  # the message was read as it was said, and then the question was put
    system = model.asked("chat")[0]["messages"][0]["content"]
    assert "likes tea in the morning" in system  # the memory was in the prompt of the question


def test_a_case_that_the_memory_got_wrong_is_graded_wrong_and_says_what_it_held(tmp_path):
    model = ByQuestionClient(extraction=["- likes coffee"], chat=["You like coffee."])
    c = case("update", ["I like coffee.", "Now I like tea."], "What do I like?", [["tea"]], facts_not=["coffee"])
    result = bench.run_case("fake-model", c, str(tmp_path), client=model, privacy_model="")
    assert not result["ok"] and result["missing"] == [["tea"]] and result["kept"] == ["coffee"] and result["accepted"] == ["likes coffee"]


def test_the_summary_counts_each_kind_and_the_report_names_what_went_wrong():
    results = [
        {"kind": "recall", "ok": True}, {"kind": "recall", "ok": False, "told": ["a"], "ask": "q?", "answer": "no", "missing": [["x"]], "said": [], "kept": [], "accepted": [], "not_accepted": [], "gap": True},
        {"kind": "update", "ok": True},
    ]
    assert bench.summarise(results) == {"recall": (1, 2), "update": (1, 1)}
    lines = []
    bench.report("m", results, "p", out=lines.append)
    text = "\n".join(lines)
    assert "recall     1/2  50%" in text and "ALL        2/3  66%" in text and "WRONG [recall, gap?]" in text and "missing [['x']]" in text


def test_the_command_line_runs_chosen_kinds_and_writes_the_results_after_each_case(tmp_path):
    model = ByQuestionClient(extraction=["- likes tea"] * 4, chat=["Rocky.", "You like tea."] * 10)
    lines = []
    out = tmp_path / "results.json"
    assert bench.main(["--kinds", "recall", "--limit", "2", "--privacy-model", "", "--model", "fake", "--out", str(out)], out=lines.append, client=model) == 0
    import json

    saved = json.loads(out.read_text(encoding="utf-8"))
    assert len(saved["results"]) == 2 and saved["model"] == "fake" and any(line.startswith("[2/2]") for line in lines) and any("Memory question-and-answer" in line for line in lines)
