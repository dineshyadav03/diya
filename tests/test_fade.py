"""Facts that fade unless they are said again (diya_fade.py, Memory.reinforce/keep/fading/fade_due, docs/FADING_DESIGN.md), added 2026-10-18 from the study of supermemory's company-brain.

What this proves, with the real memory, Dreamer, chat route and a scripted model: the rule recognises a fact that says it is a passing state ("right now", "for now", "currently reading") and leaves alone a
fact that is meant to last ("currently lives in Pune", "always", "every Sunday"); the clock runs from the LAST time it was said, so saying it again renews it, once per message; "Keep" ends the fading and
a restore starts the clock again; a fact whose time has come is retired (not deleted) and one whose time has not is untouched; a sentence said twice in chat is counted as a mention instead of being
dropped; Dreaming does the fading only with automatic memory on and its receipt counts what faded; the Memory page's data carries the date and the count; and "how do you know that?" says so.
It does not prove the rule catches every passing state the owner will ever write: it is deliberately narrow, and a miss only means a fact stays (it never means one is lost).
"""
import dataclasses
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_fade as fade
import diya_memory
import diya_provenance as prov
import diya_web
import dreaming
from diya_db import Store
from diya_memory import IllegalTransition, Memory, UnknownFact
from fakes import ByQuestionClient, FakeClient

LOCAL = "https://localhost"


class Quiet:
    def transcribe(self, path):
        return ""


# ---- the rule --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, days", [
    ("Is reading Dune right now.", 7), ("Is busy with the project at the moment.", 7), ("Using the old laptop for now.", 45), ("Staying with a friend for the time being.", 45),
    ("Is currently reading Dune.", 45), ("Has been working on a side project lately.", 45), ("Is these days preparing for the viva.", 45), ("Is studying anatomy this semester.", 120),
    ("Is currently reading Dune this semester.", 45),  # the shortest phrase decides
])
def test_a_fact_that_says_it_is_a_passing_state_fades(text, days):
    assert fade.fade_rule(text)[0] == days
    assert fade.describe(text)


@pytest.mark.parametrize("text", [
    "Currently lives in Pune.", "Currently works at the hospital.", "Currently has a dog named Hog.", "Name is Alex.", "Plays badminton every Sunday.", "Is always reading before bed.",
    "Usually studies at night, currently.", "Used to read Dune right now.", "Has lived in Pune since 2019, for now.", "Is allergic to peanuts.", "Exam is on 5 November.", "",
])
def test_a_fact_meant_to_last_does_not_fade(text):
    assert fade.fade_rule(text) is None and fade.describe(text) is None


@pytest.mark.parametrize("value", [None, 5, ["for now"], b"for now"])
def test_something_that_is_not_text_does_not_fade(value):
    assert fade.fade_rule(value) is None


def test_the_clock_runs_from_the_last_time_it_was_said():
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    again = start + timedelta(days=30)
    assert fade.fades_on("Is reading Dune for now.", [start]) == start + timedelta(days=45)
    assert fade.fades_on("Is reading Dune for now.", [start, again]) == again + timedelta(days=45)
    assert fade.fades_on("Name is Alex.", [start]) is None
    assert fade.fades_on("Is reading Dune for now.", []) is None


# ---- the memory ------------------------------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "fade.db"))


@pytest.fixture
def memory(store):
    return Memory(store)


def age(store, fact_id, days):
    """Make a fact look `days` old (the tests cannot wait): its created_at is moved back."""
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE facts SET created_at = ? WHERE id = ?", (when, fact_id))


def test_only_a_passing_state_is_marked_to_fade(memory):
    passing = memory.add_manual("Is reading Dune for now.", "api")
    lasting = memory.add_manual("Name is Alex.", "api")
    fading = memory.fading()
    assert set(fading) == {passing} and lasting not in fading
    assert abs((fading[passing] - datetime.now(timezone.utc)).days - 44) <= 1


def test_a_fact_whose_time_has_not_come_is_not_retired(memory, store):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    age(store, fact, 10)
    assert memory.fade_due() == [] and memory.get(fact)["status"] == "accepted"


def test_a_fact_whose_time_has_come_is_retired_not_deleted_and_can_be_restored(memory, store):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    keep = memory.add_manual("Name is Alex.", "api")
    age(store, fact, 60)
    assert memory.fade_due() == [fact]
    assert memory.get(fact)["status"] == "retired" and memory.get(keep)["status"] == "accepted"
    assert memory.get(fact)["text"] == "Is reading Dune for now."  # the words are still there
    memory.decide(fact, "restore", "api")
    assert memory.get(fact)["status"] == "accepted"
    assert fact in memory.fading() and memory.fade_due() == []  # a restore starts the clock again, so it is not retired straight away


