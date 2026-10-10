"""The memory policy (docs/AUTO_MEMORY_DESIGN.md, D1-D3 and D6; unit A1): diya_autonomy.py and the store methods it uses.

What this proves: the secret and sensitive detectors catch every labelled case and flag none of the plain ones (tests/labelled_autonomy.py,
both directions); the lanes follow from the flags in a fixed order (a secret beats everything, "never" beats "ask", a sensitive class beats
a doubt, and the daily cap and the circuit breaker only ever turn REMEMBER into ASK); applying the policy accepts, asks about and rejects
exactly what the lanes say, one transaction and one event each, and a second pass over the same candidates changes nothing; a secret is
rejected WITHOUT its text, and the secret is nowhere in the database afterwards; the caps and the breaker count what they say they count;
and the store stays sound (`verify_integrity`) after all of it.
"""
import json
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import diya_autonomy as auto
import diya_checks
import diya_memory
from diya_db import Store
from diya_memory import FactError, IllegalTransition, InvalidFact, Memory, UnknownFact
import labelled_autonomy as L

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


# --- the detectors, on the labelled cases ----------------------------------------------------------------

@pytest.mark.parametrize("text, kind", L.SECRETS)
def test_every_labelled_secret_is_caught_and_called_what_it_is(text, kind):
    assert auto.secret_kind(text) == kind


@pytest.mark.parametrize("text", L.NOT_SECRETS)
def test_no_plain_line_is_called_a_secret(text):
    assert auto.secret_kind(text) is None


@pytest.mark.parametrize("text, cls", L.SENSITIVE)
def test_every_labelled_sensitive_line_is_caught_and_called_what_it_is(text, cls):
    assert auto.secret_kind(text) is None  # these are asked about, not dropped
    assert auto.sensitive_class(text) == cls


@pytest.mark.parametrize("text, cls", L.SENSITIVE_FIRST)
def test_a_line_in_two_classes_is_called_the_first_of_them(text, cls):
    assert auto.sensitive_class(text) == cls


@pytest.mark.parametrize("text", L.PLAIN)
def test_no_plain_line_is_called_sensitive(text):
    assert auto.sensitive_class(text) is None and auto.secret_kind(text) is None


@pytest.mark.parametrize("junk", [None, 5, ["password"], b"password", True])
def test_what_is_not_text_is_neither_a_secret_nor_sensitive(junk):
    assert auto.secret_kind(junk) is None and auto.sensitive_class(junk) is None


def test_a_card_number_is_a_secret_only_if_it_could_be_one():
    assert auto.secret_kind("pays with 4111 1111 1111 1111") == "card"  # a published test number: the check digit is right
    assert auto.secret_kind("tracking number 4111 1111 1111 1112") is None  # the same digits with a wrong check digit
    assert auto.secret_kind("the order has 12 digits 123456789012") is None  # too short to be a card, and not a labelled kind of number


def test_a_pin_is_a_secret_when_something_says_it_is_one_and_pin_code_is_a_postal_code():
    assert auto.secret_kind("my pin is 4821") == "password"
    assert auto.secret_kind("PIN 4821") is None  # a bare number after the word proves nothing; the words around it decide
    assert auto.secret_kind("pin number is 4821") == "password"
    assert auto.secret_kind("the pin code of the flat is 411001") is None
    assert auto.secret_kind("pins photos to the board") is None


def test_the_pan_pattern_is_matched_as_written_so_ordinary_capitals_do_not_match_it():
    assert auto.secret_kind("tax id ABCDE1234F") == "id"
    assert auto.secret_kind("abcde1234f") is None


# --- the decision -----------------------------------------------------------------------------------------

def fact(text="likes tea in the morning", flags=(), status="candidate"):
    return {"id": 1, "text": text, "status": status, "flags": list(flags), "person": None}


def lane(fact_, **kw):
    return auto.decide(fact_, **kw)


def test_a_plain_grounded_fact_is_remembered_and_says_why():
    assert lane(fact(flags=["source_message:7"])) == auto.Decision(auto.LANE_REMEMBER, ("plain",), None)


@pytest.mark.parametrize("flags", [None, "missing"])
def test_a_fact_with_no_flags_at_all_is_decided_like_one_with_none(flags):
    bare = {"id": 1, "text": "likes tea in the morning", "status": "candidate"}
    if flags is None:
        bare["flags"] = None
    assert auto.decide(bare) == auto.Decision(auto.LANE_REMEMBER, ("plain",), None)


