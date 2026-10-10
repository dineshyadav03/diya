"""diya_schedule_bench.py: the measurement of what the model does with a repeat (docs/SCHEDULE_DESIGN.md, D7 and unit R3).

The numbers in that document come from this script, so the script is tested: against a scripted model (no Ollama) it must drive
the real Agent, score by what was SAVED and not by what was said, tell a repeating reminder from a single one, clear the database
between messages, keep what it measured after every message (a run that is stopped must not lose it), stub every tool that could
touch the network, and say what it measured.
"""
import io
import json

import pytest

import diya_schedule_bench as bench
from fakes import FakeClient, text_reply, tool_reply
from labelled_repeats import NOT_A_REMINDER, ONE_OFF, REPEAT_ASKED, REPEAT_UNSUPPORTED

REAL_BUILD_AGENT = bench.build_agent


def scripted(tmp_path, replies):
    agent = REAL_BUILD_AGENT("a-model-that-is-never-called", str(tmp_path))
    agent._client = FakeClient(list(replies))
    return agent


def reminder(**args):
    return tool_reply("add_reminder", json.dumps(args))


# ---- the labelled data -------------------------------------------------------------------------------------

def test_the_labelled_messages_are_what_the_benchmark_asks_in_the_order_it_asks_them():
    asked = bench.messages()
    assert len(asked) == len(REPEAT_ASKED) + len(REPEAT_UNSUPPORTED) + len(ONE_OFF) + len(NOT_A_REMINDER) == 53
    assert [c for c, _, _ in asked] == (["repeat asked"] * 20 + ["repeat unsupported"] * 9 + ["one-off"] * 12 + ["not a reminder"] * 12)
    assert all(expected is not None for c, _, expected in asked if c == "repeat asked")
    assert all(expected is None for c, _, expected in asked if c != "repeat asked")
    assert len({text for _, text, _ in asked}) == 53


def test_every_rule_the_labelled_requests_expect_is_one_the_reader_reads_and_the_messages_contain_their_words():
    """The expected rules are checked against the reader itself, so a label that no code could ever produce is caught here."""
    from datetime import datetime

    import diya_repeat

    now = datetime(2026, 10, 10, 10, 15)
    for text, expected in REPEAT_ASKED:
        assert text == " ".join(text.split())
        found = [w for w in ("every", "daily", "weekdays") if w in text.lower()]
        assert found, text
        words = text.split(" to ", 1)[0]
        rule = None
        for start in range(len(words.split())):
            candidate = " ".join(words.split()[start:])
            try:
                rule = diya_repeat.parse_repeat(candidate, now).canonical().split("#")[0]
                break
            except diya_repeat.NotUnderstood:
                continue
        assert rule == expected, (text, rule)


def test_the_unsupported_messages_each_contain_a_repeat_the_reader_refuses():
    from datetime import datetime

    import diya_repeat

    now = datetime(2026, 10, 10, 10, 15)
    refused = 0
    for text in REPEAT_UNSUPPORTED:
        words = text.split(" to ", 1)[0].replace("Remind me ", "").replace("remind me ", "")
        try:
            diya_repeat.parse_repeat(words, now)
        except diya_repeat.NotUnderstood:
            refused += 1
    assert refused == len(REPEAT_UNSUPPORTED)


# ---- the benchmark's agent ---------------------------------------------------------------------------------

def test_the_benchmark_agent_stubs_what_reaches_outside_and_keeps_reminders_real(tmp_path):
    agent = REAL_BUILD_AGENT("some-model", str(tmp_path))
    assert agent.config.model == "some-model" and agent.config.db_path.startswith(str(tmp_path))
    for name, args, expected in (("web_search", ("x",), "Top result"), ("get_weather", ("x",), "Sunny"), ("search_notes", ("x",), "A note"),
                                 ("list_files", (), "notes.txt")):
        assert expected in agent._functions[name](*args), name
    assert agent._functions["add_reminder"] == agent.add_reminder  # the thing being measured is the real tool
    agent.warm_up()  # builds nothing: the notes index is never used here


