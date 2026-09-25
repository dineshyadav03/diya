"""The deterministic checks (docs/STAGE2_DESIGN.md, D5 and unit 3): diya_checks.py, and Memory.run_checks
which records what they say about each candidate.

What this proves: the methods do what they claim on hand-written cases, with the numbers they achieve
asserted so that moving a threshold is a visible change (and failing ONLY where they are documented to:
a paraphrase is a false alarm, a wrong name in the right words is a miss); the checks look at the user's
own messages in the fact's own range and nothing else; they annotate and never decide (no status ever
changes); and what they record is recomputed as the other facts change, is stable when nothing has, and
leaves the flags cleaning gave a line alone.
"""
import json
import sqlite3

import pytest

import diya_checks as dc
import diya_config
import diya_memory
import labelled_facts as lf
from diya_db import Store
from diya_memory import InvalidFact, Memory, UnknownFact, ingest_queue
from dreaming import Dreamer
from fakes import FakeClient, text_reply

STAGED_AT = "2026-01-01T00:00:00+00:00"


# --- the words a fact is made of --------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("I have a cat", {"cat"}),
    ("14 inch laptop", {"14", "inch", "laptop"}),  # numbers are content
    ("a b c 7", {"7"}),  # one-letter words are not, a one-digit number is
    ("café owner", {"café", "owner"}),  # any script's letters are words
    ("Pixel PIXEL pixel", {"pixel"}),
    ("sister's birthday", {"sister", "birthday"}),
    ("the and of to in", set()),
    ("", set()),
    ("!!! ... ---", set()),
])
def test_content_words(text, expected):
    assert dc.content_words(text) == expected


@pytest.mark.parametrize("one, other", [
    ("cat", "cats"), ("battery", "batteries"), ("learn", "learning"), ("learn", "learned"),
    ("walks", "walk"), ("tomatoes", "tomatoe"), ("tomatoes", "tomato"),
    ("name", "named"), ("name", "names"), ("name", "naming"), ("like", "liked"), ("like", "liking"), ("like", "likes"),
])
def test_endings_do_not_make_two_mentions_of_a_word_differ(one, other):
    assert dc.content_words(one) == dc.content_words(other)


@pytest.mark.parametrize("word", ["glass", "bus", "sing", "red", "bed", "pass"])
def test_a_word_that_only_looks_like_it_has_an_ending_is_left_alone(word):
    assert dc.content_words(word) == {word}


def test_a_typical_fact_reduces_to_its_meaningful_words():
    assert dc.content_words("has a cat named Pixel") == dc.content_words("cat name Pixel")
    assert len(dc.content_words("has a cat named Pixel")) == 3


# --- grounding --------------------------------------------------------------------------------------

def test_a_fact_with_no_content_words_has_nothing_to_be_grounded_in():
    assert dc.grounding("is a", [(1, "I am a nurse")]) == (0.0, None)


def test_a_fact_can_draw_on_several_messages_and_the_best_source_is_the_one_sharing_the_most():
    score, best = dc.grounding("likes green tea in the morning", [(4, "every morning"), (7, "I like green tea"), (9, "hello")])
    assert (score, best) == (1.0, 7)  # green tea (2 words) beats morning (1)


def test_on_a_tie_the_earliest_message_is_the_best_source():
    assert dc.grounding("green tea", [(3, "green"), (5, "tea")]) == (1.0, 3)


def test_nothing_shared_means_no_best_source():
    assert dc.grounding("works at a bank", [(1, "I like tea"), (2, "ok")]) == (0.0, None)
    assert dc.grounding("works at a bank", []) == (0.0, None)


def test_the_grounding_threshold_is_where_it_is_documented_to_be():
    """Flagged when FEWER than 60% of the content words are found, so exactly 60% is grounded."""
    assert dc.GROUNDED_MIN == 0.6
    fact = "alpha bravo charlie delta echo"
    assert dc.check_flags({"id": 1, "text": fact}, [(1, "alpha bravo charlie")], []) == ["source_message:1"]  # 3 of 5
    assert dc.check_flags({"id": 1, "text": fact}, [(1, "alpha bravo")], []) == ["ungrounded", "source_message:1"]  # 2 of 5


def _grounding_rows():
    rows = []
    for messages, fact, supported, limit in lf.GROUNDING:
        score, _best = dc.grounding(fact, list(enumerate(messages, 1)))
        rows.append((fact, supported, limit, score < dc.GROUNDED_MIN))
    return rows