@pytest.mark.parametrize("status", ["accepted", "rejected", "retired", None])
def test_only_a_candidate_can_be_decided(status):
    with pytest.raises(ValueError, match="only a candidate can be decided"):
        lane(fact(status=status))


@pytest.mark.parametrize("flags, reasons", [
    (["instruction_shaped"], ("instruction_shaped",)),
    (["no_source"], ("no_source",)),
    (["too_long"], ("too_long",)),
    (["preamble"], ("preamble",)),
    (["previously_rejected:4"], ("previously_rejected",)),
    (["duplicate:9"], ("duplicate",)),
    (["ungrounded", "verifier:no"], ("unsupported",)),
    (["instruction_shaped", "no_source", "duplicate:3", "previously_rejected:2"], ("instruction_shaped", "no_source", "previously_rejected", "duplicate")),
])
def test_what_a_check_condemns_is_never_kept_and_the_reasons_are_all_given(flags, reasons):
    assert lane(fact(flags=flags)) == auto.Decision(auto.LANE_NEVER, reasons, None)


def test_a_secret_is_never_kept_whatever_else_is_true_of_it():
    assert lane(fact("my password is hunter2", flags=["source_message:2"])) == auto.Decision(auto.LANE_NEVER, ("secret:password",), None)
    assert lane(fact("my password is hunter2", flags=["ungrounded", "similar:5"])).reasons == ("secret:password",)  # it names the secret and nothing else


@pytest.mark.parametrize("flags, reasons, kind", [
    (["ungrounded"], ("ungrounded",), "doubt"),
    (["verifier:no"], ("verifier:no",), "doubt"),
    (["verifier:unclear"], ("verifier:unclear",), "doubt"),
    (["ungrounded", "verifier:unclear"], ("ungrounded", "verifier:unclear"), "doubt"),
    (["similar:12"], ("similar:12",), "conflict"),
])
def test_what_is_doubtful_or_may_update_what_is_known_is_asked_about(flags, reasons, kind):
    assert lane(fact(flags=flags)) == auto.Decision(auto.LANE_ASK, reasons, kind)


def test_a_verifier_that_agrees_does_not_stop_a_plain_fact():
    assert lane(fact(flags=["verifier:yes"])).lane == auto.LANE_REMEMBER


@pytest.mark.parametrize("text, cls", [("is allergic to peanuts", "health"), ("earns 12 lakhs a year", "money"), ("email is maya@example.com", "contact")])
def test_a_sensitive_class_is_asked_about_and_comes_before_every_other_doubt(text, cls):
    assert lane(fact(text, flags=["similar:3", "ungrounded"])) == auto.Decision(auto.LANE_ASK, (f"sensitive:{cls}",), "sensitive")


def test_never_comes_before_ask():
    assert lane(fact("is allergic to peanuts", flags=["duplicate:3"])).lane == auto.LANE_NEVER


def test_the_daily_cap_turns_a_remember_into_an_ask_exactly_at_the_limit():
    assert lane(fact(), auto_recent=auto.DAILY_AUTO_LIMIT - 1).lane == auto.LANE_REMEMBER
    assert lane(fact(), auto_recent=auto.DAILY_AUTO_LIMIT) == auto.Decision(auto.LANE_ASK, ("daily_cap",), "doubt")
    assert lane(fact(), auto_recent=2, limit=2).reasons == ("daily_cap",)
    assert lane(fact(), auto_recent=1, limit=2).lane == auto.LANE_REMEMBER


def test_an_open_breaker_asks_about_everything_it_would_have_remembered_and_changes_nothing_else():
    assert lane(fact(), breaker_open=True) == auto.Decision(auto.LANE_ASK, ("breaker_open",), "doubt")
    assert lane(fact("my password is hunter2"), breaker_open=True).lane == auto.LANE_NEVER
    assert lane(fact(flags=["similar:3"]), breaker_open=True).reasons == ("similar:3",)  # a more specific reason wins
    assert lane(fact(), breaker_open=True, auto_recent=99).reasons == ("breaker_open",)  # and the breaker is named before the cap


