"""diya_actions_bench.py: the measurement of when the model proposes a Todoist task (docs/ACTIONS_DESIGN.md, section 6).

The numbers in that document come from this script, so the script is tested: against a scripted model (no Ollama), it must
drive the real Agent, count reaching for the tool and recording a proposal as the two different things they are, stub
every tool that could touch the network or the disk, leave nothing pending behind, and say what it measured.
"""
import io
import json

import pytest

import diya
import diya_actions_bench as bench
import diya_intent
from fakes import FakeClient, text_reply, tool_reply
from labelled_task_requests import AMBIGUOUS, ASKED, NOT_ASKED, all_not_asked


REAL_BUILD_AGENT = bench.build_agent  # kept, because some tests replace bench.build_agent with a scripted one


def scripted(tmp_path, replies):
    """The benchmark's own agent, on a scripted model instead of Ollama."""
    agent = REAL_BUILD_AGENT("a-model-that-is-never-called", str(tmp_path))
    agent._client = FakeClient(list(replies))
    return agent


def propose(arguments):
    return tool_reply(bench.PROPOSE, json.dumps(arguments))


# ---- the benchmark's agent ---------------------------------------------------------------------------

def test_the_benchmark_agent_offers_todoist_and_never_reaches_a_real_service(tmp_path):
    agent = REAL_BUILD_AGENT("some-model", str(tmp_path))
    assert agent.config.model == "some-model"
    assert bench.PROPOSE in [tool["function"]["name"] for tool in agent.tools]  # Todoist counts as connected
    assert agent.config.db_path.startswith(str(tmp_path))  # a temporary database, never the real one
    for name, args, expected in (("web_search", ("x",), "Top result"), ("get_weather", ("x",), "Sunny"), ("search_notes", ("x",), "A note"),
                                 ("list_files", (), "notes.txt"), ("list_reminders", (), "No pending"), ("list_todoist_tasks", (), "Buy milk")):
        assert expected in agent._functions[name](*args), name


def test_a_reminder_the_model_saves_is_recorded_not_written_to_any_database(tmp_path):
    agent = REAL_BUILD_AGENT("m", str(tmp_path))
    assert agent._functions["add_reminder"]("call mum", None) == "Reminder saved: call mum"
    assert agent.bench_reminders == ["call mum"] and agent.store.reminders("all") == []


# ---- asking one message ------------------------------------------------------------------------------

def test_a_proposal_that_was_asked_for_is_recorded_and_then_cleared_away(tmp_path):
    agent = scripted(tmp_path, [propose({"content": "Buy oat milk"}), text_reply("It is waiting for you.")])
    result = bench.ask_once(agent, "Add a task to buy oat milk")
    assert bench.proposed(result)
    assert [a["args"] for a in result["attempts"]] == [{"content": "Buy oat milk"}]
    assert result["attempts"][0]["result"].startswith("Proposed as action #1")
    assert result["recorded"] == [{"content": "Buy oat milk"}]
    assert result["tools"] == [bench.PROPOSE] and result["answer"] == "It is waiting for you."
    assert agent.actions.pending() == [] and agent.actions.counts()["rejected"] == 1  # the next message starts clean


def test_a_proposal_nobody_asked_for_is_reached_for_but_not_recorded(tmp_path):
    agent = scripted(tmp_path, [propose({"content": "Buy milk"}), text_reply("Noted.")])
    result = bench.ask_once(agent, "I need to buy milk")
    assert bench.proposed(result) and result["recorded"] == []
    assert result["attempts"][0]["result"] == "Not proposed: the user did not ask for that. Answer what they said instead, and do not propose it unless they ask."


def test_a_message_the_model_just_answers_has_no_attempt_and_nothing_recorded(tmp_path):
    agent = scripted(tmp_path, [text_reply("Paris.")])
    result = bench.ask_once(agent, "What's the capital of France?")
    assert not bench.proposed(result) and result["attempts"] == [] and result["recorded"] == [] and result["tools"] == []