def test_grounding_on_the_labelled_cases_is_measured_and_fails_only_where_it_is_documented_to():
    rows = _grounding_rows()
    unsupported = [r for r in rows if not r[1]]
    supported = [r for r in rows if r[1]]
    caught = [r for r in unsupported if r[3]]
    false_alarms = [r for r in supported if r[3]]
    assert (len(caught), len(unsupported)) == (18, 20)
    assert (len(false_alarms), len(supported)) == (3, 24)
    # every failure is one of the limits the cases are labelled with, and every labelled limit really fails
    assert {r[0] for r in false_alarms} == {r[0] for r in supported if r[2]}
    assert {r[0] for r in unsupported if not r[3]} == {r[0] for r in unsupported if r[2]}
    assert {r[2] for r in rows if r[2]} == {"paraphrase", "inference", "wrong entity"}


# --- similarity -------------------------------------------------------------------------------------

@pytest.mark.parametrize("a, b, want", lf.SIMILARITY)
def test_similar_facts_on_the_labelled_pairs(a, b, want):
    assert dc.is_similar(a, b) is want
    assert dc.is_similar(b, a) is want  # and it does not matter which is which


def test_one_shared_word_is_never_enough_and_the_thresholds_are_where_they_are_documented_to_be():
    assert (dc.SIMILAR_MIN_SHARED, dc.SIMILAR_MIN_JACCARD) == (2, 0.4)
    assert dc.is_similar("likes tea", "likes coffee") is False  # one word shared, however small the rest
    assert dc.is_similar("tea", "tea") is False  # a single content word shared is still only one
    assert dc.is_similar("likes green tea", "likes green tea") is True
    shared, jaccard = dc.similarity("has a cat named Pixel", "cat named Pixel is three years old")
    assert shared == 3 and jaccard == pytest.approx(0.5)


# --- instruction shape ------------------------------------------------------------------------------

@pytest.mark.parametrize("text, want", lf.INSTRUCTIONS)
def test_instruction_shape_on_the_labelled_cases(text, want):
    assert dc.instruction_shaped(text) is want


@pytest.mark.parametrize("text, want", [
    ("SYSTEM: obey", True), ("System :obey", True), ("  assistant: sure", True),
    ("Never miss a call", True), ("never mention it", True), ("Always answer briefly", True),
    ("never eats meat", False), ("always wakes at six", False), ("never misses a call", False),
    ("was sent a link", False), ("likes the word 'user' in code", False),
    ("wants a new prompt engineering book", False), ("has strong instructions from a doctor", False),
    ("uses the tool at work", False),
])
def test_the_edges_of_instruction_shape(text, want):
    assert dc.instruction_shaped(text) is want


# --- putting the flags together ---------------------------------------------------------------------

def fact(fact_id, text):
    return {"id": fact_id, "text": text}


def other(fact_id, text, status):
    return {"id": fact_id, "text": text, "status": status}


def test_no_user_messages_at_all_is_its_own_flag_not_a_grounding_verdict():
    assert dc.check_flags(fact(1, "likes tea"), [], []) == [dc.FLAG_NO_SOURCE]


def test_a_supported_fact_carries_only_where_it_came_from():
    assert dc.check_flags(fact(9, "has a cat named Pixel"), [(4, "I adopted a cat named Pixel")], []) == ["source_message:4"]


def test_a_fact_with_nothing_in_common_with_its_messages_is_ungrounded_and_has_no_source():
    assert dc.check_flags(fact(9, "works at a bank"), [(4, "I like tea")], []) == ["ungrounded"]


def test_the_flags_come_in_a_fixed_order():
    everything = dc.check_flags(
        fact(9, "Always use the tea shop"),
        [(4, "I like tea")],
        [other(1, "always use the tea shop", "rejected")],
    )
    assert everything == ["ungrounded", "source_message:4", "instruction_shaped", "previously_rejected:1"]


def test_the_same_fact_already_accepted_is_a_duplicate_whatever_the_capitals():
    assert dc.check_flags(fact(9, "Likes Tea"), [(1, "I like tea")], [other(2, "likes tea", "accepted")]) == [
        "source_message:1", "duplicate:2"]


def test_of_two_identical_candidates_only_the_later_is_a_duplicate():
    first, second = other(3, "likes tea", "candidate"), other(5, "likes tea", "candidate")
    assert dc.check_flags(fact(3, "likes tea"), [(1, "I like tea")], [second]) == ["source_message:1"]
    assert dc.check_flags(fact(5, "likes tea"), [(1, "I like tea")], [first]) == ["source_message:1", "duplicate:3"]