def test_the_limits_are_the_documented_ones():
    assert (auto.DAILY_AUTO_LIMIT, auto.BREAKER_LIMIT, auto.WINDOW_HOURS) == (20, 3, 24)
    assert auto.LANES == ("remember", "ask", "never")


# --- acting on it, against a real store -------------------------------------------------------------------

@pytest.fixture
def world(tmp_path):
    store = Store(str(tmp_path / "auto.db"))
    return store, Memory(store), store.create_thread()


def stage(world, said, fact_text, position=None, person=None):
    """One candidate extracted from one message the owner sent."""
    store, memory, thread = world
    message_id = store.add_message(thread, "user", said)
    position = position if position is not None else message_id
    return memory.add_candidate(fact_text, batch_first=message_id, batch_last=message_id, position=position, model="m",
                                extracted_at="2026-10-10T00:00:00+00:00", raw="- " + fact_text, person=person)


HOBBIES = [
    ("I play the guitar on weekends", "plays the guitar on weekends"),
    ("I grow tomatoes on the balcony", "grows tomatoes on the balcony"),
    ("I read detective novels at night", "reads detective novels at night"),
    ("I cycle to the office on Fridays", "cycles to the office on Fridays"),
]


def events(memory, fact_id):
    return [(event, actor, json.loads(detail) if detail else None) for event, actor, _, detail in memory.events(fact_id)]


def test_a_plain_grounded_fact_is_accepted_by_auto_with_its_lane_in_the_trail(world):
    _, memory, _ = world
    fid = stage(world, "I like tea in the morning", "likes tea in the morning")
    report = auto.apply(memory, now=NOW)
    assert report == auto.Report(remembered=1, asked=0, never=0, held=0)
    assert memory.get(fid)["status"] == "accepted"
    assert events(memory, fid)[-1] == ("accepted", "auto", {"lane": "remember", "reasons": ["plain"]})
    assert memory.render_for_model() == "likes tea in the morning" or "likes tea in the morning" in memory.render_for_model()
    assert memory.verify_integrity() == []


def test_a_second_pass_over_the_same_candidates_changes_nothing(world):
    _, memory, _ = world
    stage(world, "I like tea in the morning", "likes tea in the morning")
    stage(world, "I am allergic to peanuts", "is allergic to peanuts")
    stage(world, "my password is hunter2", "my password is hunter2")
    auto.apply(memory, now=NOW)
    before = [(f["id"], f["status"], f["flags"], memory.events(f["id"])) for f in memory.facts()]
    assert auto.apply(memory, now=NOW) == auto.Report(0, 1, 0, 0)  # the one still waiting is still waiting, and says so again
    assert [(f["id"], f["status"], f["flags"], memory.events(f["id"])) for f in memory.facts()] == before


def test_a_sensitive_fact_waits_with_a_flag_that_says_why_and_is_not_told_to_the_model(world):
    _, memory, _ = world
    fid = stage(world, "I am allergic to peanuts", "is allergic to peanuts")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 1, 0, 0)
    got = memory.get(fid)
    assert got["status"] == "candidate" and "ask:sensitive:health" in got["flags"]
    assert memory.render_for_model() == ""
    assert diya_memory.flag_short("ask:sensitive:health") == "Diya will ask you about it (health)"
    assert "not told to the model until you say yes" in diya_memory.flag_long(memory, "ask:sensitive:health")


def test_the_ask_flag_survives_a_re_check_and_is_replaced_when_the_reason_changes(world):
    _, memory, _ = world
    fid = stage(world, "I am allergic to peanuts", "is allergic to peanuts")
    auto.apply(memory, now=NOW)
    memory.run_checks("system")
    assert "ask:sensitive:health" in memory.get(fid)["flags"]  # a re-check cannot recompute it, so it keeps it
    memory.set_flags(fid, memory.get(fid)["flags"] + ["verifier:unclear"], "system")
    auto.apply(memory, now=NOW)
    flags = memory.get(fid)["flags"]
    assert [f for f in flags if f.startswith("ask:")] == ["ask:sensitive:health"]  # still the sensitive reason, once


