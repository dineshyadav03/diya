"""Reminders that were done (docs/PROACTIVITY_DESIGN.md, "Reminders that were done"): the time a reminder was ticked off, the model's way to read them, and the note a question about what the person did is given.

What this proves: ticking a reminder off keeps when (and a reminder done before that was kept has no time, and says so); the list the model can ask for says which were ticked off and when, and a repeating
series' reminder closed unticked is not called "done"; asked with a bad state it says what the states are; the default is still exactly the pending list; a question about something the person did ("when did
I buy the guitar strings?") is given what they ticked off, at the END of the system message, and any other question or a chat with nothing ticked off is given nothing; and an automation's run never gets it.
"""
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_config
import diya_intent
from diya_db import Store
from fakes import FakeClient, text_reply

NOW = datetime(2026, 10, 11, 21, 30)


def make_agent(tmp_path, replies=()):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "d.db"), profile_path=str(tmp_path / "profile.txt"))
    return diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: NOW)


# ---- the store --------------------------------------------------------------------------------------------------------------

def test_ticking_one_off_keeps_when_and_an_older_one_has_no_time(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    first, second, third = (store.add_reminder(name) for name in ("buy strings", "call the bank", "pay rent"))
    assert store.complete_reminder(first, "2026-10-11T15:40:00Z") is True and store.complete_reminder(first) is False  # once
    conn = store.connect()
    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (second,))  # done before the time was kept
    conn.commit()
    conn.close()
    rows = store.done_reminders()
    assert [(r["id"], r["done_at"]) for r in rows] == [(first, "2026-10-11T15:40:00Z"), (second, None)] and store.get_reminder(third)["done"] == 0


def test_a_time_that_is_not_a_stored_moment_is_refused(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.add_reminder("x")
    with pytest.raises(ValueError):
        store.complete_reminder(1, "yesterday")


def test_the_done_route_keeps_the_time(tmp_path):
    from fastapi.testclient import TestClient

    import diya_web

    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)
    agent = diya.Agent(config, client=FakeClient(), clock=lambda: NOW)
    rid = agent.store.add_reminder("buy strings")
    assert TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost").post(f"/api/reminders/{rid}/done").status_code == 200
    (row,) = agent.store.done_reminders()
    assert row["done_at"] is not None and row["done_at"].endswith("Z")


# ---- what the model can read --------------------------------------------------------------------------------------------------

def test_the_default_is_still_exactly_the_pending_list(tmp_path):
    agent = make_agent(tmp_path)
    assert agent.list_reminders() == "No pending reminders." == agent.list_reminders("pending")
    done = agent.store.add_reminder("buy strings")
    agent.store.add_reminder("call the bank", "tomorrow")
    agent.store.complete_reminder(done)
    assert agent.list_reminders() == "#2: call the bank (no time set; asked as 'tomorrow')"


def test_done_ones_say_when_or_say_it_was_not_kept_or_that_a_series_closed_it(tmp_path):
    agent = make_agent(tmp_path)
    assert agent.list_reminders("done") == "No reminders have been marked done."
    kept, old, series = (agent.store.add_reminder(name) for name in ("buy strings", "pay rent", "water plants"))
    agent.store.complete_reminder(kept, "2026-10-11T15:40:00Z")
    conn = agent.store.connect()
    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (old,))
    conn.execute("UPDATE reminders SET done = 1, series_id = 1 WHERE id = ?", (series,))
    conn.commit()
    conn.close()
    lines = agent.list_reminders("done").split("\n")
    assert lines[0] == "Reminders already done (the most recent first):"
    assert lines[1].startswith(f"#{kept}: buy strings (marked done Sunday 11 Oct 2026, ") and lines[1].endswith(")")
    assert lines[2] == f"#{series}: water plants (closed without being ticked off, because the next one of a repeating reminder came)"
    assert lines[3] == f"#{old}: pay rent (marked done, but the time it was done was not kept)"
    assert agent.list_reminders("all").startswith("No pending reminders.\n\nReminders already done")


def test_a_state_it_does_not_have_is_said_in_words(tmp_path):
    assert make_agent(tmp_path).list_reminders("finished") == "Error: state must be pending, done or all, not 'finished'."


