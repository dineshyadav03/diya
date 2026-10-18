"""Forget for good (diya_forget.py, Memory.purge, the two routes; docs/FORGET_DESIGN.md), added 2026-10-18 for the owner's decision 234.

What this proves, with the real memory, chat route and database file: a fact forgotten for good loses its words everywhere Diya keeps them (the fact, the line it was read from, its history, its questions,
its vector, the staged-queue file) and the words are not left in the database file either; its trail still says that a fact was here and was forgotten, and the memory's own integrity check still passes;
deleting a message removes it and Diya's reply and what was derived from them, and with "also forget what was learned" the facts whose recorded source is that message, and only those; what was MADE from
the message (a task, an approved action) is kept and unlinked; a preview changes nothing; and both routes are reachable and refuse what they should.
"""
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_forget as forget
import diya_memory
import diya_recall
import diya_web
from diya_db import Store
from diya_memory import IllegalTransition, Memory, UnknownFact
from fakes import ByQuestionClient

SECRET = "zebrafinch"  # a word nothing else in these tests says


class Quiet:
    def transcribe(self, path):
        return ""


def build(folder, client=None):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(folder / "f.db"), dream_log_path=str(folder / "log"), dream_state_path=str(folder / "state.json"), dream_pending_path=str(folder / "pending.jsonl"),
        profile_path=str(folder / "profile.txt"), auto_memory=True, require_token=False, categories=True, lookup=False,
    )
    model = client or ByQuestionClient(extraction=[f"- keeps a {SECRET} named Hog"], chat=["Noted."] * 8)
    agent = diya.Agent(config, client=model)
    return TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost"), agent, config


def db_bytes(config):
    with open(config.db_path, "rb") as f:
        return f.read()


def said(client, text):
    return client.post("/api/chat", json={"message": text}).json()["message_id"]


# ---- a fact ------------------------------------------------------------------------------------------------------------------------------------

def test_a_fact_forgotten_for_good_loses_its_words_everywhere_and_keeps_a_trail_that_says_so(tmp_path):
    client, agent, config = build(tmp_path)
    message = said(client, f"I keep a {SECRET} named Hog")
    memory = Memory(agent.store)
    (fact,) = [f for f in memory.facts() if SECRET in f["text"]]
    diya_recall.vectors(agent.store, [{"id": fact["id"], "text": fact["text"], "text_key": diya_memory.text_key(fact["text"])}], lambda t: [1.0, 0.0], "m")
    with open(config.dream_pending_path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"first_message_id": message, "last_message_id": message, "facts": [f"- keeps a {SECRET} named Hog", "- likes tea"]}) + "\n")
    assert SECRET.encode() in db_bytes(config)
    answer = client.post(f"/api/memory/{fact['id']}/forget-for-good")
    assert answer.status_code == 200 and answer.json()["fact"] == fact["id"] and answer.json()["staged_lines_cleaned"] == 1
    after = memory.get(fact["id"])
    assert after["text"] == diya_memory.PURGED_PLACEHOLDER and after["status"] == "rejected" and after["raw"] is None and after["flags"] == [] and after["batch_first"] is None
    events = memory.events(fact["id"])
    assert events[-1][0] == "purged" and json.loads(events[-1][3]) == {"was": "accepted"} and all(detail is None for _e, _a, _t, detail in events[:-1])
    conn = agent.store.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM fact_embeddings WHERE fact_id = ?", (fact["id"],)).fetchone()[0] == 0
    finally:
        conn.close()
    assert SECRET not in open(config.dream_pending_path, encoding="utf-8").read() and "likes tea" in open(config.dream_pending_path, encoding="utf-8").read()
    assert memory.verify_integrity() == []
    assert SECRET not in memory.render() and SECRET not in " ".join(f["text"] for f in memory.facts())
    assert db_bytes(config).count(SECRET.encode()) == 1  # only the person's own message still has the word (it was not deleted); the fact left none behind in the file


def test_the_words_are_gone_from_the_database_file_too_once_the_message_is_also_deleted(tmp_path):
    client, agent, config = build(tmp_path)
    message = said(client, f"I keep a {SECRET} named Hog")
    assert SECRET.encode() in db_bytes(config)
    client.post(f"/api/messages/{message}/forget", json={"also_learned": True})
    assert SECRET.encode() not in db_bytes(config)