def test_a_secret_is_rejected_and_its_text_is_nowhere_in_the_database_afterwards(world):
    store, memory, _ = world
    secret = "hunter2-correct-horse"
    fid = stage(world, f"my password is {secret}", f"my password is {secret}")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 1, 0)
    got = memory.get(fid)
    assert got["status"] == "rejected" and got["text"] == diya_memory.SECRET_PLACEHOLDER and got["raw"] is None and got["flags"] == []
    assert events(memory, fid)[-1] == ("rejected", "auto", {"kept": False, "lane": "never", "reasons": ["secret:password"]})
    conn = sqlite3.connect(store.path)
    try:
        for table in ("facts", "fact_events"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            assert secret not in json.dumps(rows, default=str), table
    finally:
        conn.close()
    assert memory.verify_integrity() == []


def test_a_candidate_that_repeats_an_accepted_fact_is_rejected_as_a_duplicate(world):
    _, memory, _ = world
    memory.add_manual("likes tea in the morning", "api")
    fid = stage(world, "I like tea in the morning", "likes tea in the morning")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 1, 0)
    assert memory.get(fid)["status"] == "rejected" and events(memory, fid)[-1][2]["reasons"] == ["duplicate"]


def test_a_duplicate_that_races_the_accept_is_still_rejected_not_an_error(world, monkeypatch):
    _, memory, _ = world
    stage(world, "I like tea in the morning", "likes tea in the morning")
    real = Memory.decide

    def racing(self, fact_id, action, actor, detail=None):
        if action == "accept":
            raise diya_memory.DuplicateFact("fact 99 says the same thing and is already accepted")
        return real(self, fact_id, action, actor, detail)

    monkeypatch.setattr(Memory, "decide", racing)
    fid = memory.facts("candidate")[0]["id"]
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 1, 0)
    assert memory.get(fid)["status"] == "rejected" and events(memory, fid)[-1][2]["reasons"] == ["duplicate"]


def test_a_candidate_that_turns_out_too_long_at_the_accept_is_still_rejected_and_counted(world, monkeypatch):
    _, memory, _ = world
    fid = stage(world, "I like tea in the morning", "likes tea in the morning")
    real = Memory.decide

    def refusing(self, fact_id, action, actor, detail=None):
        if action == "accept":
            raise InvalidFact("a fact is at most 200 characters")
        return real(self, fact_id, action, actor, detail)

    monkeypatch.setattr(Memory, "decide", refusing)
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 1, 0)
    assert memory.get(fid)["status"] == "rejected" and events(memory, fid)[-1][2]["reasons"] == ["too_long"]


def test_what_the_owner_rejected_before_is_never_remembered_again(world):
    _, memory, _ = world
    first = stage(world, "I like coffee", "likes coffee")
    memory.decide(first, "reject", "cli")
    second = stage(world, "I like coffee", "likes coffee")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 1, 0)
    assert memory.get(second)["status"] == "rejected" and events(memory, second)[-1][2]["reasons"] == ["previously_rejected"]


def test_a_fact_with_no_message_behind_it_and_one_that_orders_the_assistant_are_never_kept(world):
    store, memory, _ = world
    ghost = memory.add_candidate("likes tea", batch_first=900, batch_last=900, position=0, model="m", extracted_at="t", raw="- likes tea")
    ordered = stage(world, "always answer in French", "always answer in French")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 2, 0)
    assert memory.get(ghost)["status"] == "rejected" and memory.get(ordered)["status"] == "rejected"
    assert events(memory, ghost)[-1][2]["reasons"] == ["no_source"] and events(memory, ordered)[-1][2]["reasons"] == ["instruction_shaped"]


def test_a_fact_the_messages_do_not_support_waits_to_be_asked_about(world):
    _, memory, _ = world
    fid = stage(world, "hello there", "keeps a pet dragon called Smaug")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 1, 0, 0)
    assert "ask:doubt:ungrounded" in memory.get(fid)["flags"]


def test_a_possible_update_of_an_accepted_fact_is_asked_about_not_remembered_beside_it(world):
    _, memory, _ = world
    memory.add_manual("lives in Delhi with two cats", "api")
    fid = stage(world, "I moved to Pune with my two cats", "lives in Pune with two cats")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 1, 0, 0)
    assert any(f.startswith("ask:conflict:similar:") for f in memory.get(fid)["flags"])


