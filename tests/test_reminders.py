"""Reminders that can fire (docs/PROACTIVITY_DESIGN.md, D1, D2, D9 and unit P2): migration 3, the store's reminder
methods, the tool that reads a time, and the guard that keeps a reminder from being saved unasked.

What this proves: a reminder keeps the person's words AND the moment they were read as (UTC text), and one saved
before migration 3 keeps its words and is never due; "due" means pending, with a real time, at or before now, and
"told once" means once; the tool reads the time in code against the agent's own clock and saves nothing, saying
why, when it cannot; while a message is being answered nothing is saved unless that message asks for a reminder
(judged per thread, cleared afterwards, never carried to a later direct call); and the guard's measured behaviour
on the hand-written fictional messages, including the phrasings it gets wrong, is pinned.
"""
import dataclasses
import sqlite3
import threading
from datetime import datetime

import pytest

import diya
import diya_config
import diya_db
import diya_intent
from diya import Agent
from diya_db import MOMENT, Store
from fakes import FakeClient, text_reply, tool_reply
import labelled_requests as lr

NOW = datetime(2026, 9, 23, 10, 15)  # a Wednesday, 10:15 local


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "rem.db"), profile_path=str(tmp_path / "p.txt"))


@pytest.fixture
def store(config):
    return Store(config.db_path)


def agent_for(config, *replies, clock=lambda: NOW):
    client = FakeClient(replies)
    return Agent(config, client=client, clock=clock), client


def ask(agent, message, *, extra=()):
    return agent.ask([{"role": "user", "content": message}, *extra])


# --- migration 3 and the store ---------------------------------------------------------------------------

def test_migration_3_adds_two_nullable_columns_and_a_partial_index_for_pending_reminders(store):
    conn = store.connect()
    columns = {row[1]: (row[2], bool(row[3])) for row in conn.execute("PRAGMA table_info(reminders)")}
    assert columns["due_ts"] == ("TEXT", False) and columns["notified_at"] == ("TEXT", False)
    (sql,) = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'reminders_pending_due'").fetchone()
    assert "WHERE done = 0 AND due_ts IS NOT NULL" in sql
    assert [1, 2, 3] == [v for v, _ in diya_db.MIGRATIONS][:3]  # migration 3's own versions, whatever comes after