def test_every_status_can_be_forgotten_and_a_second_time_or_an_unknown_fact_is_refused(tmp_path):
    client, agent, _ = build(tmp_path)
    memory = Memory(agent.store)
    accepted = memory.add_manual("studies medicine", "api")
    retired = memory.add_manual("lives in Delhi", "api")
    memory.decide(retired, "retire", "api")
    for fact in (accepted, retired):
        assert client.post(f"/api/memory/{fact}/forget-for-good").status_code == 200
    assert client.post(f"/api/memory/{accepted}/forget-for-good").status_code == 409  # already forgotten
    assert client.post("/api/memory/9999/forget-for-good").status_code == 404
    assert client.post("/api/memory/0/forget-for-good").status_code == 404
    with pytest.raises(UnknownFact):
        memory.purge(9999, "api")
    with pytest.raises(IllegalTransition):
        memory.purge(accepted, "api")
    assert memory.verify_integrity() == [] and memory.counts()["accepted"] == 0


def test_a_candidate_with_questions_loses_them_too(tmp_path):
    client, agent, _ = build(tmp_path)
    store, memory = agent.store, Memory(agent.store)
    thread = store.create_thread("t")
    message = store.add_message(thread, "user", "I take medicine for my knee")
    fact = memory.add_candidate("takes medicine for the knee", batch_first=message, batch_last=message, position=message, model="m", extracted_at="2026-10-10T00:00:00+00:00", raw="- takes medicine")
    conn = store.connect()
    conn.execute("INSERT INTO memory_questions (fact_id, kind, created_at) VALUES (?, 'sensitive', 'now')", (fact,))
    conn.commit()
    conn.close()
    assert client.post(f"/api/memory/{fact}/forget-for-good").status_code == 200
    conn = store.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM memory_questions WHERE fact_id = ?", (fact,)).fetchone()[0] == 0
    finally:
        conn.close()


def test_the_staged_file_is_left_alone_when_it_is_missing_or_not_about_the_fact(tmp_path):
    _, agent, config = build(tmp_path)
    memory = Memory(agent.store)
    fact = memory.add_manual("studies medicine", "api")
    assert forget.forget_fact(memory, config, fact)["staged_lines_cleaned"] == 0  # no file at all
    with open(config.dream_pending_path, "w", encoding="utf-8") as f:
        f.write("not json\n" + json.dumps({"facts": ["- likes tea"]}) + "\n\n")
    other = memory.add_manual("likes rain", "api")
    assert forget.forget_fact(memory, config, other)["staged_lines_cleaned"] == 0
    assert open(config.dream_pending_path, encoding="utf-8").read().startswith("not json\n")


# ---- a message ---------------------------------------------------------------------------------------------------------------------------------

def test_a_preview_says_what_would_happen_and_changes_nothing(tmp_path):
    client, agent, config = build(tmp_path)
    message = said(client, f"I keep a {SECRET} named Hog")
    before = (db_bytes(config), len(agent.store.get_messages(agent.store.main_thread())))
    report = client.post(f"/api/messages/{message}/forget", json={"dry_run": True}).json()
    assert report["dry_run"] is True and report["replies"] == 1 and report["facts"] == 1 and len(report["message_ids"]) == 2 and report["not_reached"]
    assert (db_bytes(config), len(agent.store.get_messages(agent.store.main_thread()))) == before


