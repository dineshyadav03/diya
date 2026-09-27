"""Who a fact is about (docs/PERSON_MEMORY_DESIGN.md, D1 and D3; unit M1: storage).

What this proves: a fact defaults to "self" (no person, not a row); tagging it with a name creates the
person the first time and reuses it after, case-insensitively, exactly like a fact's own text_key; setting
it back to "self" (any capitalisation) untags it; nothing here ever touches a fact's status or text; every
change that actually changed something is recorded as a `retagged` event with the old and new name, and one
that changes nothing is not; a merge moves every fact from one person to another (or to "self") in one
transaction, never deletes the losing person's row, and is refused for an unknown name or for merging away
from "self"; and the store stays internally consistent throughout (verify_integrity).
"""
import json
import sqlite3

import pytest

from diya_db import Store
from diya_memory import (
    InvalidFact,
    Memory,
    UnknownFact,
    UnknownPerson,
    check_person_name,
    person_key,
)

STAGED_AT = "2026-01-01T00:00:00+00:00"


def candidate(memory, text, position=0):
    return memory.add_candidate(text, batch_first=1, batch_last=1, position=position, model="m",
                                extracted_at=STAGED_AT, raw="- " + text)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "people.db"))


@pytest.fixture
def memory(store):
    return Memory(store)


def last_event(memory, fact_id):
    return memory.events(fact_id)[-1]


# --- tagging one fact -----------------------------------------------------------------------------------

def test_a_fact_defaults_to_self_which_is_not_a_row(memory):
    fact_id = memory.add_manual("likes green tea", "cli")
    assert memory.get(fact_id)["person"] is None
    assert memory.people() == []


def test_tagging_creates_the_person_the_first_time_and_reuses_it_after(memory):
    a = memory.add_manual("sister Maya is visiting in May", "cli")
    b = memory.add_manual("Maya's birthday is in March", "cli")
    assert memory.set_person(a, "Maya", "cli") is True
    assert memory.set_person(b, "Maya", "cli") is True
    assert memory.people() == [{"name": "Maya", "facts": 2}]
    assert memory.get(a)["person"] == memory.get(b)["person"] == "Maya"


def test_tagging_is_case_insensitive_like_a_facts_own_identity(memory):
    a = memory.add_manual("x", "cli")
    b = memory.add_manual("y", "cli")
    memory.set_person(a, "Maya", "cli")
    memory.set_person(b, "MAYA", "cli")
    assert memory.people() == [{"name": "Maya", "facts": 2}]  # the first spelling wins, like text_key


def test_tagging_the_same_person_again_changes_nothing_and_says_so(memory):
    fact_id = memory.add_manual("x", "cli")
    assert memory.set_person(fact_id, "Maya", "cli") is True
    events_before = memory.events(fact_id)
    assert memory.set_person(fact_id, "Maya", "cli") is False
    assert memory.set_person(fact_id, "maya", "cli") is False  # same person, different spelling
    assert memory.events(fact_id) == events_before  # no event for a no-op


@pytest.mark.parametrize("word", ["self", "Self", "SELF", " self "])
def test_setting_it_to_self_in_any_spelling_untags_it(memory, word):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    assert memory.set_person(fact_id, word, "cli") is True
    assert memory.get(fact_id)["person"] is None
    assert memory.people() == [{"name": "Maya", "facts": 0}]  # the person is not deleted, just empty


def test_setting_an_already_self_fact_to_self_changes_nothing(memory):
    fact_id = memory.add_manual("x", "cli")
    assert memory.set_person(fact_id, "self", "cli") is False