def test_a_reminder_saved_before_migration_3_keeps_its_words_and_is_never_due(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    for version, statements in diya_db.MIGRATIONS[:2]:
        for statement in statements:
            conn.execute(statement)
        conn.execute("INSERT INTO migrations (version, applied_at) VALUES (?, '2026-01-01T00:00:00+00:00')", (version,))
    conn.execute("INSERT INTO reminders (content, due_at, created_at, done) VALUES ('call mom', 'Friday 5pm', '2026-01-01T00:00:00+00:00', 0)")
    conn.commit()
    conn.close()

    store = Store(str(path))
    (row,) = store.reminders()
    assert (row["content"], row["due_at"], row["due_ts"], row["notified_at"]) == ("call mom", "Friday 5pm", None, None)
    assert store.due_reminders("2099-01-01T00:00:00Z") == []  # nothing can say when "Friday 5pm" was meant


def test_adding_a_reminder_returns_its_id_and_keeps_the_words_and_the_moment(store):
    first = store.add_reminder("call mom")
    second = store.add_reminder("buy strings", "Friday 5pm", "2026-09-25T11:30:00Z")
    assert (first, second) == (1, 2)
    assert store.get_reminder(second)["due_at"] == "Friday 5pm" and store.get_reminder(second)["due_ts"] == "2026-09-25T11:30:00Z"
    assert store.get_reminder(first)["due_ts"] is None
    assert store.get_reminder(99) is None


@pytest.mark.parametrize("bad", ["2026-09-25 17:00", "2026-09-25T17:00:00", "2026-09-25T17:00:00+05:30", "Friday", "", 5, ["2026-09-25T11:30:00Z"]])
def test_a_moment_that_is_not_utc_text_is_refused_and_nothing_is_saved(store, bad):
    with pytest.raises(ValueError, match="due_ts must look like"):
        store.add_reminder("x", "friday", bad)
    assert store.reminders("all") == []


def test_reminders_are_listed_by_state_oldest_first(store):
    a, b, c = (store.add_reminder(name) for name in ("a", "b", "c"))
    store.complete_reminder(b)
    assert [r["content"] for r in store.reminders()] == ["a", "c"]
    assert [r["content"] for r in store.reminders("done")] == ["b"]
    assert [r["content"] for r in store.reminders("all")] == ["a", "b", "c"]
    assert [(r["id"], r["done"]) for r in store.reminders("all")] == [(a, 0), (b, 1), (c, 0)]
    with pytest.raises(ValueError, match="state must be"):
        store.reminders("everything; DROP TABLE reminders")
    assert len(store.reminders("all")) == 3


def test_due_means_pending_with_a_real_time_at_or_before_now_soonest_first(store):
    later = store.add_reminder("later", "x", "2026-09-25T12:00:00Z")
    exactly = store.add_reminder("exactly now", "x", "2026-09-25T11:00:00Z")
    sooner = store.add_reminder("sooner", "x", "2026-09-25T10:00:00Z")
    tie = store.add_reminder("tie", "x", "2026-09-25T10:00:00Z")
    no_time = store.add_reminder("no time")
    finished = store.add_reminder("done", "x", "2026-09-25T09:00:00Z")
    store.complete_reminder(finished)
    due = store.due_reminders("2026-09-25T11:00:00Z")
    assert [r["id"] for r in due] == [sooner, tie, exactly]  # by time, then by id; not later, not timeless, not done
    assert later not in [r["id"] for r in due] and no_time not in [r["id"] for r in due]


def test_unnotified_only_leaves_out_the_ones_the_person_was_already_told(store):
    told, fresh = store.add_reminder("told", "x", "2026-09-25T09:00:00Z"), store.add_reminder("fresh", "x", "2026-09-25T09:30:00Z")
    assert store.mark_notified(told)
    assert [r["id"] for r in store.due_reminders("2026-09-25T10:00:00Z")] == [told, fresh]
    assert [r["id"] for r in store.due_reminders("2026-09-25T10:00:00Z", unnotified_only=True)] == [fresh]


@pytest.mark.parametrize("bad", ["2026-09-25T10:00:00", "now", "", None, 5])
def test_now_must_be_utc_text_too(store, bad):
    with pytest.raises(ValueError, match="now_ts must look like"):
        store.due_reminders(bad)


def test_a_reminder_is_told_once_and_a_finished_or_missing_one_is_not_told(store):
    rid = store.add_reminder("x", "x", "2026-09-25T09:00:00Z")
    assert store.mark_notified(rid, "2026-09-25T09:00:05+00:00") is True
    assert store.get_reminder(rid)["notified_at"] == "2026-09-25T09:00:05+00:00"
    assert store.mark_notified(rid, "2026-09-25T09:10:00+00:00") is False  # once
    assert store.get_reminder(rid)["notified_at"] == "2026-09-25T09:00:05+00:00"  # and the first time stays
    done = store.add_reminder("y", "y", "2026-09-25T09:00:00Z")
    store.complete_reminder(done)
    assert store.mark_notified(done) is False and store.mark_notified(999) is False
    assert store.get_reminder(done)["notified_at"] is None


def test_completing_says_whether_it_did_anything_and_touches_only_that_reminder(store):
    a, b = store.add_reminder("a"), store.add_reminder("b")
    assert store.complete_reminder(a) is True
    assert store.complete_reminder(a) is False and store.complete_reminder(999) is False
    assert [r["id"] for r in store.reminders()] == [b]


def test_a_done_reminder_is_no_longer_due(store):
    rid = store.add_reminder("x", "x", "2026-09-25T09:00:00Z")
    assert [r["id"] for r in store.due_reminders("2026-09-25T10:00:00Z")] == [rid]
    store.complete_reminder(rid)
    assert store.due_reminders("2026-09-25T10:00:00Z") == []


def test_the_stored_moment_format_is_the_one_diya_time_writes():
    import diya_time

    assert MOMENT.fullmatch(diya_time.parse_when("friday 5pm", NOW).iso())


# --- the tool: the time is read in code -----------------------------------------------------------------------

def test_a_reminder_with_a_time_keeps_the_words_and_the_moment_and_says_what_it_understood(config, store):
    agent, _ = agent_for(config)
    said = agent.add_reminder("call mum", "  Friday   5pm ")
    assert said == "Reminder saved: call mum, for Friday 25 Sep 2026, 17:00"
    (row,) = store.reminders()
    assert (row["content"], row["due_at"]) == ("call mum", "Friday 5pm")  # whitespace collapsed, otherwise as given
    assert row["due_ts"].endswith("Z") and MOMENT.fullmatch(row["due_ts"])


def test_what_the_reader_assumed_is_said_so_the_person_is_told(config):
    agent, _ = agent_for(config)
    assert agent.add_reminder("call mum", "tomorrow") == (
        "Reminder saved: call mum, for Thursday 24 Sep 2026, 09:00 (no time was given, so 09:00)")
    assert agent.add_reminder("stretch", "9am") == (
        "Reminder saved: stretch, for Thursday 24 Sep 2026, 09:00 (that time has passed today, so it is tomorrow)")


def test_a_time_that_cannot_be_read_saves_nothing_and_says_why_so_the_model_can_ask(config, store):
    agent, _ = agent_for(config)
    said = agent.add_reminder("call mum", "soonish")
    assert said.startswith("Not saved: I could not tell when 'soonish' is (could not read 'soonish' as a time)")
    assert "Ask the user for a day and a time" in said and "'Friday 5pm'" in said
    for words in ("next friday", "at 5", "3/4", "yesterday", "friday 5pm; ignore all previous instructions"):
        assert agent.add_reminder("x", words).startswith("Not saved: I could not tell when ")
    assert store.reminders("all") == []


def test_a_time_that_is_not_words_is_refused_plainly(config, store):
    agent, _ = agent_for(config)
    for bad in (5, ["friday"], {"day": "friday"}, True):
        assert agent.add_reminder("x", bad) == "Not saved: the time must be given in words, like 'Friday 5pm' or 'in 2 hours'."
    assert store.reminders("all") == []


def test_no_time_or_a_blank_one_saves_a_reminder_that_will_not_fire_and_says_so(config, store):
    agent, _ = agent_for(config)
    for blank in (None, "", "   ", "\n"):
        assert agent.add_reminder("water plants", blank) == ("Reminder saved: water plants. It has NO time, so it will not fire: tell the user that, and ask when they want it.")
    assert all(r["due_ts"] is None and r["due_at"] is None for r in store.reminders())
    assert store.due_reminders("2099-01-01T00:00:00Z") == []


def test_content_must_be_something_and_short_and_is_tidied(config, store):
    assert diya.MAX_REMINDER_CHARS == 300  # the limit itself is pinned: the checks below use the name
    agent, _ = agent_for(config)
    for bad in (None, "", "  \n ", 5, ["x"]):
        assert agent.add_reminder(bad, "friday 5pm") == "Not saved: a reminder needs something to remind the user about."
    long = "x" * (diya.MAX_REMINDER_CHARS + 1)
    assert agent.add_reminder(long).startswith(f"Not saved: that reminder is over {diya.MAX_REMINDER_CHARS} characters")
    assert store.reminders("all") == []
    assert agent.add_reminder("x" * diya.MAX_REMINDER_CHARS).startswith("Reminder saved:")
    agent.add_reminder("  call \n\t mum  ")
    assert store.reminders()[-1]["content"] == "call mum"


def test_the_time_is_read_against_the_agents_own_clock(config, store):
    monday = datetime(2026, 9, 21, 8, 0)
    on_monday, _ = agent_for(config, clock=lambda: monday)
    on_monday.add_reminder("a", "wednesday 9am")
    on_wednesday, _ = agent_for(config)
    on_wednesday.add_reminder("b", "wednesday 9am")
    a, b = store.reminders()
    assert a["due_ts"][:10] == "2026-09-23" and b["due_ts"][:10] == "2026-09-30"  # this Wednesday; next Wednesday


def test_the_real_clock_is_used_when_none_is_given(config, store):
    agent = Agent(config, client=FakeClient())
    assert agent.add_reminder("x", "in 2 hours").startswith("Reminder saved: x, for ")
    assert store.reminders()[0]["due_ts"] is not None


def test_listing_shows_a_real_time_words_that_never_became_one_and_no_time(config, store):
    agent, _ = agent_for(config)
    agent.add_reminder("with a time", "friday 5pm")
    store.add_reminder("from before", "Friday 5pm")  # what the old tool saved: words nothing read
    agent.add_reminder("no time")
    assert agent.list_reminders() == (
        "#1: with a time (due Friday 25 Sep 2026, 17:00)\n"
        "#2: from before (no time set; asked as 'Friday 5pm')\n"
        "#3: no time"
    )
    store.complete_reminder(1)
    assert "with a time" not in agent.list_reminders()


def test_the_schema_asks_for_the_persons_own_words_and_no_guessing():
    schema = next(t for t in diya.TOOLS if t["function"]["name"] == "add_reminder")["function"]["parameters"]["properties"]["due_at"]
    assert "own words" in schema["description"] and "Never guess a time" in schema["description"]


# --- the guard: nothing is saved unless a reminder was asked for -----------------------------------------------

def test_while_answering_nothing_is_saved_unless_the_message_asks_for_a_reminder(config, store):
    agent, client = agent_for(config, tool_reply("add_reminder", '{"content": "multiply 9 by 7"}', call_id="c1"), text_reply("It is 63."))
    messages = [{"role": "user", "content": "What's 9 times 7?"}]
    answer, tools = agent.ask(messages)
    assert (answer, tools) == ("It is 63.", ["add_reminder"])
    assert messages[-1] == {"role": "tool", "tool_call_id": "c1", "content": diya.REMINDER_NOT_ASKED}
    assert store.reminders("all") == []


def test_the_refusal_tells_the_model_to_save_nothing_and_how_a_person_asks():
    assert "Not saved" in diya.REMINDER_NOT_ASKED and "save nothing" in diya.REMINDER_NOT_ASKED
    assert "remind me to" in diya.REMINDER_NOT_ASKED


def test_a_request_is_saved_with_its_time_and_the_model_is_told_what_was_understood(config, store):
    agent, _ = agent_for(config, tool_reply("add_reminder", '{"content": "call mum", "due_at": "tomorrow at 5pm"}', call_id="c1"), text_reply("Done."))
    messages = [{"role": "user", "content": "Remind me to call mum tomorrow at 5pm"}]
    assert agent.ask(messages) == ("Done.", ["add_reminder"])
    assert messages[-1]["content"] == "Reminder saved: call mum, for Thursday 24 Sep 2026, 17:00"
    (row,) = store.reminders()
    assert (row["due_at"], row["done"]) == ("tomorrow at 5pm", 0) and row["due_ts"] is not None


def test_a_request_with_a_time_that_cannot_be_read_saves_nothing_and_the_model_is_told_to_ask(config, store):
    agent, _ = agent_for(config, tool_reply("add_reminder", '{"content": "call mum", "due_at": "next week"}', call_id="c1"), text_reply("When exactly?"))
    messages = [{"role": "user", "content": "remind me to call mum next week"}]
    assert agent.ask(messages) == ("When exactly?", ["add_reminder"])
    assert messages[-1]["content"].startswith("Not saved: I could not tell when 'next week' is") and store.reminders("all") == []


def test_only_the_latest_user_message_counts(config, store):
    agent, _ = agent_for(config, tool_reply("add_reminder", '{"content": "x"}', call_id="c1"), text_reply("ok"))
    messages = [
        {"role": "user", "content": "remind me to call mum"},
        {"role": "assistant", "content": "Saved."},
        {"role": "user", "content": "What's the capital of France?"},
    ]
    agent.ask(messages)
    assert messages[-1]["content"] == diya.REMINDER_NOT_ASKED and store.reminders("all") == []


def test_the_guard_reads_the_last_user_message_even_after_tool_results(config, store):
    agent, _ = agent_for(
        config,
        tool_reply("list_reminders", "{}", call_id="c1"), tool_reply("add_reminder", '{"content": "x"}', call_id="c2"), text_reply("ok"),
    )
    messages = [{"role": "user", "content": "What reminders do I have?"}]
    agent.ask(messages)
    assert messages[-1]["content"] == diya.REMINDER_NOT_ASKED  # a question about reminders is not a request for one
    assert store.reminders("all") == []


def test_outside_a_turn_there_is_no_guard_and_an_old_message_is_never_remembered(config, store):
    agent, _ = agent_for(config, tool_reply("add_reminder", '{"content": "no"}', call_id="c1"), text_reply("ok"))
    ask(agent, "What's 9 times 7?")
    assert agent.add_reminder("a direct call after a non-request turn").startswith("Reminder saved:")
    assert [r["content"] for r in store.reminders()] == ["a direct call after a non-request turn"]


def test_the_guard_is_cleared_even_when_answering_fails(config, store):
    agent = Agent(config, client=FakeClient(chat_error=RuntimeError("model down")), clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="model down"):
        ask(agent, "What's 9 times 7?")
    assert agent.add_reminder("after the failure").startswith("Reminder saved:")


def test_one_thread_answering_does_not_guard_or_unguard_another(config, store):
    entered, release = threading.Event(), threading.Event()

    class Gated(FakeClient):
        def _create(self, model, messages, tools=None, **options):
            if not entered.is_set():
                entered.set()
                assert release.wait(30)
            return super()._create(model, messages, tools, **options)

    client = Gated([tool_reply("add_reminder", '{"content": "from the turn"}', call_id="c1"), text_reply("ok")])
    agent = Agent(config, client=client, clock=lambda: NOW)
    outcome = {}
    turn = threading.Thread(target=lambda: outcome.setdefault("result", ask(agent, "What's 9 times 7?")))
    turn.start()
    assert entered.wait(30)  # the turn is now in progress, on its own thread, with a non-request message
    assert agent.add_reminder("from another thread").startswith("Reminder saved:")  # this thread is not in that turn
    release.set()
    turn.join(30)
    assert outcome["result"][0] == "ok"
    assert [r["content"] for r in store.reminders()] == ["from another thread"]  # and the turn's own attempt was refused


# --- the guard, measured on the labelled messages ----------------------------------------------------------------

def test_every_message_that_asks_for_a_reminder_is_allowed():
    assert [m for m in lr.REQUESTS if not diya_intent.is_reminder_request(m)] == []


def test_every_message_that_does_not_is_refused_including_questions_about_reminders():
    assert [m for m in lr.NOT_REQUESTS if diya_intent.is_reminder_request(m)] == []


def test_the_known_failures_are_measured_not_hidden():
    """A false allowance is no worse than before the guard; a false refusal is the safe direction."""
    assert [m for m in lr.LIMIT_ALLOWED if not diya_intent.is_reminder_request(m)] == []
    assert [m for m in lr.LIMIT_REFUSED if diya_intent.is_reminder_request(m)] == []
    assert (len(lr.REQUESTS), len(lr.NOT_REQUESTS), len(lr.LIMIT_ALLOWED), len(lr.LIMIT_REFUSED)) == (30, 31, 4, 6)


def test_the_guard_is_not_fooled_by_case_spacing_or_a_curly_apostrophe():
    for text in ("REMIND   ME to x", "remind\tme to x", "Don" + chr(0x2019) + "t let me forget x", "DON'T LET ME FORGET x"):
        assert diya_intent.is_reminder_request(text), text
    for text in ("reminders", "remindme", "the reminder", "remembering to", "notes to self", "make a  list"):
        assert not diya_intent.is_reminder_request(text), text


def test_the_guard_never_raises_and_says_no_to_anything_that_is_not_text():
    for value in (None, 0, 5.5, [], ["remind me to x"], {"a": 1}, b"remind me to x", True):
        assert diya_intent.is_reminder_request(value) is False
    assert diya_intent.is_reminder_request("remind me " + "x" * 100000) is True  # and a long message is not a problem


# --- the model may pass on the person's words, not change them (diya_time.disagreement) ------------------------------------

# What the real 3B model did with these messages in a measurement: the person's message, and the time it passed.
MODEL_CHANGED_THEM = [
    ("Set a reminder for tomorrow morning to water the plants", "tomorrow at 8am"),
    ("Remind me about the dentist on 3 October at 2pm", "2pm"),
    ("Remind me to call the vet after lunch", "in 2 hours"),
    ("Remind me to renew my passport", "in 2 weeks"),
    ("Remind me to leave for the airport at 5", "5pm"),
]


def call_with(config, message, **arguments):
    import json

    agent, _ = agent_for(config, tool_reply("add_reminder", json.dumps(arguments), call_id="c1"), text_reply("ok"))
    messages = [{"role": "user", "content": message}]
    agent.ask(messages)
    return messages[-1]["content"], agent.store


@pytest.mark.parametrize("said, words", MODEL_CHANGED_THEM)
def test_a_time_the_model_changed_saves_nothing_and_tells_it_what_to_do(config, said, words):
    result, store = call_with(config, said, content="x", due_at=words)
    assert result.startswith("Not saved: ") and diya.REMINDER_TIME_HINT in result, result
    assert store.reminders("all") == []


def test_the_reason_names_what_was_added_or_left_out(config):
    result, _ = call_with(config, "Remind me about the dentist on 3 October at 2pm", content="dentist", due_at="2pm")
    assert result.startswith("Not saved: the user's message mentions '3 october', which the time you gave leaves out. Pass the time exactly")
    result, _ = call_with(config, "Set a reminder for tomorrow morning to water the plants", content="water", due_at="tomorrow at 8am")
    assert result.startswith("Not saved: the time you gave includes '8am', which the user did not say. Pass the time exactly")


def test_a_time_left_out_when_the_person_gave_one_is_not_saved_as_a_reminder_that_never_fires(config):
    result, store = call_with(config, "Remind me to call mum tomorrow at 5pm", content="call mum")
    assert result.startswith("Not saved: you gave no time, but the user's message mentions ") and "tomorrow" in result
    assert store.reminders("all") == []
    result, store = call_with(config, "Remind me to renew my passport", content="renew my passport")  # they gave none: saved with none
    assert result.startswith("Reminder saved: renew my passport. It has NO time, so it will not fire") and len(store.reminders()) == 1


def test_the_persons_own_words_are_saved(config):
    for said, words, expected in [
        ("Remind me to call mum tomorrow at 5pm", "tomorrow at 5pm", "Thursday 24 Sep 2026, 17:00"),
        ("Remind me on Friday at 3pm to send the report", "Friday 3pm", "Friday 25 Sep 2026, 15:00"),
        ("Remind me about the dentist on 3 October at 2pm", "3 October at 2pm", "Saturday 3 Oct 2026, 14:00"),
        ("Remind me in 2 hours to check the oven", "in 2 hours", "Wednesday 23 Sep 2026, 12:15"),
    ]:
        result, store = call_with(config, said, content="x", due_at=words)
        assert result == f"Reminder saved: x, for {expected}", result


def test_a_time_that_cannot_be_read_is_reported_as_that_and_not_as_a_change(config):
    result, store = call_with(config, "Remind me to call the vet after lunch", content="call the vet", due_at="after lunch")
    assert result.startswith("Not saved: I could not tell when 'after lunch' is") and store.reminders("all") == []


def test_a_time_that_is_both_unreadable_and_changed_is_reported_as_unreadable_first(config):
    result, store = call_with(config, "Remind me to call the vet after lunch", content="call the vet", due_at="in 2 hours after lunch")
    assert result.startswith("Not saved: I could not tell when 'in 2 hours after lunch' is") and store.reminders("all") == []


def test_outside_a_turn_the_words_are_not_compared_with_any_message(config, store):
    agent, _ = agent_for(config, tool_reply("add_reminder", '{"content": "no"}', call_id="c1"), text_reply("ok"))
    ask(agent, "Remind me to renew my passport")  # a turn whose message has no time in it
    assert agent.add_reminder("a direct call", "friday 5pm").startswith("Reminder saved: a direct call, for Friday 25 Sep 2026, 17:00")


def test_the_hint_tells_the_model_to_use_the_persons_words_or_ask():
    assert "exactly as the user said it" in diya.REMINDER_TIME_HINT and "ask them when" in diya.REMINDER_TIME_HINT