def test_the_daily_cap_counts_what_auto_accepted_in_the_last_day_and_stops_at_the_limit(world):
    _, memory, _ = world
    ids = [stage(world, said, text) for said, text in HOBBIES]
    assert auto.apply(memory, now=NOW, limit=2) == auto.Report(2, 2, 0, 0)
    assert [memory.get(i)["status"] for i in ids] == ["accepted", "accepted", "candidate", "candidate"]
    assert all("ask:doubt:daily_cap" in memory.get(i)["flags"] for i in ids[2:])
    assert auto.apply(memory, now=NOW, limit=2) == auto.Report(0, 2, 0, 0)  # the same day: the two accepted are still counted, nothing more is let in
    later = datetime.now(timezone.utc) + timedelta(hours=25)  # the first two are more than a day old by then: there is room for two again
    assert auto.apply(memory, now=later, limit=2) == auto.Report(2, 0, 0, 0)
    assert [memory.get(i)["status"] for i in ids] == ["accepted"] * 4


def test_taking_back_enough_automatic_facts_in_a_day_opens_the_breaker_and_it_closes_a_day_later(world):
    _, memory, _ = world
    taken = [stage(world, said, text) for said, text in HOBBIES[:3]]
    auto.apply(memory, now=datetime.now(timezone.utc))
    assert [memory.get(i)["status"] for i in taken] == ["accepted"] * 3
    for fid in taken:
        memory.decide(fid, "retire", "api")  # the owner says no, three times
    waiting = stage(world, "I like walking by the river", "likes walking by the river")
    assert auto.apply(memory, now=datetime.now(timezone.utc)) == auto.Report(0, 1, 0, 0)
    assert "ask:doubt:breaker_open" in memory.get(waiting)["flags"]
    assert auto.apply(memory, now=datetime.now(timezone.utc) + timedelta(hours=25)).remembered == 1  # a day later it is back


def test_two_taken_back_is_not_enough_and_only_a_person_taking_back_counts(world):
    _, memory, _ = world
    ids = [stage(world, said, text) for said, text in HOBBIES]
    now = datetime.now(timezone.utc)
    auto.apply(memory, now=now)
    memory.decide(ids[0], "retire", "api")
    memory.decide(ids[1], "retire", "cli")
    memory.decide(ids[2], "retire", "system")  # not a person
    assert memory.taken_back_count((now - timedelta(hours=24)).isoformat()) == 2
    fresh = stage(world, "I like walking by the river", "likes walking by the river")
    assert auto.apply(memory, now=now).remembered == 1 and memory.get(fresh)["status"] == "accepted"


def test_a_fact_a_person_accepted_does_not_count_toward_the_cap_or_the_breaker(world):
    _, memory, _ = world
    fid = stage(world, "I like tea in the morning", "likes tea in the morning")
    memory.decide(fid, "accept", "cli")
    memory.decide(fid, "retire", "cli")
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert memory.count_events("accepted", "auto", since) == 0 and memory.taken_back_count(since) == 0


def test_a_full_profile_holds_the_fact_rather_than_failing(world):
    _, memory, _ = world
    for n in range(100):
        try:
            memory.add_manual(("long fact number %d " % n) + "x" * 170, "api")
        except diya_memory.BudgetExceeded:
            break
    big = "likes walking by the river " + "y" * 160  # as long as the facts that filled it, so it cannot fit in what is left
    fid = stage(world, big, big)
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 0, 1)
    assert "ask:doubt:memory_full" in memory.get(fid)["flags"] and memory.get(fid)["status"] == "candidate"


def test_a_candidate_too_long_to_accept_is_rejected_not_an_error(world):
    _, memory, _ = world
    long_text = ("likes " + "walking by the river and " * 12).strip()
    fid = stage(world, long_text, long_text)
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 1, 0)  # the pass runs the checks first, and the length check says it is too long
    assert memory.get(fid)["status"] == "rejected" and events(memory, fid)[-1][2]["reasons"] == ["too_long"]


def test_facts_about_a_named_person_are_remembered_like_any_other_unless_sensitive(world):
    _, memory, _ = world
    kept = stage(world, "my sister Maya is visiting in May", "sister Maya is visiting in May", person="Maya")
    asked = stage(world, "my sister Maya is on medication for asthma", "sister Maya takes medication for asthma", person="Maya")
    assert auto.apply(memory, now=NOW) == auto.Report(1, 1, 0, 0)
    assert memory.get(kept)["status"] == "accepted" and memory.get(asked)["status"] == "candidate"