def test_a_made_up_due_date_is_visible_in_the_attempt_and_left_off_the_record(tmp_path):
    agent = scripted(tmp_path, [propose({"content": "Call mum", "due_string": "tomorrow at 5pm"}), text_reply("ok")])
    result = bench.ask_once(agent, "add task call mum")
    assert result["attempts"][0]["args"] == {"content": "Call mum", "due_string": "tomorrow at 5pm"}  # what the model chose
    assert result["recorded"] == [{"content": "Call mum"}]  # what the owner would see


def test_a_reminder_the_model_saves_while_answering_is_reported_for_reference(tmp_path):
    from fakes import tool_reply as call

    agent = scripted(tmp_path, [call("add_reminder", json.dumps({"content": "call the plumber"})), text_reply("Saved.")])
    result = bench.ask_once(agent, "Make a note to call the plumber")
    assert result["reminders"] == ["call the plumber"] and not bench.proposed(result)


def test_one_message_s_reminders_are_not_counted_against_the_next(tmp_path):
    from fakes import tool_reply as call

    agent = scripted(tmp_path, [call("add_reminder", json.dumps({"content": "call the plumber"})), text_reply("Saved."), text_reply("Paris.")])
    assert bench.ask_once(agent, "Make a note to call the plumber")["reminders"] == ["call the plumber"]
    assert bench.ask_once(agent, "What's the capital of France?")["reminders"] == []


def test_the_proposing_function_is_put_back_after_every_message(tmp_path):
    agent = scripted(tmp_path, [text_reply("a"), propose({"content": "x"}), text_reply("b")])
    before = agent._functions[bench.PROPOSE]
    bench.ask_once(agent, "hello")
    assert agent._functions[bench.PROPOSE] is before
    bench.ask_once(agent, "add a task x")
    assert agent._functions[bench.PROPOSE] is before


def test_the_functions_put_back_even_when_the_model_fails(tmp_path):
    agent = scripted(tmp_path, [])
    agent.client._chat_error = RuntimeError("Ollama is down")
    before = agent._functions[bench.PROPOSE]
    with pytest.raises(RuntimeError):
        bench.ask_once(agent, "hello")
    assert agent._functions[bench.PROPOSE] is before


def test_what_the_tool_loop_prints_does_not_reach_the_report(tmp_path, capsys):
    agent = scripted(tmp_path, [propose({"content": "x"}), text_reply("ok")])
    bench.ask_once(agent, "add a task x")
    assert "[tool call]" not in capsys.readouterr().out


# ---- a whole run ----------------------------------------------------------------------------------------

def test_a_run_asks_every_labelled_message_the_stated_number_of_times(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: scripted(tmp_path, [text_reply("fine")] * 400))
    results = bench.run_model("m", runs=2, limit=0)
    assert len(results["asked"]) == 2 * len(ASKED)
    assert {c: len(rs) for c, rs in results["not_asked"].items()} == {c: 2 * len(texts) for c, texts in NOT_ASKED.items()}
    assert len(results["ambiguous"]) == 2 * len(AMBIGUOUS)
    assert results["model"] == "m" and results["runs"] == 2 and isinstance(results["seconds"], int)


def test_a_limited_run_takes_the_first_few_of_each_list_and_skips_the_ambiguous_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: scripted(tmp_path, [text_reply("fine")] * 100))
    results = bench.run_model("m", runs=1, limit=2)
    assert [r["text"] for r in results["asked"]] == ASKED[:2]
    assert all(len(rs) <= 2 for rs in results["not_asked"].values()) and results["ambiguous"] == []


# ---- the report ----------------------------------------------------------------------------------------

def result(text, attempts=(), recorded=(), tools=(), reminders=()):
    return {"text": text, "tools": list(tools), "attempts": [{"args": a, "result": r} for a, r in attempts],
            "recorded": list(recorded), "reminders": list(reminders), "answer": ""}