def test_deleting_a_message_removes_it_its_reply_and_what_was_derived_from_them(tmp_path):
    client, agent, config = build(tmp_path)
    said(client, "hello there")
    message = said(client, f"I keep a {SECRET} named Hog")
    store = agent.store
    ids_before = [m["id"] for m in store.get_messages(store.main_thread())]
    report = client.post(f"/api/messages/{message}/forget", json={"also_learned": True}).json()
    assert report["facts"] == 1 and report["replies"] == 1 and report["dry_run"] is False
    remaining = store.get_messages(store.main_thread())
    assert [m["id"] for m in remaining] == [i for i in ids_before if i not in report["message_ids"]] and all(SECRET not in m["content"] for m in remaining)
    conn = store.connect()
    try:
        for table in ("message_categories", "capture_queue", "memory_captures"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE message_id = ?", (message,)).fetchone()[0] == 0, table
    finally:
        conn.close()
    memory = Memory(store)
    assert all(SECRET not in f["text"] for f in memory.facts()) and memory.verify_integrity() == []
    assert any(e["tool"] == "forget_for_good" and e["kind"] == "flow" for e in store.journal_recent(10)) and SECRET not in json.dumps(store.journal_recent(20))


def test_without_also_learned_the_fact_stays(tmp_path):
    client, agent, _ = build(tmp_path)
    message = said(client, f"I keep a {SECRET} named Hog")
    report = client.post(f"/api/messages/{message}/forget", json={"also_learned": False}).json()
    assert report["facts"] == 0 and any(SECRET in f["text"] for f in Memory(agent.store).facts("accepted"))


def test_only_the_facts_read_from_that_message_are_forgotten(tmp_path):
    client, agent, _ = build(tmp_path, ByQuestionClient(extraction=["- plays badminton on Sundays", "- keeps a zebrafinch named Hog"], chat=["Noted."] * 8))
    first = said(client, "I play badminton on Sundays")
    second = said(client, f"I keep a {SECRET} named Hog")
    client.post(f"/api/messages/{second}/forget", json={"also_learned": True})
    texts = [f["text"] for f in Memory(agent.store).facts("accepted")]
    assert texts == ["plays badminton on Sundays"]
    assert agent.store.get_messages_between(first, first)


def test_a_fact_read_from_a_wide_batch_with_no_recorded_source_is_counted_but_kept(tmp_path):
    client, agent, _ = build(tmp_path)
    store, memory = agent.store, Memory(agent.store)
    thread = store.create_thread("t")
    a, b, c = (store.add_message(thread, "user", text) for text in ("one", "two", "three"))
    unsure = memory.add_candidate("some fact", batch_first=a, batch_last=c, position=a, model="m", extracted_at="2026-10-10T00:00:00+00:00", raw="- some fact")
    report = forget.forget_message(store, memory, agent.config, b, also_learned=True, dry_run=True)
    assert report["facts"] == 0 and report["facts_unsure"] == 1
    forget.forget_message(store, memory, agent.config, b, also_learned=True)
    assert memory.get(unsure)["text"] == "some fact"


def test_what_was_made_from_the_message_is_kept_and_unlinked_and_reported(tmp_path):
    client, agent, config = build(tmp_path)
    store = agent.store
    message = said(client, "add a task to buy milk")
    task = agent.tasks.add("buy milk", None, source="chat", thread_id=store.main_thread(), message_id=message)
    report = client.post(f"/api/messages/{message}/forget", json={"dry_run": True}).json()
    assert report["kept_and_unlinked"]["tasks"] == 1
    client.post(f"/api/messages/{message}/forget")
    kept = [t for t in agent.tasks.tasks("open") if t["content"] == "buy milk"]
    assert len(kept) == 1 and kept[0]["message_id"] is None and task


def test_only_the_persons_own_messages_can_be_deleted_and_unknown_ones_are_refused(tmp_path):
    client, agent, _ = build(tmp_path)
    message = said(client, "hello")
    reply_id = [m["id"] for m in agent.store.get_messages(agent.store.main_thread()) if m["role"] == "assistant"][0]
    assert client.post(f"/api/messages/{reply_id}/forget").status_code == 404
    assert client.post("/api/messages/99999/forget").status_code == 404
    assert client.post("/api/messages/0/forget").status_code == 404
    assert client.post(f"/api/messages/{message}/forget", json={"also_learned": "maybe"}).status_code == 422


def test_the_reply_of_a_deleted_message_goes_but_the_next_exchange_stays(tmp_path):
    client, agent, _ = build(tmp_path)
    first = said(client, "first thing")
    said(client, "second thing")
    client.post(f"/api/messages/{first}/forget")
    left = [m["content"] for m in agent.store.get_messages(agent.store.main_thread())]
    assert "second thing" in left and "first thing" not in left and left.count("Noted.") == 1


def test_the_forget_routes_are_not_shadowed_by_the_memory_pages_generic_action_route(tmp_path):
    client, agent, _ = build(tmp_path)
    fact = Memory(agent.store).add_manual("studies medicine", "api")
    assert client.post(f"/api/memory/{fact}/forget-for-good").status_code == 200  # not "there is no action forget-for-good"
    assert client.post(f"/api/memory/{fact}/nonsense").status_code == 404
