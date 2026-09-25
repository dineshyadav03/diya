"""diya_memory.py: the store reviewed memory lives in (docs/STAGE2_DESIGN.md, section 3 and unit 1).

What this proves: a fact moves only along the legal transitions, and every move is one transaction
that changes the status AND records the event; nothing but an `accepted` fact is ever rendered for the
model; the duplicate and size limits hold even when two processes try at once; and nothing that is not
canonical text (no line break, no escape sequence, no bidirectional override) can be stored.
"""
import json
import random
import sqlite3
import threading

import pytest

import diya_memory
from diya_db import Store, apply_migrations
from diya_memory import (
    BudgetExceeded,
    DuplicateFact,
    FactError,
    IllegalTransition,
    InvalidFact,
    Memory,
    UnknownFact,
    check_text,
    render_profile,
)

STAGED_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "memory.db"))


@pytest.fixture
def memory(store):
    return Memory(store)


class Maker:
    """Facts in whatever status a test needs, each in its own queue slot."""

    PATH = {"candidate": [], "accepted": ["accept"], "rejected": ["reject"], "retired": ["accept", "retire"]}

    def __init__(self, memory):
        self.memory = memory
        self.n = 0

    def candidate(self, text=None, **extra):
        self.n += 1
        text = text or f"fictional fact number {self.n}"
        return self.memory.add_candidate(
            text, batch_first=self.n, batch_last=self.n + 1, position=0, model="qwen2.5:3b",
            extracted_at=STAGED_AT, raw="- " + text, **extra,
        )

    def in_status(self, status, text=None):
        fact_id = self.candidate(text)
        for action in self.PATH[status]:
            self.memory.decide(fact_id, action, "cli")
        return fact_id


@pytest.fixture
def make(memory):
    return Maker(memory)


def snapshot(memory):
    """Everything observable about the store, to prove a refused change changed nothing."""
    return memory.facts(), {f["id"]: memory.events(f["id"]) for f in memory.facts()}


def event_names(memory, fact_id):
    return [event for event, _actor, _at, _detail in memory.events(fact_id)]


# --- importing is free ----------------------------------------------------------------------------

def test_importing_the_module_has_no_side_effects(run_python, tmp_path):
    result = run_python("import diya_memory, os; print(sorted(os.listdir('.')))")
    assert result.returncode == 0 and result.stdout.strip() == "[]", result.stderr


def test_the_size_limits_are_the_ones_the_design_proposes():
    """Starting points, pinned so that moving one is a deliberate change (design doc, D7)."""
    assert (diya_memory.MAX_FACT_CHARS, diya_memory.MAX_PROFILE_CHARS) == (200, 2000)


# --- what text may be stored ----------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "likes tea", "has a cat named Pixel", "café owner", "Zoë's birthday is in May",
    "山田 lives in Osaka", "a family \U0001F468‍\U0001F469‍\U0001F467 photo",  # joiners are legitimate
    "x", "a" * 500,  # length is a rule of accepting, not of what may be recorded
])
def test_ordinary_text_is_a_fact(text):
    check_text(text)


@pytest.mark.parametrize("text", [
    "", " ", " leading", "trailing ", "two  spaces", "a\nb", "a\rb", "a\r\nb", "a\tb", "a b",
    "esc \x1b[31mred", "nul \x00 byte", "bell \x07", "del \x7f", "c1 \x85 control",
    "a b", "a b",
    "bidi ‮override", "bidi ⁦isolate", "left-to-right ‎mark", "arabic letter ؜mark",
    "zero​width", "word⁠joiner", "﻿bom", "lone \ud800 surrogate", "private  use",
])
def test_anything_that_is_not_one_clean_line_is_refused(text):
    with pytest.raises(InvalidFact):
        check_text(text)


@pytest.mark.parametrize("value", [None, 5, b"bytes", ["a"], 1.5])
def test_a_fact_is_text(value):
    with pytest.raises(InvalidFact):
        check_text(value)


def test_the_refusal_never_repeats_the_offending_text_raw():
    """An error message is printed to a terminal too."""
    with pytest.raises(InvalidFact) as caught:
        check_text("\x1b[2Jgotcha  ")
    assert "\x1b" not in str(caught.value)


