"""A nudge out of repeated tool calls and a limit on one tool result (diya_toolguard; diya.py's tool loop), added 2026-10-21.

What this proves: a result up to the limit is given to the model unchanged and a longer one is cut to its first 4,096 and last 1,024 characters with a marker between, so the start and the end survive and the
middle does not fill the window; the same tool called with the same arguments in a row is reminded on the third call (gently) and the fifth (with the tool, the count and the arguments), and not on the others; a
different call starts the count again; two calls whose arguments differ only in the order of the keys are the same call; arguments that are not JSON are compared as written; a very long argument is cut in the reminder;
one turn's count never leaks into the next; and in the real agent, with a scripted model that keeps calling one tool, the third and fifth tool results carry the reminder and a huge tool result is given cut.
"""
import dataclasses
import json

import pytest

import diya
import diya_config
import diya_toolguard as guard
from fakes import FakeClient, text_reply, tool_reply


def test_a_short_result_is_given_unchanged_and_the_limit_itself_is_short_enough():
    assert guard.prune("x" * guard.THRESHOLD_CHARS) == "x" * guard.THRESHOLD_CHARS
    assert guard.prune("") == "" and guard.prune(None) is None and guard.prune(5) == 5


def test_a_long_result_keeps_its_start_and_its_end_and_loses_the_middle():
    text = "A" * 5000 + "M" * 20000 + "Z" * 3000
    cut = guard.prune(text)
    assert cut.startswith("A" * guard.HEAD_CHARS) and cut.endswith("Z" * guard.TAIL_CHARS) and guard.MARKER in cut
    assert len(cut) == guard.HEAD_CHARS + len(guard.MARKER) + guard.TAIL_CHARS and "M" not in cut
    assert len(guard.prune("y" * (guard.THRESHOLD_CHARS + 1))) < guard.THRESHOLD_CHARS  # one character over is already cut


def test_the_third_and_fifth_identical_calls_in_a_row_are_reminded_and_no_others():
    repeats = guard.RepeatGuard()
    said = [repeats.after("list_files", '{"path": "a"}') for _ in range(8)]
    assert [i + 1 for i, note in enumerate(said) if note] == [3, 5]
    assert "repeating the exact same tool call" in said[2] and "list_files" not in said[2]
    assert "Tool: list_files" in said[4] and "Calls in a row: 5" in said[4] and '{"path":"a"}' in said[4] and "Do not call this tool with these exact arguments again" in said[4]


def test_a_different_call_starts_the_count_again():
    repeats = guard.RepeatGuard()
    assert [repeats.after("a", "{}"), repeats.after("a", "{}"), repeats.after("b", "{}"), repeats.after("a", "{}"), repeats.after("a", "{}")] == [None] * 5
    assert repeats.after("a", "{}") is not None  # the third in a row since the last change


def test_arguments_that_differ_only_in_key_order_are_the_same_call():
    repeats = guard.RepeatGuard()
    assert repeats.after("t", '{"a": 1, "b": 2}') is None and repeats.after("t", '{"b":2,"a":1}') is None and repeats.after("t", {"a": 1, "b": 2}) is not None


def test_arguments_that_are_not_json_are_compared_as_written_and_long_ones_are_cut_in_the_reminder():
    repeats = guard.RepeatGuard()
    assert [repeats.after("t", " not json ") for _ in range(2)] == [None, None] and repeats.after("t", "not json") is not None
    long = guard.RepeatGuard()
    notes = [long.after("t", json.dumps({"q": "w" * 1000})) for _ in range(5)]
    assert notes[4].count("w") <= guard.ARGUMENT_CHARS and "..." in notes[4]


def test_each_turn_has_its_own_count():
    assert guard.RepeatGuard().after("a", "{}") is None and guard.RepeatGuard().after("a", "{}") is None


@pytest.fixture
def agent(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "g.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), categories=False, lookup=False,
    )

    def make(replies):
        return diya.Agent(config, client=FakeClient(list(replies)))

    return make


def tool_results(agent):
    return [m["content"] for m in agent.client.chat_calls[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"]


def test_in_the_real_agent_a_model_that_keeps_calling_one_tool_is_reminded_on_the_third_and_fifth_call(agent):
    model = agent([tool_reply("list_reminders", "{}", call_id=f"c{n}") for n in range(6)] + [text_reply("Done.")])
    answer, tools = model.ask([{"role": "user", "content": "keep looking at my reminders"}])
    results = tool_results(model)
    assert answer == "Done." and len(results) == 6
    assert ["repeating the exact same tool call" in r for r in results] == [False, False, True, False, False, False]
    assert "Tool: list_reminders" in results[4] and "Calls in a row: 5" in results[4]


def test_in_the_real_agent_a_huge_tool_result_is_given_cut(agent):
    model = agent([tool_reply("list_reminders", "{}"), text_reply("Done.")])
    model._functions["list_reminders"] = lambda: "S" * 4000 + "x" * 50000 + "E" * 2000
    model.ask([{"role": "user", "content": "keep looking at my reminders"}])
    (result,) = tool_results(model)
    assert len(result) < guard.THRESHOLD_CHARS and result.startswith("S" * 100) and result.endswith("E" * 100) and guard.MARKER in result


def test_a_short_result_and_an_ordinary_turn_are_untouched(agent):
    model = agent([tool_reply("list_reminders", "{}"), text_reply("Done.")])
    model._functions["list_reminders"] = lambda: "No reminders."
    model.ask([{"role": "user", "content": "keep looking at my reminders"}])
    assert tool_results(model) == ["No reminders."]