# ---- asking one message --------------------------------------------------------------------------------------

def test_a_repeat_that_was_asked_for_is_saved_scored_by_what_was_saved_and_cleared_away(tmp_path):
    agent = scripted(tmp_path, [reminder(content="take out the bins", repeat="every Monday at 9am"), text_reply("Done."),
                                reminder(content="take out the bins", repeat="every Monday at 9am"), text_reply("Done.")])
    result = bench.ask_once(agent, "repeat asked", "Remind me every Monday at 9am to take out the bins", "weekly:0@09:00")
    assert result["series"] == [{"content": "take out the bins", "rule": "weekly:0@09:00", "said": "every Monday at 9am"}]
    assert result["one_offs"] == [] and bench.outcome(result) == "right rule" and bench.tried_to_repeat(result) is True
    assert result["tools"] == ["add_reminder"] and result["answer"] == "Done."
    assert result["attempts"][0]["args"] == {"content": "take out the bins", "repeat": "every Monday at 9am"}
    assert result["attempts"][0]["result"].startswith("Repeating reminder saved: take out the bins.")
    assert agent.schedule.series("all") == [] and agent.store.reminders("all") == [] and agent.schedule.events() == []  # the next one starts clean
    again = bench.ask_once(agent, "repeat asked", "Remind me every Monday at 9am to take out the bins", "weekly:0@09:00")
    assert bench.outcome(again) == "right rule"  # not refused as a copy


def test_the_rule_of_a_days_count_is_compared_without_the_date_it_counts_from(tmp_path):
    agent = scripted(tmp_path, [reminder(content="water the cactus", repeat="every 3 days"), text_reply("ok")])
    result = bench.ask_once(agent, "repeat asked", "Remind me every 3 days to water the cactus", "every:3@09:00")
    assert result["series"][0]["rule"] == "every:3@09:00" and bench.outcome(result) == "right rule"


def test_a_wrong_rule_a_lost_repeat_and_nothing_are_told_apart(tmp_path):
    wrong = scripted(tmp_path, [reminder(content="x", repeat="every day at 8am"), text_reply("ok")])
    assert bench.outcome(bench.ask_once(wrong, "repeat asked", "Remind me every day at 8am to x", "weekdays@08:00")) == "wrong rule"
    (tmp_path / "b").mkdir()
    lost = scripted(tmp_path / "b", [reminder(content="x", due_at="tomorrow at 9am"), text_reply("ok")])
    # a repeat that is part of the request is read from the person's own words whatever the model passed, so a lost repeat needs one that is not
    assert bench.outcome(bench.ask_once(lost, "repeat asked", "Remind me to x tomorrow at 9am, I do it every day at 8am", "daily@08:00")) == "one-off"
    nothing = scripted(tmp_path, [text_reply("Sure.")])
    assert bench.outcome(bench.ask_once(nothing, "repeat asked", "Remind me every day at 8am to x", "daily@08:00")) == "nothing"


def test_a_repeat_made_up_for_a_single_reminder_is_dropped_by_the_guard_and_counted_as_tried_not_kept(tmp_path):
    agent = scripted(tmp_path, [reminder(content="call mum", due_at="tomorrow at 5pm", repeat="every day"), text_reply("ok")])
    result = bench.ask_once(agent, "one-off", "Remind me tomorrow at 5pm to call mum", None)
    assert result["series"] == [] and len(result["one_offs"]) == 1 and bench.outcome(result) == "one-off"
    assert bench.tried_to_repeat(result) is True
    assert "does not repeat" in result["attempts"][0]["result"]