def test_rendering_is_the_bullet_lines_the_model_has_always_been_given():
    assert render_profile([]) == ""
    assert render_profile(["a"]) == "- a"
    assert render_profile(["a", "b c"]) == "- a\n- b c"


# --- adding a candidate ---------------------------------------------------------------------------

def test_a_candidate_is_recorded_with_where_it_came_from_and_an_event(memory):
    fact_id = memory.add_candidate(
        "has a cat named Pixel", batch_first=4, batch_last=9, position=2, model="qwen2.5:3b",
        extracted_at=STAGED_AT, raw="- has a cat named Pixel", flags=["ungrounded"],
    )
    fact = memory.get(fact_id)
    assert {k: fact[k] for k in ("text", "status", "source", "batch_first", "batch_last", "position", "model",
                                  "extracted_at", "raw", "flags")} == {
        "text": "has a cat named Pixel", "status": "candidate", "source": "dreaming", "batch_first": 4,
        "batch_last": 9, "position": 2, "model": "qwen2.5:3b", "extracted_at": STAGED_AT,
        "raw": "- has a cat named Pixel", "flags": ["ungrounded"],
    }
    assert fact["created_at"]
    ((event, actor, at, detail),) = memory.events(fact_id)
    assert (event, actor, detail) == ("ingested", "system", None) and at
    assert memory.accepted_texts() == []  # a candidate is not something the model is told


def test_the_same_queue_slot_is_recorded_once_and_never_overwritten(memory):
    first = memory.add_candidate("original wording", batch_first=1, batch_last=1, position=0, model="m",
                                 extracted_at=STAGED_AT, raw="- original wording")
    again = memory.add_candidate("different wording", batch_first=1, batch_last=1, position=0, model="m",
                                 extracted_at=STAGED_AT, raw="- different wording")
    assert first is not None and again is None
    assert [f["text"] for f in memory.facts()] == ["original wording"]
    assert event_names(memory, first) == ["ingested"]
    # another position in the same record, and the same position in another record, are other slots
    assert memory.add_candidate("second", batch_first=1, batch_last=1, position=1, model="m", extracted_at=STAGED_AT, raw="- second")
    assert memory.add_candidate("third", batch_first=2, batch_last=2, position=0, model="m", extracted_at=STAGED_AT, raw="- third")


