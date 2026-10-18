"""Two windows, one memory: a change never silently overwrites another (DIYA-032), added 2026-10-18.

The Memory page can be open in two places (a laptop and a phone), and the scheduled pass changes facts too. What this proves, with the real memory and routes: an edit sent with the wording the person saw is
refused, with a 409 and words saying what to do, if the fact has changed since, and nothing is written; an edit with the current wording goes through; two edits sent at the same moment cannot both win; a
decision made on a fact that something else already decided is refused rather than flipped back; and an edit sent without the old wording (an older client) behaves as it always did.
"""
import dataclasses
import threading

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from diya_db import Store
from diya_memory import ChangedUnderYou, IllegalTransition, Memory
from fakes import FakeClient


class Quiet:
    def transcribe(self, path):
        return ""


@pytest.fixture
def parts(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "m.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)
    agent = diya.Agent(config, client=FakeClient(), action_kinds=[])
    memory = Memory(agent.store)
    thread = agent.store.create_thread("t")
    message = agent.store.add_message(thread, "user", "I like tea")
    fact = memory.add_candidate("likes tea", batch_first=message, batch_last=message, position=message, model="m", extracted_at="2026-10-10T00:00:00+00:00", raw="- likes tea")
    return TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost"), memory, fact


def events(memory, fact):
    return [event for event, *_ in memory.events(fact)]


def test_an_edit_made_over_the_wording_the_person_saw_goes_through(parts):
    _, memory, fact = parts
    memory.edit(fact, "likes tea in the morning", "api", expected_text="likes tea")
    assert memory.get(fact)["text"] == "likes tea in the morning" and events(memory, fact)[-1] == "edited"


def test_an_edit_over_a_fact_that_changed_since_it_was_opened_is_refused_and_writes_nothing(parts):
    _, memory, fact = parts
    memory.edit(fact, "likes green tea", "api")  # the other window got there first
    with pytest.raises(ChangedUnderYou, match="changed since you opened it"):
        memory.edit(fact, "likes black tea", "api", expected_text="likes tea")
    assert memory.get(fact)["text"] == "likes green tea" and events(memory, fact).count("edited") == 1
    assert issubclass(ChangedUnderYou, IllegalTransition)  # so every caller that already handles a refused change handles this one


def test_an_edit_without_the_old_wording_behaves_as_before(parts):
    _, memory, fact = parts
    memory.edit(fact, "likes green tea", "api")
    memory.edit(fact, "likes black tea", "api")
    assert memory.get(fact)["text"] == "likes black tea"


def test_through_the_routes_the_second_window_is_told_what_happened_and_can_try_again(parts):
    client, memory, fact = parts
    first = client.post(f"/api/memory/{fact}/edit", json={"text": "likes green tea", "expected_text": "likes tea"})
    assert first.status_code == 200
    second = client.post(f"/api/memory/{fact}/edit", json={"text": "likes black tea", "expected_text": "likes tea"})
    assert second.status_code == 409 and "changed since you opened it" in second.json()["detail"] and "Reload" in second.json()["detail"]
    assert memory.get(fact)["text"] == "likes green tea"
    third = client.post(f"/api/memory/{fact}/edit", json={"text": "likes black tea", "expected_text": "likes green tea"})
    assert third.status_code == 200 and memory.get(fact)["text"] == "likes black tea"


def test_two_edits_sent_at_the_same_moment_cannot_both_win(parts):
    _, memory, fact = parts
    results, barrier = [], threading.Barrier(2)

    def attempt(text):
        barrier.wait()
        try:
            memory.edit(fact, text, "api", expected_text="likes tea")
            results.append("saved")
        except ChangedUnderYou:
            results.append("refused")

    threads = [threading.Thread(target=attempt, args=(text,)) for text in ("likes green tea", "likes black tea")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["refused", "saved"] and memory.get(fact)["text"] in ("likes green tea", "likes black tea") and events(memory, fact).count("edited") == 1


def test_a_decision_on_a_fact_something_else_already_decided_is_refused_not_flipped(parts):
    client, memory, fact = parts
    assert client.post(f"/api/memory/{fact}/accept").status_code == 200  # one window accepts
    answer = client.post(f"/api/memory/{fact}/reject")  # the other, still showing it as waiting, rejects
    assert answer.status_code == 409 and memory.get(fact)["status"] == "accepted"
    assert events(memory, fact).count("rejected") == 0


def test_an_edit_of_a_fact_that_is_no_longer_waiting_is_refused_whatever_the_wording(parts):
    client, memory, fact = parts
    client.post(f"/api/memory/{fact}/accept")
    answer = client.post(f"/api/memory/{fact}/edit", json={"text": "likes tea a lot", "expected_text": "likes tea"})
    assert answer.status_code == 409 and memory.get(fact)["text"] == "likes tea"
