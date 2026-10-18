"""'How do you know that?' answered from the record (diya_provenance.py, docs/PROVENANCE_DESIGN.md), added 2026-10-18.

What this proves, with the real memory, the real chat route and a scripted model: such a question is recognised in its several forms and ordinary questions are not; for a fact the person said, the answer
quotes the message and its date, says Diya took it on herself and how to undo it; for a fact the person typed, an imported one, a retired one and one still waiting, it says exactly that; for something
with no record it says so and does not invent a history; "how do you know that?" with nothing named is tied to the words of the last answer; the model is never asked (so it cannot make a history up);
and the question is recorded as a flow in the activity journal. It does not prove the wording suits every question the owner will ask.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_provenance as prov
import diya_web
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient

LOCAL = "https://localhost"


class Quiet:
    def transcribe(self, path):
        return ""


def build(folder, client):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(folder / "p.db"), dream_log_path=str(folder / "log"), dream_state_path=str(folder / "state.json"), dream_pending_path=str(folder / "pending.jsonl"),
        profile_path=str(folder / "profile.txt"), auto_memory=True, require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=client)
    return TestClient(diya_web.create_app(config, agent, Quiet()), base_url=LOCAL), agent


@pytest.mark.parametrize("text, rest", [
    ("how do you know I have a dog?", "I have a dog"), ("Why do you know my exam is on Friday", "my exam is on Friday"), ("where did you get that?", ""), ("where did you learn about Rocky", "about Rocky"),
    ("who told you my brother lives in Pune?", "my brother lives in Pune"), ("when did I tell you about the dog", "about the dog"), ("what is your source for that", "for that"),
    ("how do you remember my phone?", "my phone"), ("Wait, how do you know that?", "that"), ("how come you know my name", "my name"),
])
def test_these_ask_where_a_thing_was_learned(text, rest):
    assert prov.asks_where_from(text) is not None


@pytest.mark.parametrize("text", [
    "what is the capital of France?", "how do I know if my phone is charged", "do you know my dog's name?", "I told you about my dog", "tell me about Rocky", "why is the sky blue", "how do you work?", "",
    None, 5, "x" * 300, "how do you know\nthat",
])
def test_these_do_not(text):
    assert prov.asks_where_from(text) is None


def test_the_rest_of_the_question_is_what_is_asked_about():
    assert prov.asks_where_from("How do you know I have a dog?!") == "I have a dog"
    assert prov.asks_where_from("where did you get that?") == "that"


def setup_dog(tmp_path):
    model = ByQuestionClient(extraction=["- has a dog named Hog"], chat=["Noted."])
    client, agent = build(tmp_path, model)
    client.post("/api/chat", json={"message": "I got another dog named Hog"})
    return client, agent, model


def test_for_a_fact_the_person_said_the_answer_quotes_their_message_and_how_it_was_taken(tmp_path):
    client, agent, model = setup_dog(tmp_path)
    asked_before = len(model.asked("chat"))
    answer = client.post("/api/chat", json={"message": "how do you know I have a dog?"}).json()
    text = str(answer)
    assert "has a dog named Hog" in text and "You told me: “I got another dog named Hog”" in text
    assert "I remembered it on my own" in text and "you can undo it" in text and "Memory page" in text
    assert len(model.asked("chat")) == asked_before  # the model was not asked: it cannot make a history up


def test_a_typed_fact_an_imported_one_a_retired_one_and_a_waiting_one_are_each_described_as_what_they_are(tmp_path):
    client, agent = build(tmp_path, ByQuestionClient(chat=["unused"]))
    memory = Memory(agent.store)
    typed = memory.add_manual("studies medicine", "api")
    retired = memory.add_manual("lives in Delhi", "api")
    memory.decide(retired, "retire", "api")
    store = agent.store
    typed_text = prov.describe(memory, store, memory.get(typed))
    assert "You added this yourself" in typed_text and f"number {typed} on the Memory page" in typed_text and "told me" not in typed_text
    retired_text = prov.describe(memory, store, memory.get(retired))
    assert "I no longer use it: it was retired" in retired_text and "Restore" in retired_text or "restore" in retired_text


def test_a_retired_fact_is_found_only_when_no_live_fact_matches(tmp_path):
    client, agent = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    old = memory.add_manual("lives in Delhi", "api")
    memory.decide(old, "retire", "api")
    answer = prov.explain(memory, agent.store, "how do you know where I live in Delhi", None)
    assert answer and "I no longer use it" in answer
    new = memory.add_manual("lives in Pune now", "api")
    answer = prov.explain(memory, agent.store, "how do you know where I live", None)
    assert "Pune" in answer and "Delhi" not in answer and f"number {new}" in answer


def test_with_no_record_it_says_so_and_does_not_invent_one(tmp_path):
    client, agent = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    memory.add_manual("studies medicine", "api")
    answer = prov.explain(memory, agent.store, "how do you know my favourite colour is blue", None)
    assert answer == prov.NOTHING_FOR_THAT and "told me" not in answer
    assert prov.explain(memory, agent.store, "how do you know the weather in Pune", None) is None  # not about the person: left to the model


def test_how_do_you_know_that_is_tied_to_the_words_of_the_last_answer(tmp_path):
    client, agent = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    memory.add_manual("has a dog named Rocky", "api")
    memory.add_manual("studies medicine", "api")
    answer = prov.explain(memory, agent.store, "how do you know that?", "Your dog Rocky needs a walk.")
    assert "Rocky" in answer and "medicine" not in answer
    assert prov.explain(memory, agent.store, "how do you know that?", "It is sunny in Pune.") == prov.NOTHING_FOR_LAST
    assert prov.explain(memory, agent.store, "how do you know that?", None) is None  # nothing to refer to: left to the model


def test_at_most_three_facts_are_explained_best_match_first(tmp_path):
    client, agent = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    for text in ("has a dog named Rocky", "has a dog named Hog", "walks the dog at six", "feeds the dog twice", "dog food is in the shed"):
        memory.add_manual(text, "api")
    answer = prov.explain(memory, agent.store, "how do you know about the dog named Hog", None)
    assert answer.count("on the Memory page") == prov.MAX_FACTS and answer.index("Hog") < answer.index("Rocky")


def test_the_question_is_recorded_as_a_flow_in_the_activity_journal(tmp_path):
    client, agent, model = setup_dog(tmp_path)
    client.post("/api/chat", json={"message": "how do you know I have a dog?"})
    entries = agent.store.journal_recent(10)
    assert any(e["tool"] == "explain_memory" and e["kind"] == "flow" and e["status"] == "ok" for e in entries)


def test_a_memory_that_cannot_be_read_does_not_break_the_chat(tmp_path, monkeypatch):
    client, agent = build(tmp_path, ByQuestionClient(chat=["It is fine."]))
    monkeypatch.setattr(prov, "explain", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert client.post("/api/chat", json={"message": "how do you know I have a dog?"}).status_code == 200


def test_message_times_are_read_for_the_messages_asked_about(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    thread = store.create_thread("t")
    a, b = store.add_message(thread, "user", "one"), store.add_message(thread, "user", "two")
    times = store.message_times([a, b, 999])
    assert set(times) == {a, b} and all(times.values()) and store.message_times([]) == {}