def test_the_tool_offers_the_state_and_asks_for_none(tmp_path):
    spec = next(t for t in diya.TOOLS if t["function"]["name"] == "list_reminders")["function"]
    assert spec["parameters"]["properties"]["state"]["enum"] == ["pending", "done", "all"] and spec["parameters"]["required"] == []


# ---- the question ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "when did i buy new guitar", "When did I buy the guitar strings?", "did I buy the guitar strings?", "have I bought guitar strings yet", "Hey Diya, did I call the bank",
    "what have I already finished?", "what did I do today", "which reminders have I already completed?", "so did i pay the rent", "when was I last at the dentist",
])
def test_a_question_about_something_the_person_did_is_one(text):
    assert diya_intent.is_done_question(text)


@pytest.mark.parametrize("text", [
    "what do I need to do?", "what is the weather in Pune", "remind me to buy guitar strings tomorrow", "I bought new guitar strings", "hey", "what did the doctor say", "x" * 300, None,
])
def test_anything_else_is_not(text):
    assert not diya_intent.is_done_question(text)


def tick(agent, name, at="2026-10-11T15:40:00Z"):
    agent.store.complete_reminder(agent.store.add_reminder(name), at)


def system_of(agent, call=0):
    return agent.client.chat_calls[call]["messages"][0]["content"]


def test_a_question_about_what_they_did_is_given_what_they_ticked_off_at_the_end_of_the_system_message(tmp_path):
    agent = make_agent(tmp_path, [text_reply("You bought them.")])
    tick(agent, "buy new guitar strings")
    agent.tasks.complete(agent.tasks.add("renew passport")["id"])
    agent.ask(agent.with_profile([{"role": "user", "content": "when did i buy new guitar strings"}]))
    system = system_of(agent)
    assert system.startswith(diya.DONE_NOTE_PROMPT)  # nothing is known about the person here, so the note is the whole system message
    assert system.endswith("- task: renew passport (done Sunday 11 Oct 2026, 21:30)") and "- reminder: buy new guitar strings (marked done Sunday 11 Oct 2026, " in system


def test_the_note_goes_after_what_is_known_so_the_start_of_the_message_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(diya, "PERSONA", "You are Diya.")
    agent = make_agent(tmp_path, [text_reply("a"), text_reply("b")])
    tick(agent, "buy strings")
    agent.ask(agent.with_profile([{"role": "user", "content": "what is the weather"}]))
    agent.ask(agent.with_profile([{"role": "user", "content": "did i buy the strings"}]))
    plain, with_note = system_of(agent, 0), system_of(agent, 1)
    assert with_note.startswith(plain) and diya.DONE_NOTE_PROMPT in with_note and diya.DONE_NOTE_PROMPT not in plain


def test_another_question_or_nothing_ticked_off_or_an_unattended_run_is_given_nothing(tmp_path):
    agent = make_agent(tmp_path, [text_reply("a"), text_reply("b"), text_reply("c"), text_reply("d")])
    agent.ask([{"role": "user", "content": "did i buy the strings"}])  # nothing ticked off yet
    tick(agent, "buy strings")
    agent.ask([{"role": "user", "content": "what is the weather in Pune"}])
    agent.briefing("did I buy the strings")
    agent.ask([{"role": "user", "content": "did i buy the strings"}], on_event=None)
    notes = [diya.DONE_NOTE_PROMPT in " ".join(m["content"] for m in call["messages"] if isinstance(m, dict) and m["role"] == "system") for call in agent.client.chat_calls]
    assert notes == [False, False, False, True]


def test_a_series_closed_unticked_is_not_told_as_something_they_did(tmp_path):
    agent = make_agent(tmp_path, [text_reply("no")])
    rid = agent.store.add_reminder("water plants")
    conn = agent.store.connect()
    conn.execute("UPDATE reminders SET done = 1, series_id = 1 WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    agent.ask([{"role": "user", "content": "did i water the plants"}])
    assert diya.DONE_NOTE_PROMPT not in " ".join(m["content"] for m in agent.client.chat_calls[0]["messages"] if isinstance(m, dict))


def test_the_note_never_stays_for_the_next_turn(tmp_path):
    agent = make_agent(tmp_path, [text_reply("a")])
    tick(agent, "buy strings")
    agent.ask([{"role": "user", "content": "did i buy the strings"}])
    assert agent._turn.note is None