SAMPLE = {
    "model": "m", "runs": 1, "seconds": 7,
    "asked": [
        result("Add a task to buy milk", [({"content": "Buy milk"}, "Proposed as action #1")], [{"content": "Buy milk"}], [bench.PROPOSE]),
        result("add task call mum", [({"content": "Call mum", "due_string": "tomorrow at 5pm"}, "Proposed as action #2")], [{"content": "Call mum"}], [bench.PROPOSE]),
        result("add a task", [({"content": "x", "due_string": ""}, "Not proposed: bad")], [], [bench.PROPOSE]),
        result("Could you put it on my list?", [], [], []),
    ],
    "not_asked": {
        "needs": [result("I need to buy milk", [({"content": "Buy milk"}, "Not proposed: the user did not ask")], [], [bench.PROPOSE]),
                  result("I want tea")],
        "reminders": [result("Make a note to call the plumber", reminders=["call the plumber"])],
    },
    "ambiguous": [result("Add milk to my shopping list", [({"content": "Milk"}, "Proposed")], [{"content": "Milk"}]), result("todo: x")],
}


def test_the_report_counts_reaching_for_the_tool_and_recording_a_proposal_separately():
    out = io.StringIO()
    bench.report(SAMPLE, out)
    text = out.getvalue()
    assert "Model m: 4 asked, 3 not asked, 1 run(s) each, 7 s." in text
    assert "Asked for a task:   the model reached for the tool in 3 of 4 (75%); a proposal was recorded in 2 (50%)" in text
    assert "Not asked:          the model reached for the tool in 1 of 3 (33%); a proposal was recorded in 0 (0%)" in text
    assert "needs                        reached 1, recorded 0, of 2" in text
    assert "reminders                    reached 0, recorded 0, of 1" in text
    assert "no proposal: 'Could you put it on my list?'" in text and "no proposal: 'add a task'" in text
    assert "no proposal: 'Add a task to buy milk'" not in text
    assert "unasked: 'I need to buy milk' -> recorded=False [{'content': 'Buy milk'}]" in text


def test_the_report_counts_an_unasked_message_that_did_end_up_recorded():
    leaky = dict(SAMPLE, asked=[], ambiguous=[], not_asked={
        "needs": [result("I need to buy milk", [({"content": "Buy milk"}, "Proposed as action #1")], [{"content": "Buy milk"}], [bench.PROPOSE]),
                  result("I want tea")]})
    out = io.StringIO()
    bench.report(leaky, out)
    text = out.getvalue()
    assert "Not asked:          the model reached for the tool in 1 of 2 (50%); a proposal was recorded in 1 (50%)" in text
    assert "needs                        reached 1, recorded 1, of 2" in text
    assert "unasked: 'I need to buy milk' -> recorded=True [{'content': 'Buy milk'}]" in text


def test_the_report_counts_the_due_dates_the_model_made_up_before_and_after_the_checks():
    out = io.StringIO()
    bench.report(SAMPLE, out)
    text = out.getvalue()
    assert "Due phrases that are not the person's own words: 1 of 1 the model gave; 0 of 0 on a recorded proposal" in text
    assert "'add task call mum' -> due 'tomorrow at 5pm'" in text


def test_the_report_counts_a_due_date_that_survives_as_the_persons_own_words():
    own = dict(SAMPLE, asked=[result("Add a task due tomorrow", [({"content": "x", "due_string": "tomorrow"}, "Proposed")],
                                     [{"content": "x", "due_string": "tomorrow"}], [bench.PROPOSE])], not_asked={}, ambiguous=[])
    out = io.StringIO()
    bench.report(own, out)
    assert "Due phrases that are not the person's own words: 0 of 1 the model gave; 0 of 1 on a recorded proposal" in out.getvalue()


