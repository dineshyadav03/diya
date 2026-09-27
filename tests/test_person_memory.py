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

import diya_memory
from diya_db import Store
from diya_memory import (
    BudgetExceeded,
    InvalidFact,
    Memory,
    UnknownFact,
    UnknownPerson,
    check_person_name,
    extract_person_tag,
    person_key,
    render_grouped,
    render_profile,
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


@pytest.mark.parametrize("word", ["self", "Self", "SELF", " self ", "user", "User", "USER", " user "])
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


@pytest.mark.parametrize("self_spelling", ["self", "Self", "SELF", "user", "User", None])
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


# --- extract_person_tag: reading Dreaming's optional [Name] suffix (unit M2) ------------------------------

@pytest.mark.parametrize("line, text, name", [
    ("- sister Maya is visiting in May [Maya]", "- sister Maya is visiting in May", "Maya"),
    ("- likes green tea", "- likes green tea", None),
    ("- likes green tea ", "- likes green tea ", None),  # trailing space alone is not a tag
    ("- has a cat [Pixel]", "- has a cat", "Pixel"),
    ("- has a cat [Pixel] ", "- has a cat", "Pixel"),  # trailing space after the tag
    ("- has a cat [ Pixel ]", "- has a cat", "Pixel"),  # space just inside the brackets is not part of the name
    ("weird [a][b]", "weird [a]", "b"),  # only the trailing bracket is the tag; an earlier one is the fact's own
    ("- has a cat named Pixel []", "- has a cat named Pixel []", None),  # empty brackets: nothing to tag with
    ("- x [" + "n" * 80 + "]", "- x", "n" * 80),  # right at the pattern's own limit
    ("- x [" + "n" * 81 + "]", "- x [" + "n" * 81 + "]", None),  # one over: not read as a tag at all
    ("", "", None),
])
def test_extract_person_tag_reads_a_trailing_bracket_and_nothing_else(line, text, name):
    assert extract_person_tag(line) == (text, name)


def test_extract_person_tag_is_never_given_anything_but_text_from_a_real_queue_but_does_not_crash_on_other_types():
    for value in (None, 5, ["x"], {"a": 1}):
        assert extract_person_tag(value) == (value, None)


def test_extract_person_tag_does_not_validate_the_name_that_is_the_callers_job():
    assert extract_person_tag("- x [not\ta name]") == ("- x", "not\ta name")  # a tab: check_person_name would refuse it


# --- add_candidate with a person (unit M2) -----------------------------------------------------------------

def test_add_candidate_with_a_person_tags_it_and_creates_the_person(memory):
    fact_id = memory.add_candidate(
        "sister Maya is visiting in May", batch_first=2, batch_last=2, position=0, model="m",
        extracted_at=STAGED_AT, raw="- sister Maya is visiting in May [Maya]", person="Maya",
    )
    assert memory.get(fact_id)["person"] == "Maya"
    assert memory.people() == [{"name": "Maya", "facts": 1}]


@pytest.mark.parametrize("word", ["self", "Self", "user", "User", "USER", None])
def test_add_candidate_treats_self_and_user_as_no_person_not_a_real_name(memory, word):
    """Measured 2026-09-27: the real model, told to leave the brackets off a fact about the user, sometimes
    writes the literal tag [User] for exactly that case instead. Treated as self everywhere a name is taken,
    not only in ingest_queue's own forgiving handling, so a direct caller gets the same answer."""
    fact_id = memory.add_candidate(
        "x", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- x", person=word,
    )
    assert memory.get(fact_id)["person"] is None
    assert memory.people() == []


def test_add_candidate_with_no_person_is_unchanged_from_before_this_existed(memory):
    fact_id = candidate(memory, "likes green tea")
    assert memory.get(fact_id)["person"] is None
    assert memory.people() == []


def test_add_candidate_reuses_an_existing_person_case_insensitively(memory):
    memory.add_manual("x", "cli")
    memory.set_person(1, "Maya", "cli")
    fact_id = memory.add_candidate(
        "y", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- y [MAYA]", person="MAYA",
    )
    assert memory.get(fact_id)["person"] == "Maya"  # the first spelling, like everywhere else
    assert memory.people() == [{"name": "Maya", "facts": 2}]


def test_add_candidate_refuses_a_bad_person_name_and_creates_nothing(memory):
    with pytest.raises(InvalidFact):
        memory.add_candidate(
            "x", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- x", person="a\tb",
        )
    assert memory.facts() == [] and memory.people() == []


def test_add_candidate_no_event_beyond_ingested_for_the_persons_tag_at_creation(memory):
    """Unlike set_person, tagging at creation is not a change from something -- it is what the fact
    always was -- so there is no separate retagged event, just the one ingested event everything gets."""
    fact_id = memory.add_candidate(
        "x", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- x [Maya]", person="Maya",
    )
    assert [event for event, _actor, _at, _detail in memory.events(fact_id)] == ["ingested"]


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


# --- render_grouped: what the model is actually told (docs/PERSON_MEMORY_DESIGN.md, D4/M4) ---------------

def test_render_grouped_with_nobody_tagged_is_byte_identical_to_the_old_flat_render():
    """The whole point of this being additive: a database with no one tagged must produce exactly what
    it always has, not a new label on every existing conversation."""
    texts = ["likes green tea", "works in the evenings"]
    facts = [(t, None) for t in texts]
    assert render_grouped(facts) == render_profile(texts)


def test_render_grouped_is_empty_for_no_facts():
    assert render_grouped([]) == ""


def test_render_grouped_puts_a_named_persons_facts_in_their_own_labelled_block():
    facts = [("likes green tea", None), ("sister Maya is visiting in May", "Maya")]
    assert render_grouped(facts) == "- likes green tea\n\nAbout Maya:\n- sister Maya is visiting in May"


def test_render_grouped_with_only_named_people_has_no_leading_self_block():
    facts = [("sister Maya is visiting in May", "Maya")]
    assert render_grouped(facts) == "About Maya:\n- sister Maya is visiting in May"


def test_render_grouped_orders_named_people_alphabetically_case_insensitively_you_first():
    facts = [("x", "Zed"), ("y", None), ("z", "maya")]
    assert render_grouped(facts) == "- y\n\nAbout maya:\n- z\n\nAbout Zed:\n- x"


def test_render_grouped_keeps_a_persons_own_facts_in_the_order_given():
    facts = [("first about maya", "Maya"), ("second about maya", "Maya")]
    assert render_grouped(facts) == "About Maya:\n- first about maya\n- second about maya"


def test_render_grouped_groups_the_same_person_regardless_of_spelling_given_to_it():
    """render_grouped trusts its caller for the exact spelling (Memory.render_for_model always passes
    the one canonical name people() stores); this only proves it groups by exact string equality."""
    facts = [("a", "Maya"), ("b", "Maya")]
    assert render_grouped(facts).count("About Maya:") == 1


# --- Memory.render_for_model: the real thing, from the store ---------------------------------------------

def test_render_for_model_is_empty_when_nothing_is_accepted(memory):
    assert memory.render_for_model() == ""


def test_render_for_model_matches_render_when_nobody_is_tagged(memory):
    memory.add_manual("likes green tea", "cli")
    memory.add_manual("works in the evenings", "cli")
    assert memory.render_for_model() == memory.render()


def test_render_for_model_groups_by_person_while_render_and_export_stay_flat(memory):
    """The regression this whole unit must not cause: render()/accepted_texts() (export, import-profile)
    keep every accepted fact in one flat list regardless of who it is about."""
    memory.add_manual("likes green tea", "cli")
    fact_id = memory.add_manual("sister Maya is visiting in May", "cli")
    memory.set_person(fact_id, "Maya", "cli")

    assert memory.render_for_model() == "- likes green tea\n\nAbout Maya:\n- sister Maya is visiting in May"
    assert memory.render() == "- likes green tea\n- sister Maya is visiting in May"  # unchanged: still flat
    assert memory.accepted_texts() == ["likes green tea", "sister Maya is visiting in May"]


def test_render_for_model_ignores_anything_not_accepted(memory):
    memory.add_manual("likes green tea", "cli")
    fact_id = candidate(memory, "sister Maya is visiting in May")
    memory.set_person(fact_id, "Maya", "cli")  # tagged, but still a candidate
    assert memory.render_for_model() == "- likes green tea"


# --- the character budget is measured on the grouped form, not the flat one (M4) --------------------------

def test_accepting_the_first_fact_for_a_new_person_counts_the_new_headers_overhead(memory, monkeypatch):
    """A fact that would fit the flat budget can still be refused once its own "About Name:" header is
    counted -- that header is real content sent to the model, so it must count."""
    fact_id = candidate(memory, "x")
    memory.set_person(fact_id, "Maya", "cli")
    flat_len = len(render_profile(["x"]))
    grouped_len = len(render_grouped([("x", "Maya")]))
    assert grouped_len > flat_len  # the premise: the header adds real length
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", grouped_len - 1)  # fits flat, not grouped
    with pytest.raises(BudgetExceeded):
        memory.decide(fact_id, "accept", "cli")
    assert memory.get(fact_id)["status"] == "candidate"  # refused, not partially applied


def test_add_manual_is_held_to_the_grouped_budget_too(memory, monkeypatch):
    fact_id = candidate(memory, "sister Maya is visiting in May")
    memory.set_person(fact_id, "Maya", "cli")
    memory.decide(fact_id, "accept", "cli")
    used = len(memory.render_for_model())
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", used)  # no room left at all
    with pytest.raises(BudgetExceeded):
        memory.add_manual("likes green tea", "cli")


def test_import_legacys_over_budget_check_accounts_for_already_tagged_facts(memory, monkeypatch):
    fact_id = memory.add_manual("sister Maya is visiting in May", "cli")
    memory.set_person(fact_id, "Maya", "cli")
    grouped_used = len(memory.render_for_model())
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", grouped_used)  # already exactly full, grouped
    result = memory.import_legacy([("a new fact", "- a new fact", [])], actor="import")
    assert result.imported == 1 and result.over_budget is True
    assert result.chars_used == len(memory.render_for_model())  # measured on the grouped form, not the flat one