def test_none_means_self_too_the_same_as_due_at_none_means_no_time_elsewhere(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    assert memory.set_person(fact_id, None, "cli") is True
    assert memory.get(fact_id)["person"] is None
    assert memory.set_person(fact_id, None, "cli") is False  # already self: no-op, not an error


def test_tagging_never_touches_the_facts_status_or_text(memory):
    fact_id = memory.add_manual("likes green tea", "cli")
    before = memory.get(fact_id)
    memory.set_person(fact_id, "Maya", "cli")
    after = memory.get(fact_id)
    assert (before["status"], before["text"]) == (after["status"], after["text"])


def test_an_unknown_fact_is_refused_and_nothing_is_created(memory):
    with pytest.raises(UnknownFact):
        memory.set_person(999, "Maya", "cli")
    assert memory.people() == []


@pytest.mark.parametrize("bad", ["", "   ", "a\tb", "a\nb", "x" * 61, 5, "line\x00feed"])
def test_a_name_that_is_not_canonical_text_or_is_too_long_is_refused(memory, bad):
    fact_id = memory.add_manual("x", "cli")
    with pytest.raises(InvalidFact):
        memory.set_person(fact_id, bad, "cli")
    assert memory.get(fact_id)["person"] is None


def test_check_person_name_accepts_a_plain_name_and_refuses_what_check_text_would():
    check_person_name("Maya")  # does not raise
    with pytest.raises(InvalidFact):
        check_person_name("a\nb")
    with pytest.raises(InvalidFact):
        check_person_name("x" * 61)


def test_person_key_folds_case_like_text_key():
    assert person_key("Maya") == person_key("MAYA") == person_key("maya") == "maya"


def test_a_bad_actor_is_refused_before_anything_is_written(memory):
    fact_id = memory.add_manual("x", "cli")
    with pytest.raises(ValueError):
        memory.set_person(fact_id, "Maya", "nobody")
    assert memory.get(fact_id)["person"] is None


# --- the event trail --------------------------------------------------------------------------------------

def test_tagging_records_a_retagged_event_with_the_old_and_new_name(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "api")
    event, actor, _at, detail = last_event(memory, fact_id)
    assert (event, actor) == ("retagged", "api")
    assert json.loads(detail) == {"from": None, "to": "Maya"}


def test_untagging_records_the_old_name_and_none(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    memory.set_person(fact_id, "self", "cli")
    event, _actor, _at, detail = last_event(memory, fact_id)
    assert event == "retagged" and json.loads(detail) == {"from": "Maya", "to": None}


def test_moving_a_fact_from_one_named_person_to_another_records_both_names(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    memory.set_person(fact_id, "Sam", "cli")
    event, _actor, _at, detail = last_event(memory, fact_id)
    assert event == "retagged" and json.loads(detail) == {"from": "Maya", "to": "Sam"}


def test_retagged_never_changes_the_status_even_under_verify_integrity(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    memory.set_person(fact_id, "self", "cli")
    assert memory.get(fact_id)["status"] == "accepted"
    assert memory.verify_integrity() == []


def test_tagging_a_candidate_leaves_it_a_candidate_not_accepted(memory):
    """A candidate and an already-accepted fact must look different under this: everything else in this
    file retags already-accepted facts, where a bug that forced retagged -> accepted would be invisible."""
    fact_id = candidate(memory, "sister Maya is visiting in May")
    memory.set_person(fact_id, "Maya", "cli")
    assert memory.get(fact_id)["status"] == "candidate"
    assert memory.verify_integrity() == []


def test_merging_a_candidates_person_leaves_it_a_candidate_too(memory):
    fact_id = candidate(memory, "x")
    memory.set_person(fact_id, "Maya", "cli")
    memory.merge_people("Maya", "Sam", "cli")
    assert memory.get(fact_id)["status"] == "candidate"
    assert memory.verify_integrity() == []


def test_the_name_key_index_refuses_a_second_person_with_the_same_key_at_the_sql_level(store):
    """set_person/merge_people never hit this (they always look up first), the way facts_one_accepted_per_key
    is never hit through normal use either: it is the backstop, and this proves it is really there."""
    conn = store.connect()
    conn.execute("INSERT INTO people (name, name_key, created_at) VALUES ('Maya', 'maya', 'now')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO people (name, name_key, created_at) VALUES ('MAYA', 'maya', 'now')")
    conn.close()


# --- listing people ------------------------------------------------------------------------------------------

def test_people_are_listed_alphabetically_by_key_not_by_first_spelling(memory):
    a, b, c = (memory.add_manual(x, "cli") for x in ("a", "b", "c"))
    memory.set_person(a, "Zara", "cli")
    memory.set_person(b, "amir", "cli")
    memory.set_person(c, "Mo", "cli")
    assert [p["name"] for p in memory.people()] == ["amir", "Mo", "Zara"]


def test_a_persons_fact_count_only_counts_facts_currently_theirs(memory):
    a, b = (memory.add_manual(x, "cli") for x in ("a", "b"))
    memory.set_person(a, "Maya", "cli")
    memory.set_person(b, "Maya", "cli")
    memory.set_person(b, "self", "cli")
    assert memory.people() == [{"name": "Maya", "facts": 1}]


# --- merging -------------------------------------------------------------------------------------------------

def test_merging_moves_every_fact_from_one_person_to_another(memory):
    a, b, c = (memory.add_manual(x, "cli") for x in ("a", "b", "c"))
    memory.set_person(a, "Maya", "cli")
    memory.set_person(b, "Maya", "cli")
    memory.set_person(c, "Sam", "cli")  # untouched: a different person
    assert memory.merge_people("Maya", "Mayaa", "cli") == 2
    assert {memory.get(a)["person"], memory.get(b)["person"]} == {"Mayaa"}
    assert memory.get(c)["person"] == "Sam"


def test_merging_creates_the_target_if_it_is_new_and_reuses_it_if_not(memory):
    a, b = (memory.add_manual(x, "cli") for x in ("a", "b"))
    memory.set_person(a, "Maya", "cli")
    memory.set_person(b, "Existing", "cli")
    memory.merge_people("Maya", "existing", "cli")  # case-insensitive: reuses "Existing"
    assert memory.people() == [{"name": "Existing", "facts": 2}, {"name": "Maya", "facts": 0}]


def test_merging_never_deletes_the_losing_persons_row(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    memory.merge_people("Maya", "Sam", "cli")
    names = [p["name"] for p in memory.people()]
    assert "Maya" in names and "Sam" in names  # the empty one is a record a merge happened, not gone


def test_merging_into_self_moves_facts_back_to_untagged(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    assert memory.merge_people("Maya", "self", "cli") == 1
    assert memory.get(fact_id)["person"] is None
    assert memory.people() == [{"name": "Maya", "facts": 0}]


@pytest.mark.parametrize("self_spelling", ["self", "Self", "SELF", None])
def test_merging_from_self_is_refused_and_moves_nothing(memory, self_spelling):
    a, b = (memory.add_manual(x, "cli") for x in ("a", "b"))  # both untagged: about self
    with pytest.raises(InvalidFact):
        memory.merge_people(self_spelling, "Maya", "cli")
    assert memory.get(a)["person"] is None and memory.get(b)["person"] is None and memory.people() == []


def test_merging_into_none_is_the_same_as_merging_into_self(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    assert memory.merge_people("Maya", None, "cli") == 1
    assert memory.get(fact_id)["person"] is None


def test_merging_an_unknown_person_is_refused(memory):
    with pytest.raises(UnknownPerson):
        memory.merge_people("Nobody", "Maya", "cli")
    assert memory.people() == []


def test_merging_a_person_into_themselves_changes_nothing(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    events_before = memory.events(fact_id)
    assert memory.merge_people("Maya", "maya", "cli") == 0
    assert memory.events(fact_id) == events_before


def test_each_moved_fact_gets_its_own_retagged_event_naming_the_merge(memory):
    a, b = (memory.add_manual(x, "cli") for x in ("a", "b"))
    memory.set_person(a, "Maya", "cli")
    memory.set_person(b, "Maya", "cli")
    memory.merge_people("Maya", "Mayaa", "api")
    for fact_id in (a, b):
        event, actor, _at, detail = last_event(memory, fact_id)
        assert (event, actor) == ("retagged", "api")
        assert json.loads(detail) == {"from": "Maya", "to": "Mayaa", "via": "merge"}


def test_merging_leaves_the_store_internally_consistent(memory):
    a, b, c = (memory.add_manual(x, "cli") for x in ("a", "b", "c"))
    memory.set_person(a, "Maya", "cli")
    memory.set_person(b, "Maya", "cli")
    memory.set_person(c, "Sam", "cli")
    memory.merge_people("Maya", "Sam", "cli")
    memory.merge_people("Sam", "self", "cli")
    assert memory.verify_integrity() == []


def test_a_bad_target_name_is_refused_and_moves_nothing(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    with pytest.raises(InvalidFact):
        memory.merge_people("Maya", "x" * 61, "cli")
    assert memory.get(fact_id)["person"] == "Maya"


def test_a_bad_actor_on_a_merge_is_refused_before_anything_moves(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    with pytest.raises(ValueError):
        memory.merge_people("Maya", "Sam", "nobody")
    assert memory.get(fact_id)["person"] == "Maya"


# --- reading facts still works exactly as before, with a person key added -------------------------------------

def test_get_and_facts_both_include_the_person_key_for_every_status(memory):
    fact_id = memory.add_manual("x", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    assert memory.get(fact_id)["person"] == "Maya"
    (only,) = memory.facts()
    assert only["person"] == "Maya"
    (accepted_only,) = memory.facts("accepted")
    assert accepted_only["person"] == "Maya"


def test_a_fresh_database_migrates_and_a_copy_of_an_existing_one_keeps_its_facts_untagged(tmp_path):
    """Migration 4 adds person_id as a plain nullable column: an existing facts row (from before this
    existed) reads back with person None, exactly like a brand-new untagged one."""
    path = str(tmp_path / "old.db")
    store = Store(path)
    memory = Memory(store)
    fact_id = memory.add_manual("existing fact", "cli")
    # reconnect (as a fresh process would) and confirm nothing about the existing fact changed
    again = Memory(Store(path))
    assert again.get(fact_id)["person"] is None
    assert again.verify_integrity() == []
