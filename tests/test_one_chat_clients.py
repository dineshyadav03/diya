"""One chat across clients: two devices and a reconnect show the same durable conversation, with no duplicate history (task DIYA-154; docs/ONE_CHAT_DESIGN.md), added 2026-10-20.

What this proves, through the real HTTP routes of one server: a message sent from one client is in the history the other client reads, in order and with the same ids; each client writing in turn gives one
conversation, never a second chat; asking for the chat by name, by nothing, or after the server has been restarted on the same database gives the same chat and the same messages; a turn that failed and is
tried again leaves one message, not two; and the streamed route and the plain route write the same way. It does not prove a phone's browser behaves (the page keeps no chat id of its own, which
tests/test_one_chat.py checks in the page's code).
"""
import dataclasses

from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from fakes import ByQuestionClient, FakeClient, text_reply

LOCAL = "https://localhost"


class Quiet:
    def transcribe(self, path):
        return ""


def server(tmp_path, client):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "c.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False, auto_memory=False,
    )
    return config, diya_web.create_app(config, diya.Agent(config, client=client), Quiet())


def history(http):
    body = http.get("/api/history/main").json()
    return body["thread_id"], [(m["id"], m["role"], m["content"]) for m in body["messages"]]


def test_two_devices_see_one_conversation_in_the_same_order(tmp_path):
    config, app = server(tmp_path, ByQuestionClient(chat=["Hi phone.", "Hi laptop.", "Third."]))
    phone, laptop = TestClient(app, base_url=LOCAL), TestClient(app, base_url=LOCAL)
    phone.post("/api/chat", json={"message": "hello from the phone"})
    thread_phone, seen_by_laptop = history(laptop)
    assert [(role, content) for _, role, content in seen_by_laptop] == [("user", "hello from the phone"), ("assistant", "Hi phone.")]
    laptop.post("/api/chat", json={"message": "hello from the laptop"})
    phone.post("/api/chat", json={"message": "and back on the phone"})
    thread_laptop, on_laptop = history(laptop)
    thread_again, on_phone = history(phone)
    assert thread_phone == thread_laptop == thread_again and on_laptop == on_phone and len(on_phone) == 6
    assert [i for i, _, _ in on_phone] == sorted(i for i, _, _ in on_phone) and len({i for i, _, _ in on_phone}) == 6  # in order, none twice
    assert len(phone.get("/api/threads").json()["threads"]) == 1  # and there is one chat


def test_naming_the_chat_or_not_naming_it_is_the_same_chat(tmp_path):
    config, app = server(tmp_path, ByQuestionClient(chat=["one", "two", "three"]))
    a, b = TestClient(app, base_url=LOCAL), TestClient(app, base_url=LOCAL)
    first = a.post("/api/chat", json={"message": "no chat named"}).json()["thread_id"]
    second = b.post("/api/chat", json={"message": "the chat named", "thread_id": first}).json()["thread_id"]
    third = a.post("/api/chat", json={"message": "named again later"}).json()["thread_id"]
    assert first == second == third and len(a.get("/api/threads").json()["threads"]) == 1


def test_a_restart_on_the_same_database_shows_the_same_chat(tmp_path):
    config, app = server(tmp_path, ByQuestionClient(chat=["one", "two"]))
    http = TestClient(app, base_url=LOCAL)
    http.post("/api/chat", json={"message": "before the restart"})
    before = history(http)
    _, restarted = server(tmp_path, ByQuestionClient(chat=["three"]))  # a new process: new objects, the same file
    again = TestClient(restarted, base_url=LOCAL)
    assert history(again) == before
    again.post("/api/chat", json={"message": "after the restart"})
    thread, messages = history(again)
    assert thread == before[0] and [m[2] for m in messages][:2] == ["before the restart", "one"] and len(messages) == 4
    assert len(again.get("/api/threads").json()["threads"]) == 1


def test_a_turn_that_failed_and_is_tried_again_leaves_one_message(tmp_path):
    client = FakeClient(chat_error=ConnectionError("ollama is not running"))
    config, app = server(tmp_path, client)
    http = TestClient(app, base_url=LOCAL)
    failed = http.post("/api/chat", json={"message": "are you there?"})
    assert failed.status_code in (500, 503)  # (the page is told in fixed words; the message stays)
    _, after_failure = history(http)
    assert [(r, c) for _, r, c in after_failure] == [("user", "are you there?")]  # the message was kept
    client._chat_error = None
    client.replies = [text_reply("Yes.")]
    ok = http.post("/api/chat", json={"message": "are you there?"})
    assert ok.status_code == 200
    _, after_retry = history(http)
    assert [(r, c) for _, r, c in after_retry] == [("user", "are you there?"), ("assistant", "Yes.")]  # one message, not two


def test_the_streamed_route_and_the_plain_route_write_the_same_way(tmp_path):
    config, app = server(tmp_path, FakeClient([text_reply("plain answer"), text_reply("streamed answer")]))
    a, b = TestClient(app, base_url=LOCAL), TestClient(app, base_url=LOCAL)
    a.post("/api/chat", json={"message": "plain question"})
    with b.stream("POST", "/api/chat/stream", json={"message": "streamed question"}) as reply:
        b_lines = [line for line in reply.iter_lines() if line]
    assert any('"type":"done"' in line for line in b_lines)
    thread, messages = history(a)
    assert [(r, c) for _, r, c in messages] == [("user", "plain question"), ("assistant", "plain answer"), ("user", "streamed question"), ("assistant", "streamed answer")]
    assert len(a.get("/api/threads").json()["threads"]) == 1