def test_apply_acts_only_on_candidates(world):
    _, memory, _ = world
    memory.add_manual("works as a software engineer", "api")
    rejected = stage(world, "I like coffee", "likes coffee")
    memory.decide(rejected, "reject", "cli")
    assert auto.apply(memory, now=NOW) == auto.Report(0, 0, 0, 0)
    assert [f["status"] for f in memory.facts()] == ["accepted", "rejected"]


# --- the store's own new methods --------------------------------------------------------------------------

def test_discard_secret_only_discards_a_candidate_and_only_with_a_kind_that_is_a_word(world):
    _, memory, _ = world
    fid = stage(world, "I like tea", "likes tea")
    with pytest.raises(InvalidFact):
        memory.discard_secret(fid, "Pass Word!", "auto")
    with pytest.raises(InvalidFact):
        memory.discard_secret(fid, "x", "auto")
    with pytest.raises(InvalidFact):
        memory.discard_secret(fid, "a" * 21, "auto")
    with pytest.raises(UnknownFact):
        memory.discard_secret(999, "password", "auto")
    memory.decide(fid, "accept", "cli")
    with pytest.raises(IllegalTransition):
        memory.discard_secret(fid, "password", "auto")
    with pytest.raises(ValueError):
        memory.discard_secret(fid, "password", "someone")


def test_decide_records_the_detail_it_is_given_and_nothing_when_it_is_not(world):
    _, memory, _ = world
    a = stage(world, "I like tea", "likes tea")
    b = stage(world, "I like coffee", "likes coffee")
    memory.decide(a, "accept", "cli")
    memory.decide(b, "accept", "auto", {"lane": "remember", "reasons": ["plain"]})
    assert events(memory, a)[-1] == ("accepted", "cli", None)
    assert events(memory, b)[-1] == ("accepted", "auto", {"lane": "remember", "reasons": ["plain"]})


def test_auto_is_an_actor_and_an_unknown_actor_is_not(world):
    _, memory, _ = world
    assert "auto" in diya_memory.ACTORS
    fid = stage(world, "I like tea", "likes tea")
    with pytest.raises(ValueError, match="actor must be one of"):
        memory.decide(fid, "accept", "robot")


def test_count_events_counts_the_kind_the_actor_and_the_window(world):
    _, memory, _ = world
    a = stage(world, "I like tea", "likes tea")
    memory.decide(a, "accept", "auto")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert memory.count_events("accepted", "auto", past) == 1
    assert memory.count_events("accepted", "cli", past) == 0
    assert memory.count_events("rejected", "auto", past) == 0
    assert memory.count_events("accepted", "auto", future) == 0