def test_the_report_says_how_the_arguments_the_model_chose_fared():
    out = io.StringIO()
    bench.report(SAMPLE, out)
    text = out.getvalue()
    assert "Arguments the model chose when asked (3 attempts): a due phrase in 1, empty or null due phrase in 1, unknown arguments in 0, refused by the checks in 1" in text
    assert "refused: {'content': 'x', 'due_string': ''} -> Not proposed: bad" in text


def test_the_report_gives_the_reminder_count_for_reference_and_lists_the_ambiguous_ones_unscored():
    out = io.StringIO()
    bench.report(SAMPLE, out)
    text = out.getvalue()
    assert "(for reference: add_reminder was reached for on 1 of the not-asked messages)" in text
    assert "proposed  'Add milk to my shopping list'" in text and "did not     'todo: x'" in text


def test_percent_of_nothing_is_not_a_number():
    assert bench.percent(1, 4) == "25%" and bench.percent(0, 5) == "0%" and bench.percent(5, 5) == "100%" and bench.percent(0, 0) == "n/a"


# ---- the guard, scored without the model ----------------------------------------------------------------------

def test_scoring_the_guard_needs_no_model_and_reports_what_it_got_wrong():
    out = io.StringIO()
    assert bench.score_guard(out) == 0
    text = out.getvalue()
    assert f"allowed {len(ASKED)} of {len(ASKED)} (100%)" in text
    assert f"allowed 0 of {len(all_not_asked())} (0%)" in text
    assert "refused  'Add milk to my shopping list'" in text and "allowed  'todo: call the bank'" in text


def test_scoring_a_guard_that_is_missing_says_so(monkeypatch):
    monkeypatch.delattr(diya_intent, "is_task_request")
    out = io.StringIO()
    assert bench.score_guard(out) == 1 and "no diya_intent.is_task_request yet" in out.getvalue()


def test_scoring_a_poor_guard_lists_its_mistakes(monkeypatch):
    monkeypatch.setattr(diya_intent, "is_task_request", lambda text: text.startswith("Add"))
    out = io.StringIO()
    bench.score_guard(out)
    text = out.getvalue()
    assert "  refused: " in text and "  allowed: " in text


# ---- the command line ----------------------------------------------------------------------------------------

def test_guard_only_runs_without_a_model():
    out = io.StringIO()
    assert bench.main(["--guard-only"], out=out) == 0 and "Asked for a task:   allowed" in out.getvalue()


def test_a_run_prints_its_report_and_can_save_every_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit: dict(SAMPLE, model=model, runs=runs))
    out, saved = io.StringIO(), tmp_path / "results.json"
    assert bench.main(["--model", "qwen3:8b", "--runs", "2", "--out", str(saved)], out=out) == 0
    assert "Model qwen3:8b:" in out.getvalue()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["model"] == "qwen3:8b" and data["runs"] == 2 and len(data["asked"]) == 4
    assert b"\r" not in saved.read_bytes()  # LF, like every text file here


def test_the_default_model_is_the_configured_one(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit: seen.update(model=model, runs=runs, limit=limit) or SAMPLE)
    bench.main([], out=io.StringIO())
    assert seen == {"model": "qwen2.5:3b", "runs": 1, "limit": 0}


@pytest.mark.parametrize("runs, expected", [("0", 1), ("-3", 1), ("4", 4)])
def test_a_run_count_below_one_is_one(monkeypatch, runs, expected):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit: seen.update(runs=runs) or SAMPLE)
    bench.main(["--runs", runs], out=io.StringIO())
    assert seen["runs"] == expected


def test_a_model_that_cannot_be_reached_is_a_clean_failure_not_a_traceback(monkeypatch, capsys):
    def down(model, runs, limit):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(bench, "run_model", down)
    assert bench.main([], out=io.StringIO()) == 2
    assert "could not run against qwen2.5:3b: connection refused" in capsys.readouterr().err


def test_the_labelled_messages_the_benchmark_uses_are_the_ones_the_guard_tests_use():
    assert len(ASKED) == 25 and sum(len(t) for t in NOT_ASKED.values()) == 51
