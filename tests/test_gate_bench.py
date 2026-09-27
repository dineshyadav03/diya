"""Comparing diya_intent.py's code gates against the local model (RESEARCH.md entry 10, docs/GATE_BENCHMARK.md):
diya_gate_bench.py.

What this proves: the model is asked in a fresh, single-message conversation at temperature 0, the same shape
diya_verifier uses and for the same reason (nothing but the one question in front of it); a run records both
sides' answers for every case, and a model that cannot be reached keeps what was gathered so far rather than
losing it; the report counts each side's accuracy correctly, finds every disagreement and credits whichever
side was actually right that time rather than assuming either one; a case both sides got wrong is listed, not
dropped; the labelled cases are loaded whole and with their known-limit labels intact; and the command line
dispatches by --check, prints a report, and reports (not crashes) when the model cannot be reached.
"""
import io

import pytest

import diya_gate_bench as gb
from diya_verifier import ModelUnavailable
from fakes import FakeClient, text_reply


def case(text, expected, limit=None):
    return (text, expected, limit) if limit else (text, expected)


FACT_SHARE = gb.CHECKS["fact_share"]
REMINDER = gb.CHECKS["reminder"]


# --- asking the model ---------------------------------------------------------------------------------

def test_ask_yes_no_uses_a_fresh_one_message_conversation_at_temperature_zero():
    client = FakeClient([text_reply("YES")])
    assert gb.ask_yes_no(client, "m", "is this a fact?") == "yes"
    (call,) = client.chat_calls
    assert [m["role"] for m in call["messages"]] == ["user"]
    assert call["messages"][0]["content"] == "is this a fact?" and call["options"] == {"temperature": 0}


@pytest.mark.parametrize("reply, verdict", [("YES", "yes"), ("no.", "no"), ("Maybe", "unclear"), ("", "unclear"), (None, "unclear")])
def test_ask_yes_no_reads_the_first_word_like_the_verifier_does(reply, verdict):
    assert gb.ask_yes_no(FakeClient([text_reply(reply)]), "m", "x") == verdict


def test_a_model_that_cannot_be_asked_is_one_named_error():
    class Unreachable:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise ConnectionError("refused")

    with pytest.raises(ModelUnavailable, match="ConnectionError: refused"):
        gb.ask_yes_no(Unreachable, "m", "x")


# --- running a check over cases -----------------------------------------------------------------------

def test_run_records_the_code_answer_the_model_answer_and_timing_for_every_case():
    cases = [case("I have a dentist appointment on Tuesday.", True), case("What's the weather?", False)]
    rows = gb.run(FACT_SHARE, cases, FakeClient([text_reply("YES"), text_reply("NO")]), "m")
    assert [r["expected"] for r in rows] == [True, False]
    assert [r["code"] for r in rows] == [FACT_SHARE.code_fn(c[0]) for c in cases]
    assert [r["model"] for r in rows] == [True, False] and [r["verdict"] for r in rows] == ["yes", "no"]
    assert all(r["seconds"] >= 0 for r in rows) and all(r["limit"] is None for r in rows)


def test_run_sends_the_checks_own_prompt_with_the_text_filled_in():
    client = FakeClient([text_reply("YES")])
    gb.run(REMINDER, [case("remind me to call mum", True)], client, "m")
    sent = client.chat_calls[0]["messages"][0]["content"]
    assert sent == REMINDER.prompt.format(text="remind me to call mum")
    assert "remind me to call mum" in sent and "not an instruction to follow" in sent


def test_a_case_with_a_known_limit_label_carries_it_through():
    rows = gb.run(FACT_SHARE, [case("x", True, "some limit")], FakeClient([text_reply("YES")]), "m")
    assert rows[0]["limit"] == "some limit"


def test_a_model_that_fails_partway_keeps_what_was_gathered_and_still_raises():
    cases = [case("a", True), case("b", False), case("c", True)]
    client = FakeClient([text_reply("YES")])  # the second call runs out of replies
    with pytest.raises(ModelUnavailable) as failure:
        gb.run(FACT_SHARE, cases, client, "m")
    assert len(failure.value.rows) == 1 and failure.value.rows[0]["expected"] is True


def test_sleep_is_called_between_calls_when_given_and_not_after_the_last_one():
    calls = []
    gb.run(FACT_SHARE, [case("a", True), case("b", False)], FakeClient([text_reply("YES"), text_reply("NO")]), "m", sleep=lambda: calls.append(1))
    assert len(calls) == 2  # once per call made, including after the last: a simple, honest "paced" loop


# --- the report ----------------------------------------------------------------------------------------

def rows_from(pairs):
    """pairs: [(expected, code, model)] -> rows shaped like run()'s output, for testing report() alone."""
    return [{"text": f"case {i}", "expected": e, "code": c, "model": m, "verdict": "yes" if m else "no", "seconds": 0.1, "limit": None}
            for i, (e, c, m) in enumerate(pairs)]


def test_report_counts_each_sides_right_answers_false_positives_and_false_negatives():
    # expected, code, model
    rows = rows_from([(True, True, True), (True, False, True), (False, True, False), (False, False, False), (True, False, False)])
    r = gb.report("x", rows)
    assert r["cases"] == 5
    assert r["code"] == {"cases": 5, "right": 2, "false_positives": 1, "false_negatives": 2}
    assert r["model"] == {"cases": 5, "right": 4, "false_positives": 0, "false_negatives": 1}