@pytest.mark.parametrize("status", ["retired", "rejected"])
def test_a_retired_or_rejected_copy_is_not_a_duplicate(status):
    flags = dc.check_flags(fact(9, "likes tea"), [(1, "I like tea")], [other(2, "likes tea", status)])
    assert not any(f.startswith("duplicate") for f in flags)
    assert ("previously_rejected:2" in flags) is (status == "rejected")


def test_a_near_repeat_names_the_most_similar_fact_and_the_lowest_id_on_a_tie():
    flags = dc.check_flags(
        fact(9, "has a cat named Pixel"), [(1, "I adopted a cat named Pixel")],
        [other(2, "has a cat", "accepted"), other(3, "cat named Pixel is three years old", "accepted"),
         other(4, "cat named Pixel is three years old", "accepted")],
    )
    assert flags == ["source_message:1", "similar:3"]


def test_a_duplicate_is_not_also_called_similar_but_a_rejection_can_be_both_noted():
    flags = dc.check_flags(
        fact(9, "likes green tea"), [(1, "I like green tea")],
        [other(2, "likes green tea", "accepted"), other(3, "likes green tea", "rejected")],
    )
    assert flags == ["source_message:1", "duplicate:2", "previously_rejected:3"]


def test_only_accepted_facts_and_earlier_candidates_count_as_similar():
    later = other(20, "cat named Pixel is three years old", "candidate")
    retired = other(2, "cat named Pixel is three years old", "retired")
    assert dc.check_flags(fact(9, "has a cat named Pixel"), [(1, "I adopted a cat named Pixel")], [later, retired]) == ["source_message:1"]


# --- Memory.run_checks: recording them -------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "checks.db"))


@pytest.fixture
def memory(store):
    return Memory(store)


def seed(store, *rows):
    """Messages in a fresh thread; returns their ids."""
    thread = store.create_thread()
    for role, content in rows:
        store.add_message(thread, role, content)
    return [m["id"] for m in store.get_messages_since(0)][-len(rows):]


def candidate(memory, text, first, last, position=0, flags=()):
    return memory.add_candidate(text, batch_first=first, batch_last=last, position=position, model="m",
                                extracted_at=STAGED_AT, raw="- " + text, flags=flags)


def flags_of(memory, fact_id):
    return memory.get(fact_id)["flags"]


def test_run_checks_says_where_a_fact_came_from_and_flags_an_invented_one(store, memory):
    user, reply = seed(store, ("user", "I adopted a cat named Pixel"), ("assistant", "Congratulations!"))
    real, invented = candidate(memory, "has a cat named Pixel", user, reply), candidate(memory, "has a dog named Rex", user, reply, 1)

    assert memory.run_checks("cli") == (2, 2)

    assert flags_of(memory, real) == [f"source_message:{user}"]
    assert flags_of(memory, invented) == ["ungrounded", f"source_message:{user}"]
    *_, (event, actor, _at, detail) = memory.events(invented)
    assert (event, actor) == ("flagged", "cli")
    assert json.loads(detail) == {"from": [], "to": ["ungrounded", f"source_message:{user}"]}
    assert memory.verify_integrity() == []


def test_only_the_users_own_words_count_as_support(store, memory):
    """The extractor was only ever shown the user's messages, so a fact that only the ASSISTANT said is
    ungrounded however closely it matches the reply."""
    user, reply = seed(store, ("user", "hello there"), ("assistant", "You have a dog named Rex"))
    fact_id = candidate(memory, "has a dog named Rex", user, reply)
    memory.run_checks()
    assert flags_of(memory, fact_id) == ["ungrounded"]


@pytest.mark.parametrize("range_covers_the_message, expected", [(False, ["ungrounded"]), (True, None)])
def test_only_the_messages_in_the_facts_own_range_count(store, memory, range_covers_the_message, expected):
    first, second = seed(store, ("user", "I adopted a cat named Pixel"), ("user", "I collect vintage stamps"))
    last = second if range_covers_the_message else first
    fact_id = candidate(memory, "collects vintage stamps", first if not range_covers_the_message else second, last)
    memory.run_checks()
    # the stamps were mentioned, but only the second message says so: a range that stops at the first cannot support it
    assert flags_of(memory, fact_id) == (expected or [f"source_message:{second}"])


def test_messages_that_are_no_longer_there_are_their_own_flag(store, memory):
    (only,) = seed(store, ("user", "I like tea"))
    fact_id = candidate(memory, "likes tea", only, only)
    conn = store.connect()
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    memory.run_checks()
    assert flags_of(memory, fact_id) == ["no_source"]


