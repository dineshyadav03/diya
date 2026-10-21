"""What did you know on that day? (Memory.as_of, diya_provenance.asks_as_of, `diya_review.py as-of`; docs/TIME_DESIGN.md), added 2026-10-21 from Mem0's article on time in memory.

What this proves, with the real memory and database and facts whose trail is dated by hand: the replay says what was accepted at the end of a past day and nothing from after it (a fact added later is absent, a
fact retired later is still there, a fact retired before is absent, a fact restored is back from the day it was restored); a candidate reworded before it was accepted comes back in the words it had then;
a fact forgotten for good is left out because its words are gone; nothing is written by asking; the question "what did you know about me on 12 Oct?" is told from "what do you know about my dog?" and from
"how do you know ...?"; the answer is made by code from the record and says what changed since; a topic narrows it; a day before anything was remembered says so; and the command line says the same.
"""
import dataclasses
import io
import sqlite3
from datetime import date, datetime, timezone

import pytest

import diya_provenance
import diya_review
from diya_db import Store
from diya_memory import Memory

import diya_config

TODAY = date(2026, 10, 21)


def at(day, hour=12):
    return datetime(2026, 10, day, hour, 0, tzinfo=timezone.utc).astimezone()


def end_of(day):
    return datetime(2026, 10, day + 1, 0, 0).astimezone()


