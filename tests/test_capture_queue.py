"""The capture queue: no message of the person's is skipped by memory (diya_db capture_queue, diya_web.read_for_facts; docs/MEMORY_DURABILITY_DESIGN.md), added 2026-10-18.

What this proves: every message of the person's is written down in the queue as it is saved (with automatic memory on, and only then); the reader takes everything that is waiting, one message after
another, and looks again before it lets go, so a message that arrives while another is being read is read next; a message with nothing worth keeping is settled as skipped, one the model could not be
asked about is tried again and after three tries left to the scheduled pass, and one the scheduled pass already read is settled without a second reading; what was left waiting when the program stopped is
read at the next message; and a failure in reading never reaches the chat.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
import dreaming
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient

LOCAL = "https://localhost"


class Quiet:
    def transcribe(self, path):
        return ""


def parts(folder, auto_memory=True, client=None):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(folder / "q.db"), dream_log_path=str(folder / "log"), dream_state_path=str(folder / "state.json"),
        dream_pending_path=str(folder / "pending.jsonl"), profile_path=str(folder / "profile.txt"), auto_memory=auto_memory, require_token=False, categories=False,
    )
    model = client or ByQuestionClient(extraction=["- likes tea in the morning"] * 6)
    agent = diya.Agent(config, client=model)
    return TestClient(diya_web.create_app(config, agent, Quiet()), base_url=LOCAL), agent, model


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "s.db"))


def test_a_message_is_queued_once_and_waits_until_it_is_settled(store):
    thread = store.create_thread()
    first, second = store.add_message(thread, "user", "a"), store.add_message(thread, "user", "b")
    store.enqueue_capture(second)
    store.enqueue_capture(first)
    store.enqueue_capture(first)  # once only
    assert store.pending_captures() == [first, second] and store.capture_backlog() == {"pending": 2}
    store.finish_capture(first, "done")
    store.enqueue_capture(first)  # a message already settled is not put back
    assert store.pending_captures() == [second] and store.capture_backlog() == {"done": 1, "pending": 1}


def test_a_try_that_did_not_work_is_counted_and_the_message_stays_waiting(store):
    thread = store.create_thread()
    message = store.add_message(thread, "user", "a")
    store.enqueue_capture(message)
    assert store.retry_capture(message, "down") == 1 and store.retry_capture(message, "down") == 2
    assert store.pending_captures() == [message]


def test_every_message_the_person_sends_is_queued_when_it_is_saved(tmp_path):
    client, agent, _ = parts(tmp_path)
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    assert agent.store.capture_backlog() == {"done": 1}


def test_with_automatic_memory_off_nothing_is_queued(tmp_path):
    client, agent, _ = parts(tmp_path, auto_memory=False)
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    assert agent.store.capture_backlog() == {}


def test_a_message_with_nothing_worth_keeping_is_settled_as_skipped_without_asking_the_model(tmp_path):
    client, agent, model = parts(tmp_path)
    client.post("/api/chat", json={"message": "what is 9 times 7?"})
    assert agent.store.capture_backlog() == {"skipped": 1} and model.asked("extraction") == []


def test_a_message_the_scheduled_pass_already_read_is_settled_without_a_second_reading(tmp_path):
    client, agent, model = parts(tmp_path)
    thread = agent.store.create_thread()
    message = agent.store.add_message(thread, "user", "I like tea in the morning")
    agent.store.mark_captured(message, 1)
    agent.store.enqueue_capture(message)
    client.post("/api/chat", json={"thread_id": thread, "message": "hello"})
    assert agent.store.capture_backlog().get("done") == 1 and model.asked("extraction") == []


def test_what_was_left_waiting_when_the_program_stopped_is_read_at_the_next_message(tmp_path):
    client, agent, model = parts(tmp_path, client=ByQuestionClient(extraction=["- plays badminton on Sundays", "- likes tea in the morning"]))
    thread = agent.store.create_thread()
    left = agent.store.add_message(thread, "user", "I play badminton on Sundays")
    agent.store.enqueue_capture(left)  # written down, then the program stopped before reading it
    client.post("/api/chat", json={"thread_id": thread, "message": "I like tea in the morning"})
    assert sorted(f["text"] for f in Memory(agent.store).facts()) == ["likes tea in the morning", "plays badminton on Sundays"] and agent.store.capture_backlog() == {"done": 2}


def test_a_model_that_cannot_be_asked_is_tried_three_times_and_then_left_to_the_scheduled_pass(tmp_path):
    class Down(ByQuestionClient):
        def _create(self, model, messages, tools=None, **options):
            if self.kind_of(messages) == "extraction":
                raise ConnectionError("down")
            return super()._create(model, messages, tools, **options)

    client, agent, _ = parts(tmp_path, client=Down())
    for _ in range(3):
        response = client.post("/api/chat", json={"message": "I like tea in the morning"})
        assert response.status_code == 200  # the chat is never broken by it
    # the first message has had three tries (one at each message) and is left to the scheduled pass; the others are still being tried
    assert agent.store.capture_backlog() == {"failed": 1, "pending": 2} and Memory(agent.store).facts() == []


def test_a_failure_in_reading_does_not_reach_the_chat_and_the_message_keeps_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(dreaming.Dreamer, "capture_message", lambda self, message_id: (_ for _ in ()).throw(RuntimeError("boom")))
    client, agent, _ = parts(tmp_path)
    assert client.post("/api/chat", json={"message": "I like tea in the morning"}).status_code == 200
    assert agent.store.capture_backlog() == {"pending": 1}


def test_a_request_to_forget_is_queued_and_read_like_any_other(tmp_path):
    client, agent, _ = parts(tmp_path)
    client.post("/api/chat", json={"message": "I like tea in the morning"})
    assert [f["text"] for f in Memory(agent.store).facts("accepted")] == ["likes tea in the morning"]
    client.post("/api/chat", json={"message": "forget that I like tea"})
    assert Memory(agent.store).facts("accepted") == [] and agent.store.capture_backlog() == {"done": 2}


def test_the_queue_is_in_the_database_schema_as_a_migration(tmp_path):
    import diya_db

    assert 20 in [version for version, _ in diya_db.MIGRATIONS]
    conn = Store(str(tmp_path / "m.db")).connect()
    assert conn.execute("SELECT COUNT(*) FROM capture_queue").fetchone()[0] == 0
    conn.close()


def test_a_message_and_its_reading_job_are_saved_in_one_transaction(store):
    """DIYA-019: there is no moment at which the message is saved and the job to read it is not. If the job cannot be written, the message is not saved either."""
    thread = store.create_thread("t")
    first = store.add_message(thread, "user", "I have a dog named Hog", capture=True)
    assert store.pending_captures() == [first]
    assert store.add_message(thread, "assistant", "ok", capture=True) and store.pending_captures() == [first]  # only the person's messages are queued
    conn = store.connect()
    conn.execute("DROP TABLE capture_queue")  # the queue cannot be written
    conn.commit()
    conn.close()
    before = len(store.get_messages(thread))
    with pytest.raises(Exception):
        store.add_message(thread, "user", "this must not be saved without its job", capture=True)
    assert len(store.get_messages(thread)) == before
    assert store.add_message(thread, "user", "no capture asked, so the queue is not needed")  # unchanged behaviour when capture is off


def test_a_retry_puts_the_job_back_if_a_restart_lost_it(tmp_path):
    client, agent, _ = parts(tmp_path)
    thread = agent.store.create_thread("t")
    message = agent.store.add_message(thread, "user", "I have a dog named Hog")  # saved without a job, as if it had been lost
    assert agent.store.pending_captures() == []
    client.post("/api/chat", json={"message": "I have a dog named Hog", "thread_id": thread})
    conn = agent.store.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM capture_queue WHERE message_id = ?", (message,)).fetchone()[0] == 1  # the message was reused, and its job is there
        assert conn.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'").fetchone()[0] == 1
    finally:
        conn.close()