def test_a_series_where_none_was_expected_is_a_series(tmp_path):
    agent = scripted(tmp_path, [reminder(content="stretch", repeat="every day"), text_reply("ok")])
    assert bench.outcome(bench.ask_once(agent, "repeat unsupported", "Remind me every day to stretch", None)) == "series"


def test_a_message_the_model_just_answers_saves_nothing_and_tried_nothing(tmp_path):
    agent = scripted(tmp_path, [text_reply("63.")])
    result = bench.ask_once(agent, "not a reminder", "What's 9 times 7?", None)
    assert bench.outcome(result) == "nothing" and bench.tried_to_repeat(result) is False and result["attempts"] == [] and result["tools"] == []


@pytest.mark.parametrize("args", [{"content": "x"}, {"content": "x", "repeat": ""}, {"content": "x", "repeat": None}])
def test_an_empty_or_missing_repeat_is_not_trying_to_repeat(tmp_path, args):
    agent = scripted(tmp_path, [reminder(**args), text_reply("ok")])
    assert bench.tried_to_repeat(bench.ask_once(agent, "one-off", "Remind me to x", None)) is False


def test_the_reminder_function_is_put_back_after_every_message_even_when_the_model_fails(tmp_path):
    agent = scripted(tmp_path, [text_reply("a")])
    before = agent._functions["add_reminder"]
    bench.ask_once(agent, "one-off", "hello", None)
    assert agent._functions["add_reminder"] is before
    agent.client._chat_error = RuntimeError("Ollama is down")
    with pytest.raises(RuntimeError):
        bench.ask_once(agent, "one-off", "hello", None)
    assert agent._functions["add_reminder"] is before and agent.store.reminders("all") == []


def test_what_the_tool_loop_prints_does_not_reach_the_report(tmp_path, capsys):
    agent = scripted(tmp_path, [reminder(content="x", repeat="every day"), text_reply("ok")])
    bench.ask_once(agent, "repeat asked", "Remind me every day to x", "daily@09:00")
    assert "[tool call]" not in capsys.readouterr().out


# ---- a whole run, and keeping what it measured ------------------------------------------------------------------

def test_a_run_asks_every_message_the_stated_number_of_times_and_a_limit_takes_the_first_few_of_each_category(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: scripted(tmp_path, [text_reply("fine")] * 400))
    full = bench.run_model("m", runs=2, limit=0)
    assert len(full["results"]) == 2 * 53 and full["model"] == "m" and full["runs"] == 2 and isinstance(full["seconds"], int)
    limited = bench.run_model("m", runs=1, limit=2)
    assert [r["category"] for r in limited["results"]] == ["repeat asked"] * 2 + ["repeat unsupported"] * 2 + ["one-off"] * 2 + ["not a reminder"] * 2
    assert limited["results"][0]["text"] == REPEAT_ASKED[0][0]


def test_the_results_file_is_rewritten_after_every_message_so_a_stopped_run_keeps_what_it_measured(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    seen = []
    real = bench.ask_once

    def watching(agent, *args):
        if out.exists():
            seen.append(len(json.loads(out.read_text(encoding="utf-8"))["results"]))
        return real(agent, *args)

    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: scripted(tmp_path, [text_reply("fine")] * 100))
    monkeypatch.setattr(bench, "ask_once", watching)
    bench.run_model("m", runs=1, limit=1, out_path=str(out))
    assert seen == [1, 2, 3]  # before the 2nd, 3rd and 4th message the file already held 1, 2 and 3 of them
    assert len(json.loads(out.read_text(encoding="utf-8"))["results"]) == 4
    assert not (tmp_path / "out.json.part").exists() and b"\r" not in out.read_bytes()


def test_a_run_that_dies_part_way_leaves_the_messages_it_finished(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    agents = scripted(tmp_path, [text_reply("fine"), text_reply("fine")])  # a third call finds the script empty and fails
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: agents)
    with pytest.raises(IndexError):
        bench.run_model("m", runs=1, limit=2, out_path=str(out))
    assert len(json.loads(out.read_text(encoding="utf-8"))["results"]) == 2