@pytest.fixture
def world(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    return store, Memory(store)


def stamp(store, fact_id, event, when, nth=0):
    """Move the `nth` event of that kind for that fact to `when` (an ISO moment), so the trail reads as it would have over weeks."""
    conn = sqlite3.connect(store.path)
    try:
        rows = conn.execute("SELECT id FROM fact_events WHERE fact_id = ? AND event = ? ORDER BY id", (fact_id, event)).fetchall()
        conn.execute("UPDATE fact_events SET at = ? WHERE id = ?", (when, rows[nth][0]))
        conn.commit()
    finally:
        conn.close()


def added_on(store, memory, text, day):
    fact = memory.add_manual(text, "api")
    stamp(store, fact, "added", f"2026-10-{day:02d}T09:00:00+00:00")
    return fact


def test_a_fact_added_after_the_day_is_not_known_then_and_one_retired_after_it_still_is(world):
    store, memory = world
    early = added_on(store, memory, "has a dog called Rocky", 3)
    added_on(store, memory, "is preparing for the board exam", 15)
    memory.decide(early, "retire", "api")
    stamp(store, early, "retired", "2026-10-18T09:00:00+00:00")
    assert [f["text"] for f in memory.as_of(end_of(10))] == ["has a dog called Rocky"]
    assert [f["text"] for f in memory.as_of(end_of(16))] == ["has a dog called Rocky", "is preparing for the board exam"]
    assert [f["text"] for f in memory.as_of(end_of(20))] == ["is preparing for the board exam"]  # retired on the 18th


def test_a_restored_fact_is_back_from_the_day_it_was_restored(world):
    store, memory = world
    fact = added_on(store, memory, "lives in Pune", 2)
    memory.decide(fact, "retire", "api")
    stamp(store, fact, "retired", "2026-10-05T09:00:00+00:00")
    memory.decide(fact, "restore", "api")
    stamp(store, fact, "restored", "2026-10-12T09:00:00+00:00")
    assert memory.as_of(end_of(4))[0]["since"].startswith("2026-10-02")
    assert memory.as_of(end_of(8)) == []
    back = memory.as_of(end_of(13))
    assert [f["text"] for f in back] == ["lives in Pune"] and back[0]["since"].startswith("2026-10-12")


def test_a_candidate_reworded_before_it_was_accepted_comes_back_in_the_words_it_had_then(world):
    store, memory = world
    fact = memory.add_candidate("plays the flute", batch_first=1, batch_last=1, position=0, model="m", extracted_at="2026-10-01T09:00:00+00:00", raw="plays the flute")
    stamp(store, fact, "ingested", "2026-10-01T09:00:00+00:00")
    memory.edit(fact, "plays the flute in the school band", "cli")
    stamp(store, fact, "edited", "2026-10-09T09:00:00+00:00")
    memory.decide(fact, "accept", "cli")
    stamp(store, fact, "accepted", "2026-10-10T09:00:00+00:00")
    assert memory.as_of(end_of(8)) == []  # not accepted yet
    memory_then = memory.as_of(end_of(10))
    assert [f["text"] for f in memory_then] == ["plays the flute in the school band"]  # reworded on the 9th, accepted on the 10th
    assert memory.get(fact)["text"] == "plays the flute in the school band"


def test_words_changed_after_the_day_are_read_back(world):
    store, memory = world
    fact = memory.add_candidate("plays the flute", batch_first=1, batch_last=1, position=0, model="m", extracted_at="2026-10-01T09:00:00+00:00", raw="plays the flute")
    stamp(store, fact, "ingested", "2026-10-01T09:00:00+00:00")
    memory.decide(fact, "accept", "cli")
    stamp(store, fact, "accepted", "2026-10-02T09:00:00+00:00")
    conn = sqlite3.connect(store.path)
    try:  # a later rewording of the same fact (as a person reopening and editing it would have made)
        conn.execute("UPDATE facts SET text = 'plays the flute in the band', text_key = 'plays the flute in the band' WHERE id = ?", (fact,))
        conn.execute("INSERT INTO fact_events (fact_id, event, actor, at, detail) VALUES (?, 'edited', 'cli', '2026-10-20T09:00:00+00:00', ?)", (fact, '{"from": "plays the flute"}'))
        conn.commit()
    finally:
        conn.close()
    assert [f["text"] for f in memory.as_of(end_of(5))] == ["plays the flute"]  # the later rewording is read back to what it was
    assert [f["text"] for f in memory.as_of(end_of(21))] == ["plays the flute in the band"]


def test_a_fact_forgotten_for_good_is_left_out_because_its_words_are_gone(world):
    store, memory = world
    fact = added_on(store, memory, "owes the library forty rupees", 4)
    memory.purge(fact, "api")
    assert memory.as_of(end_of(10)) == []


def test_asking_changes_nothing(world):
    store, memory = world
    added_on(store, memory, "likes tea", 4)
    before = (memory.facts(), [memory.events(f["id"]) for f in memory.facts()])
    memory.as_of(end_of(10))
    assert (memory.facts(), [memory.events(f["id"]) for f in memory.facts()]) == before and memory.verify_integrity() == []


@pytest.mark.parametrize("question, day", [
    ("what did you know about me on 12 Oct?", date(2026, 10, 12)),
    ("What did you remember about me yesterday", date(2026, 10, 20)),
    ("what did you know last week?", date(2026, 10, 18)),
    ("which things did you remember as of 2026-10-01", date(2026, 10, 1)),
    ("how much did you know about me 3 days ago", date(2026, 10, 18)),
    ("show me your memory as of 5 Oct", date(2026, 10, 5)),
    ("what was in your memory on 12 Oct", date(2026, 10, 12)),
])
def test_questions_that_ask_what_was_known_on_a_past_day(question, day):
    found = diya_provenance.asks_as_of(question, TODAY)
    assert found is not None and found[0] == day


@pytest.mark.parametrize("question", [
    "what do you know about my dog?", "what did you know?", "what did you say last week?", "how do you know I have a dog?", "what did you know about me on 25 Dec 2030?",
    "remember to call mom yesterday", "", None, 7,
])
def test_questions_that_are_not_about_a_past_day_are_left_to_the_model(question):
    assert diya_provenance.asks_as_of(question, TODAY) is None


def test_the_answer_lists_what_was_remembered_and_what_changed_since(world):
    store, memory = world
    early = added_on(store, memory, "has a dog called Rocky", 3)
    added_on(store, memory, "is preparing for the board exam", 15)
    memory.decide(early, "retire", "api")
    stamp(store, early, "retired", "2026-10-18T09:00:00+00:00")
    answer = diya_provenance.as_of_answer(memory, date(2026, 10, 10), "about me")
    assert answer.startswith("At the end of Sat 10 Oct 2026 I remembered 1 thing:")
    assert "has a dog called Rocky" in answer and "board exam" not in answer
    assert "Since then: 1 added, 1 no longer used." in answer and "not written by the model" in answer


def test_a_topic_narrows_the_answer(world):
    store, memory = world
    added_on(store, memory, "has a dog called Rocky", 3)
    added_on(store, memory, "is preparing for the board exam", 4)
    answer = diya_provenance.as_of_answer(memory, date(2026, 10, 10), "about my dog on 10 Oct")
    assert "Rocky" in answer and "board exam" not in answer and "about that" in answer


def test_a_day_before_anything_was_remembered_says_so_and_names_the_first_day(world):
    store, memory = world
    added_on(store, memory, "likes tea", 9)
    answer = diya_provenance.as_of_answer(memory, date(2026, 10, 2), "")
    assert "I had nothing remembered" in answer and "first thing I have a record of remembering came on" in answer


def test_explain_answers_it_from_the_record_and_the_old_questions_still_work(world):
    store, memory = world
    fact = added_on(store, memory, "has a dog called Rocky", 3)
    assert "Rocky" in diya_provenance.explain(memory, store, "what did you know about me on 12 Oct?")
    assert "Rocky" in diya_provenance.explain(memory, store, "how do you know I have a dog?")
    assert diya_provenance.explain(memory, store, "what do you know about my dog?") is None
    assert memory.get(fact)["status"] == "accepted"


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(diya_config.load_config(), db_path=str(data / "cli.db"), profile_path=str(data / "profile.txt"), dream_state_path=str(data / "state.json"),
                               dream_log_path=str(data / "dream.log"), dream_pending_path=str(data / "pending.jsonl"))


def review(config, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = diya_review.main(list(argv), config=config, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_the_command_line_says_the_same_and_refuses_a_day_that_has_not_come(config):
    store = Store(config.db_path)
    memory = Memory(store)
    added_on(store, memory, "has a dog called Rocky", 3)
    code, out, _err = review(config, "as-of", "2026-10-10")
    assert code == 0 and "Rocky" in out and "I remembered 1 thing" in out
    code, out, _err = review(config, "as-of", "next", "week")
    assert code != 0 and "already come" in out


class Quiet:
    def transcribe(self, path):
        return ""


def test_in_the_chat_it_is_answered_from_the_record_and_the_model_is_not_asked(tmp_path):
    from fastapi.testclient import TestClient

    import diya
    import diya_web
    from fakes import ByQuestionClient

    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "c.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"),
        dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), auto_memory=False, require_token=False, categories=False, lookup=False,
    )
    model = ByQuestionClient(chat=["unused"])
    agent = diya.Agent(config, client=model)
    added_on(agent.store, Memory(agent.store), "has a dog called Rocky", 3)
    web = TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")
    answer = str(web.post("/api/chat", json={"message": "what did you know about me on 2026-10-10?"}).json())
    assert "I remembered 1 thing" in answer and "Rocky" in answer and "Since then" in answer
    assert len(model.asked("chat")) == 0  # the record answered; the model could not make up a past