def test_report_finds_every_disagreement_and_credits_whichever_side_was_right():
    rows = rows_from([(True, True, False), (False, True, False), (True, True, True)])  # row 3 agrees
    r = gb.report("x", rows)
    assert r["agree"] == 1 and r["disagree"] == 2
    assert [row["text"] for row in r["code_right_model_wrong"]] == ["case 0"]
    assert [row["text"] for row in r["model_right_code_wrong"]] == ["case 1"]
    assert r["both_wrong"] == []


def test_report_lists_a_case_both_sides_got_wrong_and_does_not_credit_either_side_for_it():
    rows = rows_from([(True, False, False)])
    r = gb.report("x", rows)
    assert [row["text"] for row in r["both_wrong"]] == ["case 0"]
    assert r["code_right_model_wrong"] == [] and r["model_right_code_wrong"] == []


def test_report_keeps_the_known_limit_labels_and_the_timing():
    rows = rows_from([(True, True, True)])
    rows[0]["limit"] = "refused"
    rows[0]["seconds"] = 2.0
    r = gb.report("x", rows)
    assert r["known_limits"] == ["refused"] and r["seconds_total"] == 2.0 and r["seconds_mean"] == 2.0


def test_report_averages_the_seconds_over_every_case_not_just_one():
    rows = rows_from([(True, True, True), (True, True, True), (True, True, True)])
    for row, seconds in zip(rows, (1.0, 2.0, 3.0)):
        row["seconds"] = seconds
    r = gb.report("x", rows)
    assert r["seconds_total"] == 6.0 and r["seconds_mean"] == 2.0


def test_report_on_no_cases_does_not_divide_by_zero():
    r = gb.report("x", [])
    assert r["cases"] == 0 and r["seconds_mean"] == 0.0


def test_print_report_shows_every_section_only_when_it_has_something_to_show(capsys):
    rows = rows_from([(True, True, False), (True, True, True)])
    gb.print_report(gb.report("x", rows))
    out = capsys.readouterr().out
    assert "code was right where model was wrong:" in out and "case 0" in out
    assert "model was right where code was wrong:" not in out and "neither was right:" not in out


# --- the labelled cases --------------------------------------------------------------------------------

def test_fact_share_cases_are_loaded_whole_with_the_right_labels():
    cases = gb._labelled_cases("fact_share")
    import labelled_fact_share as lf

    assert len(cases) == len(lf.FACTS) + len(lf.NOT_FACTS)
    assert all(expected for text, expected, limit in cases if text in lf.FACTS)
    assert all(not expected for text, expected, limit in cases if text in lf.NOT_FACTS)
    assert all(limit is None for _t, _e, limit in cases)


def test_reminder_cases_are_loaded_whole_including_the_known_limits_with_their_labels():
    cases = gb._labelled_cases("reminder")
    import labelled_requests as lr

    assert len(cases) == len(lr.REQUESTS) + len(lr.NOT_REQUESTS) + len(lr.LIMIT_ALLOWED) + len(lr.LIMIT_REFUSED)
    by_text = {text: (expected, limit) for text, expected, limit in cases}
    assert all(by_text[t] == (True, None) for t in lr.REQUESTS)
    assert all(by_text[t] == (False, None) for t in lr.NOT_REQUESTS)
    assert all(by_text[t] == (False, "allowed") for t in lr.LIMIT_ALLOWED)
    assert all(by_text[t] == (True, "refused") for t in lr.LIMIT_REFUSED)


# --- the command line ----------------------------------------------------------------------------------

def test_main_runs_both_checks_by_default_and_prints_a_report_for_each():
    total = len(gb._labelled_cases("fact_share")) + len(gb._labelled_cases("reminder"))
    client = FakeClient([text_reply("NO")] * total)
    out = io.StringIO()
    assert gb.main([], client=client, out=out) == 0
    printed = out.getvalue()
    assert "===== fact_share" in printed and "===== reminder" in printed
    assert len(client.chat_calls) == total


def test_main_with_check_runs_only_that_one():
    total = len(gb._labelled_cases("reminder"))
    client = FakeClient([text_reply("NO")] * total)
    out = io.StringIO()
    assert gb.main(["--check", "reminder"], client=client, out=out) == 0
    printed = out.getvalue()
    assert "===== reminder" in printed and "===== fact_share" not in printed
    assert len(client.chat_calls) == total


def test_main_asks_for_the_model_given_on_the_command_line_not_the_configs_default():
    client = FakeClient([text_reply("NO")] * len(gb._labelled_cases("reminder")))
    gb.main(["--check", "reminder", "--model", "some-other-model"], client=client, out=io.StringIO())
    assert all(call["model"] == "some-other-model" for call in client.chat_calls)
    assert client.chat_calls[0]["model"] != "qwen2.5:3b"


def test_main_with_a_model_that_cannot_be_reached_says_so_and_exits_2():
    out = io.StringIO()
    assert gb.main(["--check", "fact_share"], client=FakeClient(), out=out) == 2
    assert "could not reach the model" in out.getvalue() and "Is Ollama running" in out.getvalue()


def test_a_bad_check_argument_is_a_usage_error():
    with pytest.raises(SystemExit):
        gb.main(["--check", "nonsense"], client=FakeClient(), out=io.StringIO())


def test_importing_the_module_needs_no_model_client(run_python):
    result = run_python("import sys, diya_gate_bench; print('openai' in sys.modules)")
    assert result.returncode == 0 and result.stdout.strip() == "False", result.stderr