def test_taking_back_one_fact_twice_counts_it_once(world):
    _, memory, _ = world
    a = stage(world, "I like tea", "likes tea")
    memory.decide(a, "accept", "auto")
    memory.decide(a, "retire", "api")
    memory.decide(a, "restore", "api")
    memory.decide(a, "retire", "api")
    assert memory.taken_back_count((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()) == 1


# --- the hook in Dreaming, behind DIYA_AUTO_MEMORY ---------------------------------------------------------

import dataclasses

import diya_config
import dreaming


@pytest.fixture
def staged(tmp_path):
    """A store with two messages from the owner, and a queue record Dreaming staged for them (one plain fact, one sensitive)."""
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "dream.log"),
        dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "p.txt"),
    )
    store = Store(config.db_path)
    thread = store.create_thread()
    first = store.add_message(thread, "user", "I like tea in the morning and I am allergic to peanuts")
    last = store.add_message(thread, "assistant", "Noted.")
    record = {"timestamp": "2026-10-10T00:00:00+00:00", "first_message_id": first, "last_message_id": last, "model": "m",
              "facts": ["- likes tea in the morning", "- is allergic to peanuts"]}
    (tmp_path / "pending.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    return config, store


def test_with_the_switch_off_what_was_staged_waits_for_a_person_as_it_always_did(staged):
    config, store = staged
    assert config.auto_memory is False
    dreaming.Dreamer(config).remember_on_its_own()
    assert Memory(store).facts() == []  # not even taken in


def test_with_the_switch_on_what_was_staged_is_taken_in_and_put_in_its_lanes(staged, capsys):
    config, store = staged
    dreaming.Dreamer(dataclasses.replace(config, auto_memory=True)).remember_on_its_own()
    memory = Memory(store)
    assert {f["text"]: f["status"] for f in memory.facts()} == {"likes tea in the morning": "accepted", "is allergic to peanuts": "candidate"}
    out = capsys.readouterr().out
    assert "Memory on its own: 1 remembered, 1 to ask about, 0 not kept, 0 held (profile full); 2 newly taken in" in out
    dreaming.Dreamer(dataclasses.replace(config, auto_memory=True)).remember_on_its_own()  # a second cycle changes nothing
    assert "Memory on its own: 0 remembered, 1 to ask about, 0 not kept, 0 held (profile full); 0 newly taken in" in capsys.readouterr().out
    assert memory.verify_integrity() == []


def test_a_failure_in_the_memory_pass_is_logged_and_does_not_stop_dreaming(staged, monkeypatch, capsys):
    config, _ = staged

    def broken(memory, **kwargs):
        raise RuntimeError("the store is on fire")

    monkeypatch.setattr(auto, "apply", broken)
    dreaming.Dreamer(dataclasses.replace(config, auto_memory=True)).remember_on_its_own()  # does not raise
    assert "[error] Memory on its own failed (the store is on fire)" in capsys.readouterr().out


def test_the_scheduled_entry_point_runs_the_memory_pass_after_the_cycle_and_logs_it(staged, monkeypatch, tmp_path):
    config, store = staged
    (tmp_path / "state.json").write_text(json.dumps({"last_message_id": 99}), encoding="utf-8")  # nothing new to dream about: no model is called
    for name, value in (("DIYA_DB_PATH", config.db_path), ("DIYA_DREAM_LOG_PATH", config.dream_log_path), ("DIYA_DREAM_STATE_PATH", config.dream_state_path),
                        ("DIYA_DREAM_PENDING_PATH", config.dream_pending_path), ("DIYA_PROFILE_PATH", config.profile_path), ("DIYA_AUTO_MEMORY", "1")):
        monkeypatch.setenv(name, value)
    assert dreaming.main() == 0
    log = pathlib.Path(config.dream_log_path).read_text(encoding="utf-8")
    assert "Nothing new to dream about." in log and "Memory on its own: 1 remembered, 1 to ask about" in log
    assert [f["status"] for f in Memory(store).facts()] == ["accepted", "candidate"]


def test_the_switch_is_a_real_setting_off_by_default_and_a_bad_value_is_refused():
    assert diya_config.load_config({}).auto_memory is False
    assert diya_config.load_config({"DIYA_AUTO_MEMORY": "1"}).auto_memory is True
    assert diya_config.load_config({"DIYA_AUTO_MEMORY": "off"}).auto_memory is False
    with pytest.raises(diya_config.ConfigError, match="DIYA_AUTO_MEMORY"):
        diya_config.load_config({"DIYA_AUTO_MEMORY": "sometimes"})


# --- an ask flag does not outlive the asking ---------------------------------------------------------------

def test_a_fact_that_waited_and_is_then_accepted_does_not_keep_saying_it_will_be_asked_about(world):
    _, memory, _ = world
    ids = [stage(world, said, text) for said, text in HOBBIES[:2]]
    auto.apply(memory, now=NOW, limit=1)
    assert "ask:doubt:daily_cap" in memory.get(ids[1])["flags"]
    auto.apply(memory, now=datetime.now(timezone.utc) + timedelta(hours=25), limit=1)  # room again: the waiting one is remembered
    got = memory.get(ids[1])
    assert got["status"] == "accepted" and not [f for f in got["flags"] if f.startswith("ask:")]


def test_a_fact_that_waited_and_is_then_rejected_loses_the_flag_too(world):
    _, memory, _ = world
    fid = stage(world, "I like tea in the morning", "likes tea in the morning")
    memory.set_flags(fid, ["verifier:unclear"], "system")
    auto.apply(memory, now=NOW)
    assert "ask:doubt:verifier:unclear" in memory.get(fid)["flags"]
    memory.add_manual("likes tea in the morning", "api")  # now it repeats an accepted fact: never
    auto.apply(memory, now=NOW)
    got = memory.get(fid)
    assert got["status"] == "rejected" and not [f for f in got["flags"] if f.startswith("ask:")]