def test_saying_it_again_renews_it_once_per_message(memory, store):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    age(store, fact, 60)
    assert memory.reinforce(fact, 11, "auto") is True
    assert memory.reinforce(fact, 11, "auto") is False  # the same message is not counted twice
    assert [m for m, _ in memory.mentions(fact)] == [11] and memory.mention_counts() == {fact: 1}
    assert memory.fade_due() == []  # it was said just now: the clock restarted
    assert memory.reinforce(fact, 12, "auto") is True and memory.mention_counts() == {fact: 2}


def test_only_an_accepted_fact_can_be_reinforced(memory):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    memory.decide(fact, "retire", "api")
    assert memory.reinforce(fact, 3, "auto") is False and memory.reinforce(9999, 3, "auto") is False
    assert memory.reinforce(fact, "x", "auto") is False
    assert memory.mention_counts() == {}


def test_keep_ends_the_fading_for_good_and_keeping_twice_is_harmless(memory, store):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    age(store, fact, 60)
    memory.keep(fact, "api")
    memory.keep(fact, "api")
    assert fact not in memory.fading() and memory.fade_due() == [] and memory.get(fact)["status"] == "accepted"


def test_keep_is_for_an_accepted_fact_only(memory):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    memory.decide(fact, "retire", "api")
    with pytest.raises(IllegalTransition):
        memory.keep(fact, "api")
    with pytest.raises(UnknownFact):
        memory.keep(9999, "api")


def test_a_restore_after_keep_starts_fading_again(memory, store):
    fact = memory.add_manual("Is reading Dune for now.", "api")
    memory.keep(fact, "api")
    memory.decide(fact, "retire", "api")
    memory.decide(fact, "restore", "api")
    assert fact in memory.fading()  # kept applied to the fact as it was; a restore is a new decision to have it


def test_fading_never_changes_the_other_facts_or_the_integrity_of_the_record(memory, store):
    a = memory.add_manual("Is reading Dune for now.", "api")
    b = memory.add_manual("Name is Alex.", "api")
    age(store, a, 90)
    memory.fade_due()
    assert [f["id"] for f in memory.facts("accepted")] == [b]
    assert memory.verify_integrity() == []


# ---- said twice in chat is counted, not dropped ----------------------------------------------------------------------


def build(folder, client, auto=True):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(folder / "p.db"), dream_log_path=str(folder / "log"), dream_state_path=str(folder / "state.json"), dream_pending_path=str(folder / "pending.jsonl"),
        profile_path=str(folder / "profile.txt"), auto_memory=auto, require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=client)
    return TestClient(diya_web.create_app(config, agent, Quiet()), base_url=LOCAL), agent, config


def test_a_sentence_said_twice_in_chat_is_counted_as_a_mention_and_not_added_twice(tmp_path):
    model = ByQuestionClient(extraction=["- is reading Dune for now", "- is reading Dune for now"], chat=["Noted.", "Noted."])
    client, agent, _ = build(tmp_path, model)
    client.post("/api/chat", json={"message": "I'm reading Dune for now"})
    client.post("/api/chat", json={"message": "I am still reading Dune for now"})
    memory = Memory(agent.store)
    accepted = [f for f in memory.facts("accepted") if "Dune" in f["text"]]
    assert len(accepted) == 1
    assert memory.mention_counts().get(accepted[0]["id"], 0) == 1
    assert accepted[0]["id"] in memory.fading()


# ---- Dreaming ---------------------------------------------------------------------------------------------------------


def make_dreamer(tmp_path, auto):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), auto_memory=auto, categories=False, require_token=False,
    )
    store = Store(config.db_path)
    return config, store, dreaming.Dreamer(config, client=FakeClient(), store=store)


def test_dreaming_retires_the_facts_that_faded_and_the_receipt_counts_them(tmp_path):
    config, store, dreamer = make_dreamer(tmp_path, auto=True)
    memory = Memory(store)
    old = memory.add_manual("Is reading Dune for now.", "api")
    new = memory.add_manual("Is trying a new editor for now.", "api")
    age(store, old, 80)
    dreaming.run_cycle(dreamer)
    assert memory.get(old)["status"] == "retired" and memory.get(new)["status"] == "accepted"
    receipt = store.dream_last_run()
    assert receipt["faded"] == 1
    assert receipt in store.dream_runs_recent()  # a pass that faded something is a busy pass, not an idle one


def test_without_automatic_memory_dreaming_fades_nothing(tmp_path):
    config, store, dreamer = make_dreamer(tmp_path, auto=False)
    memory = Memory(store)
    old = memory.add_manual("Is reading Dune for now.", "api")
    age(store, old, 80)
    dreaming.run_cycle(dreamer)
    assert memory.get(old)["status"] == "accepted" and (store.dream_last_run() or {}).get("faded", 0) == 0