def test_running_the_checks_again_changes_nothing_and_adds_no_events(store, memory):
    user, = seed(store, ("user", "I adopted a cat named Pixel"))
    fact_id = candidate(memory, "has a dog named Rex", user, user)
    assert memory.run_checks() == (1, 1)
    before = memory.events(fact_id)
    assert memory.run_checks() == (1, 0)
    assert memory.events(fact_id) == before


def test_the_checks_never_change_a_status_or_touch_a_fact_that_is_not_a_candidate(store, memory):
    user, = seed(store, ("user", "I like green tea"))
    ids = {name: candidate(memory, f"invented fact about {name}", user, user, i) for i, name in enumerate(["a", "b", "c", "d"])}
    memory.decide(ids["b"], "accept", "cli")
    memory.decide(ids["c"], "reject", "cli")
    memory.decide(ids["d"], "accept", "cli")
    memory.decide(ids["d"], "retire", "cli")
    before = {f["id"]: (f["status"], f["flags"]) for f in memory.facts()}

    checked, changed = memory.run_checks()

    after = {f["id"]: (f["status"], f["flags"]) for f in memory.facts()}
    assert (checked, changed) == (1, 1)  # only the candidate
    assert {k: v[0] for k, v in after.items()} == {k: v[0] for k, v in before.items()}  # no status moved
    assert {k: v for k, v in after.items() if k != ids["a"]} == {k: v for k, v in before.items() if k != ids["a"]}
    assert "ungrounded" in after[ids["a"]][1]  # ...although it plainly is ungrounded
    assert memory.verify_integrity() == []


def test_what_cleaning_says_about_the_text_stays_in_front_and_follows_an_edit(store, memory):
    user, = seed(store, ("user", "I like tea"))
    text = "Here are the facts: " + "x" * 200
    fact_id = candidate(memory, text, user, user, flags=["preamble", "too_long"])
    memory.run_checks()
    memory.run_checks()
    assert flags_of(memory, fact_id) == ["preamble", "too_long", "ungrounded"]  # in front, and stable

    memory.edit(fact_id, "likes tea", "cli")  # no longer an introduction, no longer too long
    memory.run_checks()
    assert flags_of(memory, fact_id) == [f"source_message:{user}"]
    memory.edit(fact_id, "y" * (diya_memory.MAX_FACT_CHARS + 1), "cli")
    memory.run_checks()
    assert flags_of(memory, fact_id)[0] == "too_long"  # and it comes back if the text does


def test_a_candidate_whose_text_cleans_to_nothing_is_still_checked(store, memory):
    """"NONE" is a fact as far as the store is concerned (a clean line); cleaning would skip it as a line."""
    user, = seed(store, ("user", "I like tea"))
    fact_id = candidate(memory, "NONE", user, user)
    assert memory.run_checks() == (1, 1)
    assert flags_of(memory, fact_id) == ["ungrounded"]


def test_the_flags_follow_the_other_facts_as_they_change(store, memory):
    user, = seed(store, ("user", "I like green tea"))
    accepted = memory.add_manual("likes green tea", "cli")
    fact_id = candidate(memory, "likes green tea", user, user)

    memory.run_checks()
    assert flags_of(memory, fact_id) == [f"source_message:{user}", f"duplicate:{accepted}"]

    memory.decide(accepted, "retire", "cli")  # the accepted copy goes away: it is no longer a duplicate of anything
    assert memory.run_checks() == (1, 1)
    assert flags_of(memory, fact_id) == [f"source_message:{user}"]

    twin = candidate(memory, "Likes Green Tea", user, user, position=1)
    memory.run_checks()
    assert flags_of(memory, twin) == [f"source_message:{user}", f"duplicate:{fact_id}"]  # the later one is the repeat
    assert flags_of(memory, fact_id) == [f"source_message:{user}"]

    memory.decide(twin, "reject", "cli")
    again = candidate(memory, "likes green tea!", user, user, position=2)
    other_twin = candidate(memory, "LIKES GREEN TEA", user, user, position=3)
    memory.run_checks()
    assert f"previously_rejected:{twin}" in flags_of(memory, other_twin)
    assert again