# ---- a locked results file, and carrying on after a cut-off run -----------------------------------------------

def test_a_results_file_another_program_has_open_is_tried_again_and_the_swap_goes_through_once_it_lets_go(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    calls = []
    real = bench.os.replace

    def refused_twice(src, dst):
        calls.append(src)
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(bench.os, "replace", refused_twice)
    monkeypatch.setattr(bench.time, "sleep", lambda seconds: None)
    assert bench.write(str(out), {"results": [1]}) is True
    assert len(calls) == 3 and json.loads(out.read_text(encoding="utf-8")) == {"results": [1]} and not (tmp_path / "out.json.part").exists()


def test_a_results_file_that_stays_locked_is_given_up_on_without_an_error_and_the_answers_are_kept_beside_it(tmp_path, monkeypatch):
    out = tmp_path / "out.json"
    pauses, calls = [], []

    def refused(src, dst):
        calls.append(1)
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(bench.os, "replace", refused)
    monkeypatch.setattr(bench.time, "sleep", pauses.append)
    assert bench.write(str(out), {"results": [1, 2]}, tries=4, pause=0.5) is False
    assert len(calls) == 4 and pauses == [0.5, 0.5, 0.5]  # it waits between tries, not after the last
    assert json.loads((tmp_path / "out.json.part").read_text(encoding="utf-8")) == {"results": [1, 2]} and not out.exists()


def test_only_a_refused_swap_is_retried_any_other_failure_is_still_an_error(tmp_path, monkeypatch):
    def gone(src, dst):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(bench.os, "replace", gone)
    with pytest.raises(FileNotFoundError):
        bench.write(str(tmp_path / "out.json"), {"results": []})


def test_a_run_goes_on_when_the_results_file_cannot_be_updated_and_says_so_each_time(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.json"
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: scripted(tmp_path, [text_reply("fine")] * 10))
    monkeypatch.setattr(bench, "write", lambda path, results: False)
    results = bench.run_model("m", runs=1, limit=1, out_path=str(out))
    assert len(results["results"]) == 4  # nothing stopped it
    err = capsys.readouterr().err
    assert err.count("could not update") == 5 and err.count("the answers so far are in ") == 4 and err.count("the complete answers are in ") == 1


def fake_asked(monkeypatch, answered):
    monkeypatch.setattr(bench, "build_agent", lambda model, workdir: object())

    def ask(agent, category, text, expected):
        answered.append(text)
        return {"category": category, "text": text, "expected": expected, "tools": [], "attempts": [], "series": [], "one_offs": [], "answer": ""}

    monkeypatch.setattr(bench, "ask_once", ask)


def saved_run(path, model, runs, count, limit=1, seconds=100):
    asked = bench.messages()
    asked = [m for category in bench.CATEGORIES for m in [x for x in asked if x[0] == category][:limit]]
    order = [m for _ in range(runs) for m in asked][:count]
    body = {"model": model, "runs": runs, "seconds": seconds, "results": [{"category": c, "text": t, "expected": e, "answer": "earlier"} for c, t, e in order]}
    path.write_text(json.dumps(body), encoding="utf-8")


def test_a_cut_off_run_carries_on_after_the_answers_it_saved_and_keeps_them(tmp_path, monkeypatch, capsys):
    out, answered = tmp_path / "out.json", []
    saved_run(out, "m", runs=2, count=5, limit=1, seconds=100)
    fake_asked(monkeypatch, answered)
    results = bench.run_model("m", runs=2, limit=1, out_path=str(out), resume=True)
    assert len(results["results"]) == 8 and [r["answer"] for r in results["results"]] == ["earlier"] * 5 + [""] * 3
    assert answered == [r["text"] for r in results["results"][5:]] and len(answered) == 3  # only the three it had not done
    assert results["seconds"] >= 100  # the time already spent still counts
    assert "resuming after 5 of 8 answers" in capsys.readouterr().err
    assert len(json.loads(out.read_text(encoding="utf-8"))["results"]) == 8


def test_without_resume_a_saved_file_is_not_looked_at_and_everything_is_asked_again(tmp_path, monkeypatch):
    out, answered = tmp_path / "out.json", []
    saved_run(out, "m", runs=1, count=3)
    fake_asked(monkeypatch, answered)
    results = bench.run_model("m", runs=1, limit=1, out_path=str(out))
    assert len(answered) == 4 and all(r["answer"] == "" for r in results["results"])


def test_the_fuller_of_the_file_and_the_part_beside_it_is_what_a_run_carries_on_from(tmp_path):
    out = tmp_path / "out.json"
    saved_run(out, "m", runs=1, count=2)
    saved_run(tmp_path / "out.json.part", "m", runs=1, count=3)  # the swap that would have replaced the first was refused
    assert len(bench.load_checkpoint(str(out), "m", 1)["results"]) == 3
    saved_run(out, "m", runs=1, count=4)
    assert len(bench.load_checkpoint(str(out), "m", 1)["results"]) == 4
    saved_run(out, "m", runs=1, count=3)  # equally full: either will do, and it still reads
    assert len(bench.load_checkpoint(str(out), "m", 1)["results"]) == 3


@pytest.mark.parametrize("model, runs", [("other", 1), ("m", 2)])
def test_answers_from_another_model_or_run_count_are_not_carried_on_from(tmp_path, model, runs):
    out = tmp_path / "out.json"
    saved_run(out, model, runs=runs, count=2)
    assert bench.load_checkpoint(str(out), "m", 1) is None


@pytest.mark.parametrize("text", ["", "not json", "[1, 2]", '{"model": "m", "runs": 1}', '{"model": "m", "runs": 1, "results": "x"}'])
def test_a_results_file_that_cannot_be_used_is_no_checkpoint_not_an_error(tmp_path, text):
    out = tmp_path / "out.json"
    out.write_text(text, encoding="utf-8")
    assert bench.load_checkpoint(str(out), "m", 1) is None
    assert bench.load_checkpoint(str(tmp_path / "missing.json"), "m", 1) is None


@pytest.mark.parametrize("mistake", ["another message", "another category", "too many", "not an answer"])
def test_a_run_starts_again_rather_than_carry_on_after_answers_that_are_not_from_this_list_of_messages(tmp_path, monkeypatch, capsys, mistake):
    out, answered = tmp_path / "out.json", []
    saved_run(out, "m", runs=1, count=3)
    body = json.loads(out.read_text(encoding="utf-8"))
    if mistake == "another message":
        body["results"][1]["text"] = "something else entirely"
    elif mistake == "another category":
        body["results"][2]["category"] = "repeat asked"  # the third one saved was a one-off
    elif mistake == "too many":
        body["results"] = body["results"] * 3
    else:
        body["results"][0] = "oops"
    out.write_text(json.dumps(body), encoding="utf-8")
    fake_asked(monkeypatch, answered)
    results = bench.run_model("m", runs=1, limit=1, out_path=str(out), resume=True)
    assert len(answered) == 4 and len(results["results"]) == 4 and all(r["answer"] == "" for r in results["results"])
    assert "not from this list of messages; starting from the first" in capsys.readouterr().err


def test_a_run_asked_to_resume_with_nothing_saved_starts_from_the_first_and_says_so(tmp_path, monkeypatch, capsys):
    answered = []
    fake_asked(monkeypatch, answered)
    bench.run_model("m", runs=1, limit=1, out_path=str(tmp_path / "none.json"), resume=True)
    assert len(answered) == 4 and "nothing to resume from at" in capsys.readouterr().err


def test_resume_without_a_results_file_to_look_in_is_just_a_run(monkeypatch, capsys):
    answered = []
    fake_asked(monkeypatch, answered)
    bench.run_model("m", runs=1, limit=1, resume=True)
    assert len(answered) == 4 and capsys.readouterr().err == ""


# ---- the report -----------------------------------------------------------------------------------------------

def result(category, text, expected=None, series=(), one_offs=(), attempts=(), answer=""):
    return {"category": category, "text": text, "expected": expected, "tools": ["add_reminder"] if attempts else [], "attempts": [{"args": a, "result": r} for a, r in attempts],
            "series": [{"content": "c", "rule": rule, "said": "s"} for rule in series], "one_offs": [{"content": "c", "due_at": d, "due_ts": None} for d in one_offs], "answer": answer}


SAMPLE = {"model": "m", "runs": 1, "seconds": 106, "results": [
    result("repeat asked", "ask 1", "daily@08:00", ["daily@08:00"], attempts=[({"content": "c", "repeat": "every day at 8am"}, "Repeating reminder saved")]),
    result("repeat asked", "ask 2", "weekly:0@09:00", ["weekly:1@09:00"], attempts=[({"content": "c", "repeat": "every Tuesday"}, "Repeating reminder saved")]),
    result("repeat asked", "ask 3", "daily@09:00", one_offs=["tomorrow"], attempts=[({"content": "c", "due_at": "tomorrow"}, "Reminder saved")]),
    result("repeat asked", "ask 4", "daily@09:00"),
    result("repeat unsupported", "uns 1", None, one_offs=["in an hour"], answer="I will remind you every hour."),
    result("repeat unsupported", "uns 2", None, series=["daily@09:00"]),
    result("repeat unsupported", "uns 3", None),
    result("one-off", "one 1", None, one_offs=["tomorrow"]),
    result("one-off", "one 2", None, series=["daily@09:00"], attempts=[({"content": "c", "repeat": "every day"}, "Repeating reminder saved")]),
    result("one-off", "one 3", None, attempts=[({"content": "c", "repeat": "every day"}, "Not saved: the repeat is not the user's words")]),
    result("not a reminder", "other 1", None),
    result("not a reminder", "other 2", None, one_offs=["x"]),
]}


def report_of(results):
    out = io.StringIO()
    bench.report(results, out)
    return out.getvalue()


def test_the_report_counts_each_kind_of_outcome_for_each_kind_of_message():
    text = report_of(SAMPLE)
    assert "Model m: 12 messages (1 run(s) each), 106 s (8.8 s per message)." in text
    assert ("Asked for a repeating reminder (4): saved with the right rule 1 (25%), with a wrong rule 1, "
            "as a single reminder (the repeat lost) 1, nothing 1") in text
    assert "Asked for a repeat that cannot be read (3): saved as a repeating reminder 1 (should be 0), as a single reminder with the repeat dropped 1, nothing saved 1" in text
    assert "Asked for a single reminder (3): saved as one 1 (33%), saved as a repeating reminder 1 (should be 0), nothing 1" in text
    assert "Not asked for a reminder (2): anything saved 1 (should be 0)" in text


def test_the_report_lists_each_message_that_went_wrong_and_what_was_saved_for_it():
    text = report_of(SAMPLE)
    assert "wrong rule 'ask 2'  saved=['weekly:1@09:00']" in text
    assert "one-off    'ask 3'  saved=['tomorrow']" in text
    assert "nothing    'ask 4'" in text and "right rule 'ask 1'" not in text
    assert "series    'uns 2'  saved=['daily@09:00']" in text and "one-off   'uns 1'  saved=['in an hour']" in text and "'uns 3'" not in text
    assert "series 'one 2' -> ['daily@09:00']" in text and "'one 1'" not in text
    assert "saved 'other 2'" in text and "'other 1'" not in text


def test_the_report_counts_a_repeat_the_model_tried_when_the_message_had_none_and_how_many_were_kept():
    text = report_of(SAMPLE)
    assert "Passed a repeat when the message had none (5 messages): the model tried 2 times, and 1 of those were kept as a repeating reminder" in text
    assert "'one 2' -> repeat=['every day']  kept=True" in text and "'one 3' -> repeat=['every day']  kept=False" in text


def test_the_report_notices_a_single_reminder_whose_answer_sounds_as_if_it_repeats():
    assert "of the single reminders, 1 had an answer that sounds as if it repeats" in report_of(SAMPLE)
    quiet = dict(SAMPLE, results=[r for r in SAMPLE["results"] if r["text"] != "uns 1"])
    assert "sounds as if it repeats" not in report_of(quiet)


def test_percent_of_nothing_is_not_a_number():
    assert bench.percent(1, 4) == "25%" and bench.percent(0, 5) == "0%" and bench.percent(5, 5) == "100%" and bench.percent(0, 0) == "n/a"


# ---- the command line -------------------------------------------------------------------------------------------

def test_a_run_prints_its_report_and_saves_every_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, out_path=None, resume=False: dict(SAMPLE, model=model, runs=runs))
    out = io.StringIO()
    assert bench.main(["--model", "qwen3:4b-instruct", "--runs", "2"], out=out) == 0
    assert "Model qwen3:4b-instruct:" in out.getvalue()


