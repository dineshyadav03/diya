"""Remember without asking (diya_autonomy.settle, DIYA_ASK_MEMORY=0; the owner's choice of 2026-10-27: "remember whatever I mention", as Hark does), added 2026-10-27.

What this proves: a fact held back to be asked about (private-looking, doubtful, like a known one) is remembered instead, with the trail saying why; a fact held as a conflict with a known one replaces it
(the old stays in the trail) or, when it cannot, is kept beside it; a secret, a copy and what the person never said are still never kept; a hold that is a limit or a failure is left alone; and the switch
is on by default (asking) and off with DIYA_ASK_MEMORY=0.
"""
import json
from datetime import datetime, timezone

import pytest

import diya_autonomy as auto
import diya_config
from diya_db import Store
from diya_memory import Memory

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def world(tmp_path):
    store = Store(str(tmp_path / "settle.db"))
    return store, Memory(store), store.create_thread()


def stage(world, said, fact_text):
    store, memory, thread = world
    message_id = store.add_message(thread, "user", said)
    return memory.add_candidate(fact_text, batch_first=message_id, batch_last=message_id, position=message_id, model="m", extracted_at="2026-10-10T00:00:00+00:00", raw="- " + fact_text)


def hold(memory, fact_id, flag):
    memory.set_flags(fact_id, [flag], "system")


def events(memory, fact_id):
    return [(event, actor, json.loads(detail) if detail else None) for event, actor, _, detail in memory.events(fact_id)]


def test_a_private_looking_fact_is_asked_about_by_apply_and_remembered_by_settle(world):
    _, memory, _ = world
    fid = stage(world, "I take medication for asthma every night", "takes medication for asthma every night")
    assert auto.apply(memory, now=NOW).asked == 1 and memory.questions_waiting() == 1 and memory.get(fid)["status"] == "candidate"
    assert auto.settle(memory) == 1
    assert memory.get(fid)["status"] == "accepted" and memory.questions_waiting() == 0
    assert next(d for e, a, d in events(memory, fid) if e == "accepted") == {"lane": "remember", "reasons": ["no_questions", "sensitive:health"]}


@pytest.mark.parametrize("flag", ["ask:doubt:ungrounded", "ask:doubt:verifier:unclear", "ask:sensitive:model_unclear", "ask:conflict:replaces_unclear", "ask:sensitive:money"])
def test_a_doubtful_or_private_hold_is_remembered(world, flag):
    _, memory, _ = world
    fid = stage(world, "I like jazz", "likes jazz")
    hold(memory, fid, flag)
    assert auto.settle(memory) == 1 and memory.get(fid)["status"] == "accepted"


def test_a_fact_held_as_a_conflict_replaces_the_known_one_and_the_old_stays_in_the_trail(world):
    _, memory, _ = world
    old = stage(world, "I live in Pune", "lives in Pune")
    memory.decide(old, "accept", "api")
    new = stage(world, "I moved to Bengaluru", "lives in Bengaluru")
    hold(memory, new, f"ask:conflict:similar:{old}")
    assert auto.settle(memory) == 1
    assert memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired"
    assert any(event == "retired" for event, _, _ in events(memory, old))


def test_a_conflict_with_a_fact_that_is_gone_is_kept_beside_what_is_known(world):
    _, memory, _ = world
    new = stage(world, "I like jazz", "likes jazz")
    hold(memory, new, "ask:conflict:similar:9999")
    assert auto.settle(memory) == 1 and memory.get(new)["status"] == "accepted"


@pytest.mark.parametrize("flag", ["ask:doubt:memory_full", "ask:doubt:daily_cap", "ask:doubt:breaker_open", "ask:doubt:privacy_check_failed", "ask:conflict:replace_check_failed"])
def test_a_limit_or_a_failure_is_left_waiting(world, flag):
    _, memory, _ = world
    fid = stage(world, "I like jazz", "likes jazz")
    hold(memory, fid, flag)
    assert auto.settle(memory) == 0 and memory.get(fid)["status"] == "candidate"


def test_a_candidate_with_no_hold_is_not_touched(world):
    _, memory, _ = world
    fid = stage(world, "I like jazz", "likes jazz")
    assert auto.settle(memory) == 0 and memory.get(fid)["status"] == "candidate"


def test_a_secret_is_still_never_kept_and_settling_does_not_bring_it_back(world):
    _, memory, _ = world
    fid = stage(world, "my password is hunter2", "my password is hunter2")
    auto.apply(memory, now=NOW)
    assert auto.settle(memory) == 0
    assert memory.get(fid)["status"] != "accepted" and "hunter2" not in memory.render_for_model()


def test_a_fact_the_same_as_a_known_one_is_not_kept_twice(world):
    _, memory, _ = world
    known = stage(world, "I like jazz", "likes jazz")
    memory.decide(known, "accept", "api")
    again = stage(world, "I like jazz", "likes jazz!")
    hold(memory, again, "ask:doubt:ungrounded")
    auto.settle(memory)
    assert [f["text"] for f in memory.facts("accepted")].count("likes jazz") == 1


def test_asking_is_the_default_and_the_switch_turns_it_off():
    assert diya_config.load_config({}).ask_memory is True
    assert diya_config.load_config({"DIYA_ASK_MEMORY": "0"}).ask_memory is False