def test_the_whole_way_through_from_what_dreaming_staged(tmp_path):
    """The real producer, the real ingest, then the checks."""
    import dataclasses

    data = tmp_path / "data"
    data.mkdir()
    config = dataclasses.replace(
        diya_config.load_config(), db_path=str(data / "d.db"), dream_state_path=str(data / "s.json"),
        dream_log_path=str(data / "l.txt"), dream_pending_path=str(data / "q.jsonl"), profile_path=str(data / "p.txt"),
    )
    store = Store(config.db_path)
    (user, ) = seed(store, ("user", "I adopted a cat named Pixel and I love green tea"))
    Dreamer(config, client=FakeClient([text_reply("- has a cat named Pixel\n- likes green tea\n- is a doctor")]), store=store).dream_cycle()
    memory = Memory(store)
    ingest_queue(memory, config)

    memory.run_checks()

    cat, tea, doctor = memory.facts()
    assert flags_of(memory, cat["id"]) == [f"source_message:{user}"]
    assert flags_of(memory, tea["id"]) == [f"source_message:{user}"]
    assert flags_of(memory, doctor["id"]) == ["ungrounded"]
    assert [f["status"] for f in memory.facts()] == ["candidate"] * 3


# --- set_flags ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["candidate", "accepted", "rejected", "retired"])
def test_set_flags_changes_the_flags_and_never_the_status(memory, status):
    fact_id = memory.add_candidate("likes tea", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- likes tea")
    for action in {"candidate": [], "accepted": ["accept"], "rejected": ["reject"], "retired": ["accept", "retire"]}[status]:
        memory.decide(fact_id, action, "cli")
    assert memory.set_flags(fact_id, ["ungrounded"], "api") is True
    assert memory.get(fact_id)["flags"] == ["ungrounded"] and memory.get(fact_id)["status"] == status
    *_, (event, actor, _at, detail) = memory.events(fact_id)
    assert (event, actor, json.loads(detail)) == ("flagged", "api", {"from": [], "to": ["ungrounded"]})
    assert memory.verify_integrity() == []


def test_setting_the_same_flags_again_is_not_a_change(memory):
    fact_id = memory.add_manual("likes tea", "cli")
    assert memory.set_flags(fact_id, ["a"], "cli") is True
    count = len(memory.events(fact_id))
    assert memory.set_flags(fact_id, ["a"], "cli") is False
    assert memory.set_flags(fact_id, ("a",), "cli") is False  # a tuple is the same list
    assert len(memory.events(fact_id)) == count
    assert memory.set_flags(fact_id, [], "cli") is True  # clearing is a change


@pytest.mark.parametrize("bad", ["ungrounded", None, [1], ["ok", None], {"a": 1}, 5])
def test_flags_are_a_list_of_text(memory, bad):
    fact_id = memory.add_manual("likes tea", "cli")
    with pytest.raises(InvalidFact):
        memory.set_flags(fact_id, bad, "cli")
    assert memory.get(fact_id)["flags"] == []


def test_set_flags_refuses_an_unknown_fact_and_an_unknown_actor(memory):
    with pytest.raises(UnknownFact):
        memory.set_flags(99, [], "cli")
    fact_id = memory.add_manual("likes tea", "cli")
    with pytest.raises(ValueError):
        memory.set_flags(fact_id, ["x"], "somebody")
    assert memory.get(fact_id)["flags"] == []


def test_a_flag_whose_event_cannot_be_written_is_not_left_behind(store, memory):
    fact_id = memory.add_manual("likes tea", "cli")
    conn = store.connect()
    conn.execute("CREATE TRIGGER explode BEFORE INSERT ON fact_events WHEN NEW.event = 'flagged' "
                 "BEGIN SELECT RAISE(ABORT, 'no'); END")
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        memory.set_flags(fact_id, ["ungrounded"], "cli")
    assert memory.get(fact_id)["flags"] == []


def test_a_history_that_begins_with_a_flag_is_not_a_fact_that_was_ever_created(store, memory):
    fact_id = memory.add_manual("likes tea", "cli")
    conn = store.connect()
    conn.execute("UPDATE fact_events SET event = 'flagged' WHERE fact_id = ?", (fact_id,))
    conn.commit()
    conn.close()
    assert any("events say None" in p for p in memory.verify_integrity())


# --- the messages a batch came from -----------------------------------------------------------------

def test_messages_between_two_ids_are_inclusive_ordered_and_span_threads(store):
    ids = seed(store, ("user", "one"), ("assistant", "two"))
    later = seed(store, ("user", "three"), ("user", "four"))
    got = store.get_messages_between(ids[1], later[0])
    assert [(m["content"], m["role"]) for m in got] == [("two", "assistant"), ("three", "user")]
    assert got[0]["thread_id"] != got[1]["thread_id"]  # a batch is read across every thread
    assert [m["content"] for m in store.get_messages_between(ids[0], later[1])] == ["one", "two", "three", "four"]
    assert [m["content"] for m in store.get_messages_between(later[1], later[1])] == ["four"]
    assert store.get_messages_between(later[1], ids[0]) == []  # backwards is empty, not an error
    assert store.get_messages_between(500, 600) == []