@pytest.mark.parametrize("bad", [
    {"batch_first": None}, {"batch_first": True}, {"batch_first": "1"}, {"batch_first": 1.0},
    {"batch_last": None}, {"batch_last": False}, {"batch_last": 0},  # last before first
    {"position": None}, {"position": -1}, {"position": True},
    {"raw": None}, {"model": None}, {"extracted_at": None}, {"flags": [1]}, {"flags": ["ok", None]},
    {"text": "two\nlines"}, {"text": ""},
])
def test_a_candidate_that_could_not_be_told_apart_or_traced_is_refused_and_writes_nothing(memory, bad):
    """A NULL slot would slip past the one-per-slot rule, so a slot must be whole integers."""
    fields = dict(text="fine", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- fine")
    fields.update(bad)
    with pytest.raises(InvalidFact):
        memory.add_candidate(**fields)
    assert memory.facts() == []


def test_an_unknown_actor_is_refused_everywhere_and_writes_nothing(memory, make):
    fact_id = make.candidate()
    before = snapshot(memory)
    with pytest.raises(ValueError):
        memory.decide(fact_id, "accept", "somebody")
    with pytest.raises(ValueError):
        memory.edit(fact_id, "reworded", "somebody")
    with pytest.raises(ValueError):
        memory.add_manual("typed", "somebody")
    with pytest.raises(ValueError):
        memory.add_candidate("x", batch_first=9, batch_last=9, position=0, model="m", extracted_at=STAGED_AT, raw="- x", actor="somebody")
    assert snapshot(memory) == before


# --- the state machine ----------------------------------------------------------------------------

LEGAL = {
    ("candidate", "accept"): "accepted",
    ("candidate", "reject"): "rejected",
    ("rejected", "reopen"): "candidate",
    ("accepted", "retire"): "retired",
    ("retired", "restore"): "accepted",
}
EVENT = {"accept": "accepted", "reject": "rejected", "reopen": "reopened", "retire": "retired", "restore": "restored"}


@pytest.mark.parametrize("status", ["candidate", "accepted", "rejected", "retired"])
@pytest.mark.parametrize("action", ["accept", "reject", "reopen", "retire", "restore"])
def test_every_status_against_every_action(memory, make, status, action):
    fact_id = make.in_status(status)
    before = snapshot(memory)
    if (status, action) in LEGAL:
        memory.decide(fact_id, action, "api")
        assert memory.get(fact_id)["status"] == LEGAL[(status, action)]
        *_, (event, actor, _at, detail) = memory.events(fact_id)
        assert (event, actor, detail) == (EVENT[action], "api", None)
        assert len(memory.events(fact_id)) == len(before[1][fact_id]) + 1  # exactly one event
    else:
        with pytest.raises(IllegalTransition):
            memory.decide(fact_id, action, "api")
        assert snapshot(memory) == before  # a refused change changed nothing


def test_a_fact_can_go_round_every_loop_and_its_history_says_so(memory, make):
    fact_id = make.candidate()
    for action in ("reject", "reopen", "accept", "retire", "restore", "retire", "restore"):
        memory.decide(fact_id, action, "cli")
    assert event_names(memory, fact_id) == [
        "ingested", "rejected", "reopened", "accepted", "retired", "restored", "retired", "restored",
    ]
    assert memory.get(fact_id)["status"] == "accepted"
    assert memory.verify_integrity() == []


def test_an_unknown_fact_or_action_is_refused(memory, make):
    fact_id = make.candidate()
    before = snapshot(memory)
    for call in (lambda: memory.decide(999, "accept", "cli"), lambda: memory.edit(999, "x", "cli"), lambda: memory.get(999)):
        with pytest.raises(UnknownFact):
            call()
    for action in ("approve", "", None, "ACCEPT"):
        with pytest.raises(ValueError):
            memory.decide(fact_id, action, "cli")
    assert snapshot(memory) == before


# --- editing --------------------------------------------------------------------------------------

def test_a_candidate_can_be_reworded_and_the_old_wording_is_kept_in_its_history(memory, make):
    fact_id = make.candidate("likes tea")
    memory.edit(fact_id, "likes green tea", "cli")
    assert memory.get(fact_id)["text"] == "likes green tea"
    assert memory.get(fact_id)["raw"] == "- likes tea"  # what the model said is never rewritten
    *_, (event, actor, _at, detail) = memory.events(fact_id)
    assert (event, actor, json.loads(detail)) == ("edited", "cli", {"from": "likes tea"})
    assert memory.get(fact_id)["status"] == "candidate"  # editing is not deciding
    assert memory.verify_integrity() == []


@pytest.mark.parametrize("status", ["accepted", "rejected", "retired"])
def test_only_a_candidate_can_be_edited(memory, make, status):
    fact_id = make.in_status(status, "original")
    before = snapshot(memory)
    with pytest.raises(IllegalTransition):
        memory.edit(fact_id, "reworded", "cli")
    assert snapshot(memory) == before


def test_an_edit_to_something_that_is_not_a_clean_line_is_refused(memory, make):
    fact_id = make.candidate("original")
    before = snapshot(memory)
    for bad in ("", "two\nlines", "esc \x1b[0m", "  padded  "):
        with pytest.raises(InvalidFact):
            memory.edit(fact_id, bad, "cli")
    assert snapshot(memory) == before


def test_editing_changes_what_counts_as_a_duplicate(memory, make):
    make.in_status("accepted", "likes tea")
    other = make.candidate("likes coffee")
    memory.edit(other, "Likes Tea", "cli")  # now the same fact as the accepted one, in other capitals
    with pytest.raises(DuplicateFact):
        memory.decide(other, "accept", "cli")


# --- accepting: duplicates, and size --------------------------------------------------------------

def test_the_same_fact_cannot_be_accepted_twice_however_it_is_capitalised(memory, make):
    first, second = make.candidate("Likes tea"), make.candidate("likes TEA")
    memory.decide(first, "accept", "cli")
    before = snapshot(memory)
    with pytest.raises(DuplicateFact) as caught:
        memory.decide(second, "accept", "cli")
    assert str(first) in str(caught.value)
    assert snapshot(memory) == before
    assert memory.accepted_texts() == ["Likes tea"]


def test_a_repeat_is_only_a_problem_once_both_would_be_accepted(memory, make):
    make.in_status("retired", "likes tea")  # made first: getting to "retired" means being accepted on the way
    make.in_status("rejected", "likes tea")
    make.candidate("likes tea")
    first = make.in_status("accepted", "likes tea")
    assert memory.accepted_texts() == ["likes tea"]  # three other copies, none of them accepted
    memory.decide(first, "retire", "cli")
    assert memory.accepted_texts() == []


def test_a_retired_fact_cannot_come_back_while_an_accepted_one_says_the_same(memory, make):
    retired = make.in_status("retired", "likes tea")
    replacement = make.in_status("accepted", "likes tea")
    before = snapshot(memory)
    with pytest.raises(DuplicateFact):
        memory.decide(retired, "restore", "cli")
    assert snapshot(memory) == before
    memory.decide(replacement, "retire", "cli")
    memory.decide(retired, "restore", "cli")  # now nothing stands in the way
    assert memory.accepted_texts() == ["likes tea"]


def test_a_fact_over_the_per_fact_limit_cannot_be_accepted_until_it_is_edited_shorter(memory, make):
    limit = diya_memory.MAX_FACT_CHARS
    fits = make.candidate("a" * limit)
    too_long = make.candidate("b" * (limit + 1))
    memory.decide(fits, "accept", "cli")  # exactly at the limit is fine
    before = snapshot(memory)
    with pytest.raises(InvalidFact) as caught:
        memory.decide(too_long, "accept", "cli")
    assert str(limit + 1) in str(caught.value)
    assert snapshot(memory) == before
    memory.edit(too_long, "b" * limit, "cli")
    memory.decide(too_long, "accept", "cli")


def test_restoring_is_not_held_to_the_per_fact_limit_but_is_held_to_the_total(memory, store, monkeypatch):
    """A fact that came in with the old profile can be longer than a new fact may be. Retiring it must
    not make it impossible to bring back."""
    long_text = "c" * (diya_memory.MAX_FACT_CHARS + 50)
    conn = store.connect()
    conn.execute("INSERT INTO facts (text, text_key, status, source, created_at) VALUES (?, ?, 'retired', 'legacy_profile', 'now')",
                 (long_text, long_text.casefold()))
    conn.execute("INSERT INTO fact_events (fact_id, event, actor, at) VALUES (1, 'imported', 'import', 'now'), (1, 'retired', 'cli', 'now')")
    conn.commit()
    conn.close()
    memory = Memory(store)
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", len(long_text) + 1)  # one short of fitting
    with pytest.raises(BudgetExceeded):
        memory.decide(1, "restore", "cli")
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", len(render_profile([long_text])))
    memory.decide(1, "restore", "cli")
    assert memory.accepted_texts() == [long_text]


def test_the_profile_total_is_measured_on_what_the_model_is_sent(memory, make, monkeypatch):
    """Two facts of a and b characters render as (2 + a) + 1 + (2 + b): bullets and the line break count."""
    first, second = "a" * 30, "b" * 40
    exactly = len(render_profile([first, second]))
    assert exactly == 30 + 40 + 5
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", exactly)
    one, two = make.candidate(first), make.candidate(second)
    memory.decide(one, "accept", "cli")
    memory.decide(two, "accept", "cli")  # exactly at the limit: accepted
    assert len(memory.render()) == exactly

    third = make.candidate("c")
    before = snapshot(memory)
    with pytest.raises(BudgetExceeded) as caught:  # one character more than fits, plus its bullet and line break
        memory.decide(third, "accept", "cli")
    assert str(exactly) in str(caught.value) and "Retire a fact first" in str(caught.value)
    assert snapshot(memory) == before
    memory.decide(one, "retire", "cli")  # room is made by retiring, and then it fits
    memory.decide(third, "accept", "cli")
    with pytest.raises(BudgetExceeded):  # ...and bringing the retired one back no longer does
        memory.decide(one, "restore", "cli")


def test_one_character_over_the_total_is_refused(memory, make, monkeypatch):
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", len(render_profile(["d" * 10])) - 1)
    with pytest.raises(BudgetExceeded):
        memory.decide(make.candidate("d" * 10), "accept", "cli")


# --- typing a fact yourself -----------------------------------------------------------------------

def test_a_typed_fact_goes_in_already_accepted_and_is_held_to_the_same_limits(memory, monkeypatch):
    fact_id = memory.add_manual("works in the evenings", "cli")
    fact = memory.get(fact_id)
    assert (fact["status"], fact["source"], fact["batch_first"], fact["raw"]) == ("accepted", "manual", None, None)
    assert event_names(memory, fact_id) == ["added"]
    assert memory.accepted_texts() == ["works in the evenings"]

    before = snapshot(memory)
    with pytest.raises(DuplicateFact):
        memory.add_manual("Works In The Evenings", "cli")
    with pytest.raises(InvalidFact):
        memory.add_manual("z" * (diya_memory.MAX_FACT_CHARS + 1), "cli")
    with pytest.raises(InvalidFact):
        memory.add_manual("two\nlines", "cli")
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", len(memory.render()))
    with pytest.raises(BudgetExceeded):
        memory.add_manual("one more", "cli")
    assert snapshot(memory) == before
    assert memory.verify_integrity() == []


# --- what the model may be told -------------------------------------------------------------------

def test_only_accepted_facts_are_ever_rendered_oldest_first(memory, make):
    make.in_status("candidate", "still a candidate")
    third = make.in_status("accepted", "accepted third")
    make.in_status("rejected", "was rejected")
    make.in_status("retired", "was retired")
    first = make.in_status("accepted", "accepted fourth")
    memory.decide(third, "retire", "cli")
    memory.decide(third, "restore", "cli")  # keeps its place: order is by id, not by when it was decided
    assert memory.accepted_texts() == ["accepted third", "accepted fourth"]
    assert memory.render() == "- accepted third\n- accepted fourth"
    for hidden in ("still a candidate", "was rejected", "was retired"):
        assert hidden not in memory.render()
    assert first  # (silence the unused name; the id is what it is)


def test_nothing_accepted_renders_as_nothing(memory, make):
    assert memory.render() == "" and memory.accepted_texts() == []
    make.candidate("only a candidate")
    assert memory.render() == ""


def test_facts_can_be_listed_by_status_and_counted(memory, make):
    make.in_status("candidate"), make.in_status("candidate"), make.in_status("accepted"), make.in_status("rejected")
    assert [f["status"] for f in memory.facts()] == ["candidate", "candidate", "accepted", "rejected"]
    assert [f["status"] for f in memory.facts("candidate")] == ["candidate", "candidate"]
    assert memory.facts("retired") == []
    assert memory.counts() == {"candidate": 2, "accepted": 1, "rejected": 1, "retired": 0}
    with pytest.raises(ValueError):
        memory.facts("pending")


# --- one transaction per change -------------------------------------------------------------------

def _trigger_failing_on(store, event):
    conn = store.connect()
    conn.execute(
        f"CREATE TRIGGER explode BEFORE INSERT ON fact_events WHEN NEW.event = '{event}' "
        "BEGIN SELECT RAISE(ABORT, 'the event could not be written'); END"
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize("action, start, event", [
    ("accept", "candidate", "accepted"), ("reject", "candidate", "rejected"), ("reopen", "rejected", "reopened"),
    ("retire", "accepted", "retired"), ("restore", "retired", "restored"),
])
def test_a_change_whose_event_cannot_be_written_leaves_the_status_alone(store, memory, make, action, start, event):
    """The status and the event are one transaction: if the second write fails the first is undone,
    not left as a status with no explanation."""
    fact_id = make.in_status(start)
    before = snapshot(memory)
    _trigger_failing_on(store, event)
    with pytest.raises(sqlite3.DatabaseError):
        memory.decide(fact_id, action, "cli")
    assert snapshot(memory) == before
    assert memory.verify_integrity() == []


def test_an_edit_whose_event_cannot_be_written_keeps_the_old_wording(store, memory, make):
    fact_id = make.candidate("old wording")
    before = snapshot(memory)
    _trigger_failing_on(store, "edited")
    with pytest.raises(sqlite3.DatabaseError):
        memory.edit(fact_id, "new wording", "cli")
    assert snapshot(memory) == before


@pytest.mark.parametrize("event, call", [
    ("ingested", lambda m: m.add_candidate("x", batch_first=1, batch_last=1, position=0, model="m", extracted_at=STAGED_AT, raw="- x")),
    ("added", lambda m: m.add_manual("x", "cli")),
])
def test_a_new_fact_whose_event_cannot_be_written_is_not_left_behind_without_history(store, memory, event, call):
    _trigger_failing_on(store, event)
    with pytest.raises(sqlite3.DatabaseError):
        call(memory)
    assert memory.facts() == []


# --- two processes at once ------------------------------------------------------------------------

class HookedStore(Store):
    """A store whose connections report every statement they start, so a test can let a rival in at an
    exact moment (the same technique as the migration-runner tests)."""

    def __init__(self, path, on_statement):
        super().__init__(path)
        self.on_statement = on_statement

    def connect(self):
        conn = super().connect()
        conn.set_trace_callback(self.on_statement)
        return conn


class ImpatientStore(Store):
    """Gives up at once when the file is locked, instead of waiting."""

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=0)
        apply_migrations(conn)
        return conn


def _room_for_exactly_one(monkeypatch, make):
    first, second = "e" * 40, "f" * 40
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", len(render_profile([first])) + 5)  # one fits, two do not
    return make.candidate(first), make.candidate(second)


def test_a_rival_cannot_get_in_between_checking_for_room_and_accepting(tmp_path, monkeypatch):
    """Room for one fact, two candidates. While the first is being accepted -- after it has decided
    there is room, before it has written -- the second tries to be accepted too. The write lock has to
    be held from the start, so the rival is turned away and the limit holds."""
    path = str(tmp_path / "race.db")
    rival_outcome = []
    rival = Memory(ImpatientStore(path))
    ids = {}

    def on_statement(sql):
        if sql.startswith("UPDATE facts SET status") and not rival_outcome:
            try:
                rival.decide(ids["second"], "accept", "cli")
                rival_outcome.append("accepted")
            except sqlite3.OperationalError:
                rival_outcome.append("locked out")
            except FactError as exc:
                rival_outcome.append(type(exc).__name__)

    me = Memory(HookedStore(path, on_statement))
    ids["first"], ids["second"] = _room_for_exactly_one(monkeypatch, Maker(me))

    me.decide(ids["first"], "accept", "cli")

    assert rival_outcome == ["locked out"], "the rival was not turned away while the write was in progress"
    assert len(me.accepted_texts()) == 1
    assert len(me.render()) <= diya_memory.MAX_PROFILE_CHARS
    with pytest.raises(BudgetExceeded):  # and once the first is in, the second is properly told there is no room
        me.decide(ids["second"], "accept", "cli")
    assert me.verify_integrity() == []


@pytest.mark.parametrize("round_no", range(15))
def test_two_threads_accepting_at_once_never_take_the_profile_over_its_limit(tmp_path, monkeypatch, round_no):
    memory = Memory(Store(str(tmp_path / "threads.db")))
    first, second = _room_for_exactly_one(monkeypatch, Maker(memory))
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(fact_id):
        try:
            barrier.wait()
            memory.decide(fact_id, "accept", "cli")
            outcomes.append("accepted")
        except BudgetExceeded:
            outcomes.append("no room")

    threads = [threading.Thread(target=worker, args=(i,)) for i in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["accepted", "no room"]
    assert len(memory.render()) <= diya_memory.MAX_PROFILE_CHARS


def test_two_threads_accepting_the_same_words_at_once_leave_exactly_one_accepted(tmp_path):
    memory = Memory(Store(str(tmp_path / "twins.db")))
    make = Maker(memory)
    ids = [make.candidate("Likes tea"), make.candidate("likes tea")]
    barrier = threading.Barrier(2)
    outcomes = []

    def worker(fact_id):
        try:
            barrier.wait()
            memory.decide(fact_id, "accept", "cli")
            outcomes.append("accepted")
        except DuplicateFact:
            outcomes.append("duplicate")

    threads = [threading.Thread(target=worker, args=(i,)) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["accepted", "duplicate"]
    assert memory.verify_integrity() == []


# --- checking the store checks itself -------------------------------------------------------------

def test_a_store_that_has_only_been_used_through_memory_is_sound_after_any_sequence_of_changes(memory, make):
    rng = random.Random(20260925)
    ids = [make.candidate(f"fictional fact {i}") for i in range(6)]
    happened = set()
    for _ in range(400):
        fact_id = rng.choice(ids)
        action = rng.choice(list(EVENT))
        try:
            memory.decide(fact_id, action, rng.choice(["cli", "api"]))
            happened.add(action)
        except IllegalTransition:
            pass
        assert memory.verify_integrity() == []
    assert happened == set(EVENT)  # every action really was applied along the way, not just refused
    accepted = [f["text"] for f in memory.facts() if f["status"] == "accepted"]
    assert memory.accepted_texts() == accepted


def _tamper(store, sql, *args):
    conn = store.connect()
    conn.execute(sql, args)
    conn.commit()
    conn.close()


@pytest.mark.parametrize("damage, expect", [
    ("UPDATE facts SET status = 'accepted' WHERE id = 1", "events say candidate"),  # status moved with no event
    ("DELETE FROM fact_events WHERE fact_id = 1", "has no events"),
    ("INSERT INTO fact_events (fact_id, event, actor, at) VALUES (99, 'accepted', 'cli', 'now')", "does not exist"),
    ("INSERT INTO fact_events (fact_id, event, actor, at) VALUES (1, 'levitated', 'cli', 'now')", "unknown kind"),
    ("INSERT INTO fact_events (fact_id, event, actor, at) VALUES (1, 'edited', 'a ghost', 'now')", "unknown actor"),
    ("UPDATE facts SET text = 'reworded behind its back' WHERE id = 1", "identity does not match"),
    ("UPDATE facts SET text = 'esc ' || char(27) || '[0m', text_key = 'esc ' || char(27) || '[0m' WHERE id = 1", "cannot contain the character"),
    ("UPDATE fact_events SET event = 'edited' WHERE fact_id = 1", "events say None"),  # history that never creates the fact
])
def test_verify_integrity_finds_each_kind_of_damage(store, memory, make, damage, expect):
    make.candidate("fictional fact")
    assert memory.verify_integrity() == []
    _tamper(store, damage)
    problems = memory.verify_integrity()
    assert problems and any(expect in problem for problem in problems), problems


def test_verify_integrity_finds_two_accepted_facts_that_say_the_same_thing(store, memory, make):
    """The unique index makes this hard to reach, which is why the index is dropped to test the check."""
    make.in_status("accepted", "likes tea")
    make.in_status("accepted", "likes coffee")
    conn = store.connect()
    conn.execute("DROP INDEX facts_one_accepted_per_key")
    conn.execute("UPDATE facts SET text = 'likes tea', text_key = 'likes tea' WHERE id = 2")
    conn.commit()
    conn.close()
    assert any("say the same thing" in p for p in memory.verify_integrity())


def test_the_database_itself_refuses_a_second_accepted_copy_even_if_the_code_above_it_is_bypassed(store, memory, make):
    make.in_status("accepted", "likes tea")
    other = make.candidate("likes coffee")
    with pytest.raises(sqlite3.IntegrityError):
        _tamper(store, "UPDATE facts SET status = 'accepted', text = 'LIKES TEA', text_key = 'likes tea' WHERE id = ?", other)
