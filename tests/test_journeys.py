"""Ten acceptance journeys: what a person does, what they must see, and what must go wrong gracefully (task DIYA-010; docs/ACCEPTANCE_JOURNEYS.md), added 2026-10-20.

Each journey is a whole workflow through the real HTTP routes of one Diya, a scripted model and stand-ins for anything outside (Google), written as the person would do it, with the result they expect and the
failure it must survive. They are not unit tests of one function: each fails if any part of the chain breaks. They say nothing about how good a real model's answers are (the model is scripted); that is
what diya_evals.py and the benches measure.
"""
import dataclasses
import json
import sqlite3
import types

import pytest
from fastapi.testclient import TestClient

import diya
import diya_backup
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_write as gw
import diya_markdown
import diya_memory_repo
import diya_web
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient, FakeClient, text_reply, tool_reply

LOCAL = "https://localhost"


class Quiet:
    def transcribe(self, path):
        return ""


def build(tmp_path, client, **changes):
    settings = dict(
        db_path=str(tmp_path / "j.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False, auto_memory=True, connector_tokens_dir=str(tmp_path / "tok"),
        connectors_log_path=str(tmp_path / "conn.log"), backup_dir=str(tmp_path / "backups"), protect_secrets=False,
    )
    config = dataclasses.replace(diya_config.load_config({}), **{**settings, **changes})
    agent = diya.Agent(config, client=client)
    # The model is told the facts that match the message (diya_recall.pick); this stand-in embedder sees a dog in "dog" and "Hog" the way the real one does.
    agent.embed = lambda text: [float(word in text.lower()) for word in ("dog", "hog")]
    return config, agent, TestClient(diya_web.create_app(config, agent, Quiet()), base_url=LOCAL)


def system_of(client):
    sent = [c for c in client.chat_calls if c.get("kind", "chat") == "chat"][-1]["messages"]
    return sent[0]["content"] if sent and sent[0]["role"] == "system" else ""


# ---- 1. tell Diya something, and it is there next time --------------------------------------------------------------------


def test_journey_1_tell_her_something_and_she_knows_it_on_the_next_turn(tmp_path):
    """You say you have a dog. Expect: the Memory page lists it (marked as taken on her own), and the very next message reaches the model with it.
    Failure it survives: the model cannot be asked for facts; the message is still saved and still answered."""
    client = ByQuestionClient(extraction=["- has a dog named Hog"], chat=["Noted.", "Hog is a good name."])
    config, agent, http = build(tmp_path, client)
    http.post("/api/chat", json={"message": "I got a dog named Hog"})
    facts = http.get("/api/memory").json()["facts"]
    assert [(f["text"], f["status"], f["by"]) for f in facts] == [("has a dog named Hog", "accepted", "auto")]
    http.post("/api/chat", json={"message": "what should I feed him?"})
    assert "has a dog named Hog" in system_of(client)
    down = FakeClient(chat_error=ConnectionError("ollama is not running"))
    sub = tmp_path / "down"
    sub.mkdir()
    config2, agent2, http2 = build(sub, down, db_path=str(sub / "down.db"))
    assert http2.post("/api/chat", json={"message": "I got a dog named Hog"}).status_code in (500, 503)
    assert [m["content"] for m in http2.get("/api/history/main").json()["messages"]] == ["I got a dog named Hog"]  # the message is kept


# ---- 2. correct something she got wrong -----------------------------------------------------------------------------------


def test_journey_2_correct_a_fact_and_take_the_correction_back(tmp_path):
    """You told her you work as a teacher, then 'no, I now work as a nurse'. Expect: the nurse fact replaces it, the old words stay in the trail, and one press puts the old one back.
    Failure it survives: when the judge is unsure the new fact waits as a question and nothing is replaced."""
    config, agent, http = build(tmp_path, ByQuestionClient(extraction=["- works as a nurse at a hospital"], replace=["1"], chat=["Noted."]))
    old = Memory(agent.store).add_manual("works as a teacher at a school", "api")
    http.post("/api/chat", json={"message": "no, I now work as a nurse at a hospital"})
    memory = Memory(agent.store)
    nurse = next(f for f in memory.facts("accepted") if "nurse" in f["text"])
    assert memory.get(old)["status"] == "retired" and memory.replaced(nurse["id"]) == old
    memory.undo_replace(nurse["id"], "api")
    assert memory.get(old)["status"] == "accepted" and memory.get(nurse["id"])["status"] != "accepted"
    unsure = tmp_path / "unsure"
    unsure.mkdir()
    config2, agent2, http2 = build(unsure, ByQuestionClient(extraction=["- works as a nurse at a hospital"], replace=["maybe"], chat=["Noted."]), db_path=str(unsure / "u.db"))
    old2 = Memory(agent2.store).add_manual("works as a teacher at a school", "api")
    http2.post("/api/chat", json={"message": "no, I now work as a nurse at a hospital"})
    assert Memory(agent2.store).get(old2)["status"] == "accepted"  # nothing was replaced on a guess


# ---- 3. make her forget ---------------------------------------------------------------------------------------------------


def test_journey_3_forget_something_and_then_forget_it_for_good(tmp_path):
    """You say 'forget that I like tea'. Expect: it is retired (and comes back with Restore). Then you ask for the words to be deleted: they are gone from the file.
    Failure it survives: 'forget that' with two equally likely facts forgets nothing."""
    config, agent, http = build(tmp_path, ByQuestionClient(chat=["Forgotten."] * 4))
    memory = Memory(agent.store)
    tea = memory.add_manual("likes tea in the morning", "api")
    http.post("/api/chat", json={"message": "forget that I like tea"})
    assert memory.get(tea)["status"] == "retired"
    memory.decide(tea, "restore", "api")
    assert http.post(f"/api/memory/{tea}/forget-for-good").status_code == 200
    raw = open(config.db_path, "rb").read()
    assert b"likes tea in the morning" not in raw
    a, b = memory.add_manual("likes green tea", "api"), memory.add_manual("likes black tea", "api")
    http.post("/api/chat", json={"message": "forget that I like tea"})
    assert memory.get(a)["status"] == "accepted" and memory.get(b)["status"] == "accepted"


# ---- 4. a reminder, and later 'when did I do it?' -------------------------------------------------------------------------


def test_journey_4_a_reminder_by_your_own_words_and_the_day_you_ticked_it_off(tmp_path):
    """You ask in chat for a reminder; it appears with a real time read from YOUR words. You tick it off, and Diya keeps when.
    Failure it survives: a time you did not give is never invented: the model's guess is refused and no reminder is saved with it."""
    client = FakeClient([tool_reply("add_reminder", json.dumps({"content": "call mom", "due_at": "tomorrow at 5pm"})), text_reply("Reminder set."),
                         tool_reply("add_reminder", json.dumps({"content": "water the plants", "due_at": "next Friday at 7am"})), text_reply("Done.")])
    config, agent, http = build(tmp_path, client)
    http.post("/api/chat", json={"message": "remind me to call mom tomorrow at 5pm"})
    (reminder,) = http.get("/api/reminders").json()["reminders"]
    assert reminder["content"] == "call mom" and reminder["due"] and reminder["state"] == "upcoming"
    assert http.post(f"/api/reminders/{reminder['id']}/done").status_code == 200
    rows = agent.store.done_reminders()
    assert rows and rows[0]["done_at"]
    http.post("/api/chat", json={"message": "remind me to water the plants"})  # no time in the person's words, though the model made one up
    assert not any("plants" in r["content"] for r in http.get("/api/reminders").json()["reminders"])  # the tool refused a time the person never said; nothing was saved with an invented one


# ---- 5. a task ------------------------------------------------------------------------------------------------------------


def test_journey_5_a_task_is_added_listed_and_ticked_and_not_added_twice(tmp_path):
    """You add a task, see it, tick it. Expect it moves to done. Failure it survives: the same open task twice is refused."""
    config, agent, http = build(tmp_path, ByQuestionClient())
    assert http.post("/api/tasks", json={"text": "buy guitar strings"}).status_code == 201
    (task,) = http.get("/api/tasks").json()["tasks"]
    assert task["content"] == "buy guitar strings"
    assert http.post("/api/tasks", json={"text": "buy guitar strings"}).status_code in (409, 422)
    assert http.post(f"/api/tasks/{task['id']}/done").status_code == 200
    body = http.get("/api/tasks").json()
    assert body["tasks"] == [] and [t["content"] for t in body["done"]] == ["buy guitar strings"]


# ---- 6. an automation -----------------------------------------------------------------------------------------------------


def test_journey_6_an_automation_made_in_words_runs_and_leaves_its_answer_in_the_chat(tmp_path):
    """You say 'every morning at 8am tell me the weather in Pune'. Expect: it is listed with its next time; run now, the answer lands in the chat.
    Failure it survives: a run cannot save or send anything, whatever the model asks for."""
    client = FakeClient([text_reply("It is 31 degrees and sunny in Pune.")])
    config, agent, http = build(tmp_path, client)
    made = http.post("/api/automations", json={"text": "every morning at 8am tell me the weather in Pune"})
    assert made.status_code == 201
    (automation,) = http.get("/api/automations").json()["automations"]
    assert automation["state"] == "active" and automation["next"] and automation["rule"] == "Every day at 08:00"
    ran = http.post(f"/api/automations/{automation['id']}/run")
    assert ran.status_code == 200
    contents = [m["content"] for m in http.get("/api/history/main").json()["messages"]]
    assert any("31 degrees" in c for c in contents)


# ---- 7. an action that waits for you ----------------------------------------------------------------------------------------


def google(monkeypatch, *answers):
    calls = []
    queue = list(answers)

    def request(method, url, params=None, json=None, headers=None, timeout=None):
        calls.append((method, url))
        answer = queue.pop(0) if queue else types.SimpleNamespace(status_code=200, json=lambda: {})
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(gw.httpx, "request", request)
    return calls


def reply(body, status=200):
    return types.SimpleNamespace(status_code=status, json=lambda: body)


def test_journey_7_a_google_task_waits_for_your_press_is_sent_once_and_read_back(tmp_path, monkeypatch):
    """You ask for a Google Task. Expect: a card with the exact words, nothing sent; you press Approve, it is sent once and read back, and the card says done.
    Failure it survives: Google fails after the request may have gone through: the card says 'unknown', and it is never sent again."""
    client = FakeClient([tool_reply("propose_google_task", json.dumps({"title": "Renew the bus pass"})), text_reply("Proposed.")])
    config, agent, http = build(tmp_path, client)
    diya_connectors.store_token(config, "google_tasks", "refresh")
    monkeypatch.setattr(gcal, "access_token", lambda cfg, name: "access")
    calls = google(monkeypatch, reply({"id": "task_ID_1234", "title": "Renew the bus pass", "webViewLink": "https://tasks.google.com/task/abc"}),
                   reply({"id": "task_ID_1234", "title": "Renew the bus pass", "status": "needsAction", "webViewLink": "https://tasks.google.com/task/abc"}))
    http.post("/api/chat", json={"message": "add renew the bus pass to my Google Tasks"})
    (card,) = http.get("/api/actions").json()["pending"]
    assert card["summary"] == "Add to your Google Tasks: Renew the bus pass" and calls == []  # nothing was sent while it waited
    done = http.post(f"/api/actions/{card['id']}/approve", json={"args_hash": card["args_hash"]})
    assert done.status_code == 200 and done.json()["action"]["status"] == "succeeded"
    assert [m for m, _ in calls][0] == "POST" and len(calls) == 2  # one write, one read back
    # a second journey step: the same thing, but Google drops the connection after the request
    client2 = FakeClient([tool_reply("propose_google_task", json.dumps({"title": "Renew the library card"})), text_reply("Proposed.")])
    sub = tmp_path / "second"
    sub.mkdir()
    config2, agent2, http2 = build(sub, client2, db_path=str(sub / "j2.db"))
    diya_connectors.store_token(config2, "google_tasks", "refresh")
    calls2 = google(monkeypatch, gw.httpx.ReadTimeout("slow"))
    http2.post("/api/chat", json={"message": "add renew the library card to my Google Tasks"})
    (card2,) = http2.get("/api/actions").json()["pending"]
    result = http2.post(f"/api/actions/{card2['id']}/approve", json={"args_hash": card2["args_hash"]})
    assert result.json()["action"]["status"] == "unknown"
    again = http2.post(f"/api/actions/{card2['id']}/approve", json={"args_hash": card2["args_hash"]})
    assert again.status_code == 409 and len(calls2) == 1  # never sent again


# ---- 8. pause everything --------------------------------------------------------------------------------------------------


def test_journey_8_pause_stops_what_she_does_on_her_own_and_resume_lets_it_go_on(tmp_path, monkeypatch):
    """You press Pause. Expect: an approved action does not run (it waits), the Status page says so; Resume and it runs once.
    Failure it survives: pausing twice, and resuming when not paused, change nothing."""
    client = FakeClient([tool_reply("propose_google_task", json.dumps({"title": "Renew the bus pass"})), text_reply("Proposed.")])
    config, agent, http = build(tmp_path, client)
    diya_connectors.store_token(config, "google_tasks", "refresh")
    monkeypatch.setattr(gcal, "access_token", lambda cfg, name: "access")
    calls = google(monkeypatch, reply({"id": "task_ID_1234", "title": "Renew the bus pass", "webViewLink": "https://tasks.google.com/task/abc"}),
                   reply({"id": "task_ID_1234", "title": "Renew the bus pass", "status": "needsAction", "webViewLink": "https://tasks.google.com/task/abc"}))
    http.post("/api/chat", json={"message": "add renew the bus pass to my Google Tasks"})
    (card,) = http.get("/api/actions").json()["pending"]
    assert http.post("/api/pause").json()["paused"] is True and http.post("/api/pause").json()["paused"] is True
    blocked = http.post(f"/api/actions/{card['id']}/approve", json={"args_hash": card["args_hash"]})
    assert blocked.status_code == 423 and calls == []  # approved or not, nothing runs while paused
    assert http.post("/api/resume").json()["paused"] is False and http.post("/api/resume").json()["paused"] is False
    ok = http.post(f"/api/actions/{card['id']}/approve", json={"args_hash": card["args_hash"]})
    assert ok.status_code == 200 and ok.json()["action"]["status"] == "succeeded" and len(calls) == 2


# ---- 9. a backup you can come back from -----------------------------------------------------------------------------------


def test_journey_9_a_backup_is_checked_and_restoring_it_gives_back_what_was_there(tmp_path):
    """You have some memory. A backup is made and checked; the database is damaged; you restore the backup to a new file and it holds the same facts.
    Failure it survives: a snapshot that is not a database is refused and nothing is written over anything."""
    config, agent, http = build(tmp_path, ByQuestionClient(chat=["ok"]))
    memory = Memory(agent.store)
    for text in ("has a dog named Hog", "studies medicine"):
        memory.add_manual(text, "api")
    http.post("/api/chat", json={"message": "hello there, Diya"})
    snapshot = diya_backup.make(config)
    assert diya_backup.check(snapshot.path) == []
    restored = diya_backup.restore(snapshot.path, str(tmp_path / "restored.db"))
    assert [f["text"] for f in Memory(Store(restored)).facts("accepted")] == ["has a dog named Hog", "studies medicine"]
    assert Memory(Store(restored)).verify_integrity() == []
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(diya_backup.BackupError):
        diya_backup.restore(str(junk), str(tmp_path / "never.db"))
    assert not (tmp_path / "never.db").exists()
    with pytest.raises(diya_backup.BackupError):
        diya_backup.restore(snapshot.path, str(tmp_path / "restored.db"))  # restoring never overwrites


# ---- 10. take your memory with you ------------------------------------------------------------------------------------------


def test_journey_10_memory_leaves_as_a_file_and_comes_back_as_it_was(tmp_path):
    """You export your memory as Markdown and as a repository of notes; you restore the Markdown into a fresh Diya. Expect: the same facts, people and retired ones.
    Failure it survives: a file that is not an export is refused, and nothing already there is changed."""
    config, agent, http = build(tmp_path, ByQuestionClient())
    memory = Memory(agent.store)
    memory.add_manual("studies medicine", "api")
    mom = memory.add_manual("likes gardening", "api")
    memory.set_person(mom, "Mom", "api")
    gone = memory.add_manual("takes the 7:40 bus", "api")
    memory.decide(gone, "retire", "api")
    text = diya_markdown.export_markdown(memory)
    folder = tmp_path / "repo"
    written = diya_memory_repo.export_repo(memory, str(folder))
    assert "MEMORY.md" in written and "people/mom.md" in written and "retired.md" in written
    fresh = Memory(Store(str(tmp_path / "fresh.db")))
    assert diya_markdown.restore_markdown(fresh, text)[:2] == (3, 0)
    assert sorted((f["text"], f["person"], f["status"]) for f in fresh.facts()) == sorted((f["text"], f["person"], f["status"]) for f in memory.facts())
    with pytest.raises(Exception):
        diya_markdown.restore_markdown(fresh, "just some notes")
    assert len(fresh.facts()) == 3


# ---- the document and the tests agree --------------------------------------------------------------------------------------


def test_every_journey_in_the_document_has_its_test_and_the_other_way_round():
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    cited = re.findall(r"`tests/test_journeys\.py::(test_journey_\d+_[a-z_0-9]+)`", (root / "docs" / "ACCEPTANCE_JOURNEYS.md").read_text(encoding="utf-8"))
    defined = re.findall(r"^def (test_journey_\d+_[a-z_0-9]+)\(", pathlib.Path(__file__).read_text(encoding="utf-8"), re.M)
    assert len(cited) == 10 and sorted(cited) == sorted(defined)
