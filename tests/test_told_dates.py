"""The model is told what a relative time word meant on the day it was written (Memory._told_texts, docs/TIME_DESIGN.md), added 2026-10-21 from Mem0's article on time in memory.

What this proves, with the real memory and database: a fact saved as "ran a 10K last weekend" on a Monday in June 2025 is told to the model months later as "... last weekend (that was the weekend of 14-15 Jun 2025)", read
against the day of the MESSAGE it came from (not the day it was filed, not today); the stored words never change; a fact written today is told as it is; a fact with no relative word is untouched; a phrase that
cannot be told stays as written; the limit on how much is told is measured on the annotated words; and the same holds when the memory is bigger than the room and recall chooses. It does not rewrite memory:
the Memory page and the exports still show the person's own words.
"""
import dataclasses
import sqlite3

import pytest

import diya_config
import diya_memory
from diya_db import Store
from diya_memory import Memory


@pytest.fixture
def world(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    return store, Memory(store)


def sql(store, query, args=()):
    conn = sqlite3.connect(store.path)
    try:
        conn.execute(query, args)
        conn.commit()
    finally:
        conn.close()


def said_on(store, memory, text, fact_text, when):
    """A message of the person's saved on `when`, and a fact read from it (filed later, as a scheduled pass would)."""
    message = store.add_message(store.main_thread(), "user", text)
    sql(store, "UPDATE messages SET created_at = ? WHERE id = ?", (when, message))
    fact = memory.add_manual(fact_text, "api")
    sql(store, "UPDATE facts SET flags = ?, source = 'dreaming' WHERE id = ?", (f'["source_message:{message}"]', fact))
    return fact


def test_a_fact_from_an_old_message_is_told_with_what_its_words_meant_then(world):
    store, memory = world
    said_on(store, memory, "I ran my first 10K last weekend and finished in 58 minutes", "ran a 10K last weekend in 58 minutes", "2025-06-16T09:00:00+00:00")
    told = memory.render_for_model()
    assert told == "- ran a 10K last weekend (that was the weekend of 14-15 Jun 2025) in 58 minutes"


def test_the_stored_words_are_the_persons_own_and_never_change(world):
    store, memory = world
    fact = said_on(store, memory, "I started the new meds yesterday", "started the new meds yesterday", "2025-08-10T09:00:00+00:00")
    memory.render_for_model()
    assert memory.get(fact)["text"] == "started the new meds yesterday" and "that was" not in str(memory.facts())
    assert [e[0] for e in memory.events(fact)] == ["added"]  # and nothing was written to its trail


def test_it_is_the_day_of_the_message_not_the_day_the_fact_was_filed(world):
    store, memory = world
    fact = said_on(store, memory, "I went to the lab yesterday", "went to the lab yesterday", "2026-03-10T09:00:00+00:00")
    sql(store, "UPDATE facts SET created_at = '2026-09-01T09:00:00+00:00' WHERE id = ?", (fact,))  # filed half a year later
    assert "that was Mon 9 Mar 2026" in memory.render_for_model()


def test_a_fact_with_no_message_is_read_against_the_day_it_was_filed(world):
    store, memory = world
    fact = memory.add_manual("had a dentist visit two weeks ago", "api")
    sql(store, "UPDATE facts SET created_at = '2026-01-20T09:00:00+00:00' WHERE id = ?", (fact,))
    assert memory.render_for_model() == "- had a dentist visit two weeks ago (that was about Tue 6 Jan 2026)"


def test_a_fact_written_today_is_told_as_it_is(world):
    store, memory = world
    memory.add_manual("went for a run yesterday", "api")
    assert memory.render_for_model() == "- went for a run yesterday"


def test_a_fact_without_a_relative_word_and_a_phrase_that_cannot_be_told_are_untouched(world):
    store, memory = world
    said_on(store, memory, "I like tea", "likes tea", "2025-06-16T09:00:00+00:00")
    said_on(store, memory, "my race is next Friday", "has a race next Friday", "2025-06-16T09:00:00+00:00")
    assert memory.render_for_model() == "- likes tea\n- has a race next Friday"


def test_the_limit_is_measured_on_what_is_told(tmp_path):
    store = Store(str(tmp_path / "limit.db"))
    memory = Memory(store)
    said_on(store, memory, "x", "ran a 10K last weekend", "2025-06-16T09:00:00+00:00")
    plain = len("- ran a 10K last weekend")
    assert len(memory.render()) == plain  # the flat export is the person's words
    assert len(memory.render_for_model()) > plain  # what the model is told is longer, and is what the limit counts
    with memory._read() as conn:
        assert len(diya_memory.render_grouped(memory._accepted_with_person(conn))) == len(memory.render_for_model())


def test_the_same_holds_when_the_memory_is_bigger_than_the_room(tmp_path):
    store = Store(str(tmp_path / "big.db"))
    memory = Memory(store, store_limit=20000)
    said_on(store, memory, "I ran a 10K last weekend", "ran a 10K last weekend", "2025-06-16T09:00:00+00:00")
    for n in range(60):
        memory.add_manual(f"owns umbrella number {n} for the rainy season of the year, a red one", "api")
    told = memory.render_for_model(query="what 10K did I run?", embed=lambda text: [1.0, 0.0] if "10K" in text else [0.0, 1.0], model="m")
    assert "ran a 10K last weekend (that was the weekend of 14-15 Jun 2025)" in told and "more facts are not shown" in told