def test_a_failure_while_fading_is_logged_and_never_stops_dreaming(tmp_path, monkeypatch):
    config, store, dreamer = make_dreamer(tmp_path, auto=True)

    def boom(self, *a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(Memory, "fade_due", boom)
    dreaming.run_cycle(dreamer)  # does not raise
    assert "disk gone" in (store.dream_last_run()["errors"] or "")


# ---- the Memory page's data, and "how do you know that?" ---------------------------------------------------------------


def test_the_memory_route_carries_the_date_and_the_count_and_keep_clears_the_date(tmp_path):
    client, agent, _ = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    passing = memory.add_manual("Is reading Dune for now.", "api")
    lasting = memory.add_manual("Name is Alex.", "api")
    memory.reinforce(passing, 5, "auto")
    by_id = {f["id"]: f for f in client.get("/api/memory").json()["facts"]}
    assert by_id[passing]["fades_on"] and len(by_id[passing]["fades_on"]) == 10 and by_id[passing]["said_again"] == 1
    assert by_id[lasting]["fades_on"] is None and by_id[lasting]["said_again"] == 0
    reply = client.post(f"/api/memory/{passing}/keep")
    assert reply.status_code == 200 and reply.json()["fact"]["fades_on"] is None
    assert client.post("/api/memory/9999/keep").status_code == 404


def test_keep_on_a_fact_that_is_not_accepted_is_refused_and_changes_nothing(tmp_path):
    client, agent, _ = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    fact = memory.add_manual("Is reading Dune for now.", "api")
    memory.decide(fact, "retire", "api")
    assert client.post(f"/api/memory/{fact}/keep").status_code == 409
    assert memory.get(fact)["status"] == "retired"


def test_how_do_you_know_says_when_a_passing_fact_will_fade_and_that_it_was_said_again(tmp_path):
    client, agent, _ = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    fact = memory.add_manual("Is reading Dune for now.", "api")
    memory.reinforce(fact, 5, "auto")
    text = prov.describe(memory, agent.store, memory.get(fact))
    assert "fades on" in text and "unless you say it again or keep it" in text and "said it again once" in text
    memory.keep(fact, "api")
    assert "fades on" not in prov.describe(memory, agent.store, memory.get(fact))


def test_the_proxy_lets_keep_through():
    source = (pathlib.Path(__file__).resolve().parent.parent / "frontend" / "lib" / "proxy.mjs").read_text(encoding="utf-8")
    assert "'keep'" in source


def test_with_automatic_memory_off_no_date_is_promised_and_nothing_fades(tmp_path):
    client, agent, config = build(tmp_path, ByQuestionClient(), auto=False)
    memory = diya_memory.open_memory(agent.store, config)
    fact = memory.add_manual("Is reading Dune for now.", "api")
    age(agent.store, fact, 90)
    assert memory.fading() == {} and memory.fade_due() == [] and memory.get(fact)["status"] == "accepted"
    assert client.get("/api/memory").json()["facts"][0]["fades_on"] is None


# ---- a fact that says when it ends (diya_when.ends_on; docs/TIME_DESIGN.md), from Mem0's expiration dates --------------------


def test_a_fact_that_says_when_it_ends_fades_the_day_after_and_saying_it_again_does_not_move_it(memory, store):
    from datetime import date

    fact = memory.add_manual("has a gym membership until 31 Jan", "api")
    when = memory.fading()[fact]
    made = datetime.now().astimezone().date()
    year = made.year if date(made.year, 1, 31) >= made else made.year + 1
    assert when.astimezone().date() == date(year, 2, 1)
    memory.reinforce(fact, 7, "auto")
    assert memory.fading()[fact] == when  # the date is the date


def test_a_fact_about_the_past_with_a_date_does_not_fade_and_a_kept_one_does_not_either(memory):
    past = memory.add_manual("lived in Pune until 2019", "api")
    kept = memory.add_manual("the trial ends on 15 Nov", "api")
    memory.keep(kept, "api")
    assert past not in memory.fading() and kept not in memory.fading()


def test_an_explicit_end_does_not_need_a_passing_state_word_and_durable_words_do_not_block_it(memory):
    fact = memory.add_manual("goes to yoga every Monday until the end of March", "api")
    assert fact in memory.fading()


def test_the_page_and_the_provenance_answer_say_it_lasts_until_not_that_it_is_a_passing_state(tmp_path):
    client, agent, _ = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    fact = memory.add_manual("has a gym membership until 31 Jan", "api")
    body = {f["id"]: f for f in client.get("/api/memory").json()["facts"]}[fact]
    assert body["lasts_until"] and body["lasts_until"].endswith("-01-31") and body["fades_on"]
    assert "It says it lasts until" in prov.describe(memory, agent.store, memory.get(fact)) and "passing state" not in prov.describe(memory, agent.store, memory.get(fact))
    passing = memory.add_manual("is reading Dune for now", "api")
    other = {f["id"]: f for f in client.get("/api/memory").json()["facts"]}[passing]
    assert other["lasts_until"] is None