def test_the_default_model_is_the_configured_one_and_the_options_reach_the_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, out_path=None, resume=False: seen.update(model=model, runs=runs, limit=limit, out=out_path, resume=resume) or SAMPLE)
    bench.main([], out=io.StringIO())
    assert seen == {"model": "qwen2.5:3b", "runs": 1, "limit": 0, "out": None, "resume": False}
    bench.main(["--runs", "3", "--limit", "4", "--out", "x.json", "--resume"], out=io.StringIO())
    assert seen == {"model": "qwen2.5:3b", "runs": 3, "limit": 4, "out": "x.json", "resume": True}


@pytest.mark.parametrize("runs, expected", [("0", 1), ("-3", 1), ("4", 4)])
def test_a_run_count_below_one_is_one(monkeypatch, runs, expected):
    seen = {}
    monkeypatch.setattr(bench, "run_model", lambda model, runs, limit, out_path=None, resume=False: seen.update(runs=runs) or SAMPLE)
    bench.main(["--runs", runs], out=io.StringIO())
    assert seen["runs"] == expected


def test_a_model_that_cannot_be_reached_is_a_clean_failure_not_a_traceback(monkeypatch, capsys):
    def down(model, runs, limit, out_path=None, resume=False):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(bench, "run_model", down)
    assert bench.main([], out=io.StringIO()) == 2
    assert "could not run against qwen2.5:3b: connection refused" in capsys.readouterr().err


# ---- what the mutation run found nothing checking ----------------------------------------------------------------------

def test_a_locked_results_file_is_tried_five_times_a_fifth_of_a_second_apart_unless_told_otherwise(tmp_path, monkeypatch):
    pauses, calls = [], []

    def refused(src, dst):
        calls.append(1)
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(bench.os, "replace", refused)
    monkeypatch.setattr(bench.time, "sleep", pauses.append)
    assert bench.write(str(tmp_path / "out.json"), {"results": []}) is False
    assert len(calls) == 5 and pauses == [0.2, 0.2, 0.2, 0.2]


def test_a_run_can_only_carry_on_after_answers_that_are_a_prefix_of_what_it_would_ask():
    order = [("a", "first", None), ("b", "second", None)]
    answers = [{"category": "a", "text": "first"}, {"category": "b", "text": "second"}]
    assert bench.continues([], order) is True and bench.continues(answers[:1], order) is True and bench.continues(answers, order) is True
    assert bench.continues(answers + [{"category": "b", "text": "second"}], order) is False  # more answers than messages, the first ones matching
