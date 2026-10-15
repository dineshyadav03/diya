"""Diya has ONE chat (docs/ONE_CHAT_DESIGN.md, step 1), added 2026-10-16.

What this proves: the one chat is chosen once and kept (the chat with the newest message, or a new one called Diya when there are none), two callers at the same moment get the same one, and asking
which it is, or looking at the list, makes nothing; a chat message that names no chat goes into it, so the laptop, the phone and Diya's own morning message are one conversation; the page is given only
the newest few hundred messages of it and told when older ones are left out; an earlier chat can still be read, and the page does not write in it; and the page keeps no chat id of its own any more.
"""
import dataclasses
import re
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_proactive as pro
import diya_web
from diya_db import Store
from fakes import FakeClient, text_reply

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
LOCAL = "https://localhost"  # a Host name the API answers to


class FakeTranscriber:
    def transcribe(self, path):
        return "hello"


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "one.db"))


def titles(store):
    conn = store.connect()
    rows = conn.execute("SELECT id, title FROM threads ORDER BY id").fetchall()
    conn.close()
    return rows


# ---- the store ----------------------------------------------------------------------------------------------------------------

def test_with_no_chat_at_all_the_one_chat_is_made_once_and_called_diya(store):
    first = store.main_thread()
    assert store.main_thread() == first and store.main_thread() == first
    assert titles(store) == [(first, "Diya")]


def test_the_one_chat_is_the_chat_with_the_newest_message_the_first_time_and_is_kept_after(store):
    older, newer = store.create_thread(), store.create_thread()
    store.add_message(newer, "user", "talked here first")
    store.add_message(older, "user", "but the newest message is here")
    assert store.main_thread() == older
    store.add_message(newer, "user", "now a newer message lands in the other chat")
    assert store.main_thread() == older  # kept: the one chat does not wander to wherever the last message went
    assert len(titles(store)) == 2


def test_a_kept_chat_that_is_no_longer_there_is_chosen_again(store):
    gone = store.create_thread()
    store.add_message(gone, "user", "hello")
    assert store.main_thread() == gone
    conn = store.connect()
    conn.execute("UPDATE app_state SET value = '999999' WHERE key = 'main_thread'")  # a chat that does not exist
    conn.commit()
    conn.close()
    assert store.main_thread() == gone
    conn = store.connect()
    assert conn.execute("SELECT value FROM app_state WHERE key = 'main_thread'").fetchone()[0] == str(gone)
    conn.close()


def test_asking_which_chat_is_the_one_makes_nothing(store):
    assert store.current_main_thread() is None
    assert titles(store) == []
    chat = store.create_thread()
    store.add_message(chat, "user", "hello")
    assert store.current_main_thread() == chat
    conn = store.connect()
    assert conn.execute("SELECT COUNT(*) FROM app_state").fetchone()[0] == 0  # not even kept: only main_thread() keeps it
    conn.close()


def test_callers_asking_at_the_same_moment_get_the_same_chat_and_only_one_is_made(tmp_path):
    path = str(tmp_path / "race.db")
    Store(path).connect().close()  # the tables exist; the chat does not
    got, problems = [], []

    def ask():
        try:
            got.append(Store(path).main_thread())
        except Exception as exc:  # noqa: BLE001 -- the test reports it
            problems.append(repr(exc))

    workers = [threading.Thread(target=ask) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert not problems and len(got) == 8 and len(set(got)) == 1
    assert len(titles(Store(path))) == 1


def test_the_tail_of_a_chat_is_its_newest_messages_oldest_first_and_says_when_older_ones_were_left_out(store):
    chat = store.create_thread()
    ids = [store.add_message(chat, "user", f"m{number}") for number in range(5)]
    assert store.get_messages_tail(chat, 5) == ([{"id": ids[n], "role": "user", "content": f"m{n}"} for n in range(5)], False)  # exactly as many as asked for: nothing left out
    tail, more = store.get_messages_tail(chat, 3)
    assert [m["content"] for m in tail] == ["m2", "m3", "m4"] and [m["id"] for m in tail] == ids[2:] and more is True
    assert store.get_messages_tail(chat, 50)[1] is False and store.get_messages_tail(store.create_thread(), 3) == ([], False)


# ---- the web routes -----------------------------------------------------------------------------------------------------------

@pytest.fixture
def web(tmp_path):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "web.db"), profile_path=str(tmp_path / "p.txt"), require_token=False, lookup=False)
    model = FakeClient([text_reply("one"), text_reply("two"), text_reply("three")])
    agent = diya.Agent(config, client=model)
    client = TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL)
    return client, agent


def test_the_history_of_main_makes_the_one_chat_on_a_new_database(web):
    client, agent = web
    body = client.get("/api/history/main").json()
    assert body["is_main"] is True and body["messages"] == [] and body["more_before"] is False
    assert [row[0] for row in titles(agent.store)] == [body["thread_id"]]


def test_looking_at_an_earlier_chat_or_the_list_makes_no_chat(web):
    client, agent = web
    assert client.get("/api/threads").json() == {"threads": []}
    assert client.get("/api/history/12").json() == {"thread_id": 12, "is_main": False, "more_before": False, "messages": []}
    assert titles(agent.store) == []


def test_the_list_says_which_chat_is_the_one_chat(web):
    client, agent = web
    old, current = agent.store.create_thread(), agent.store.create_thread()
    agent.store.add_message(old, "user", "an old question")
    agent.store.add_message(current, "user", "the latest question")
    flags = {t["id"]: t["main"] for t in client.get("/api/threads").json()["threads"]}
    assert flags == {old: False, current: True}


@pytest.mark.parametrize("junk", ["abc", "1abc", "main2", "MAIN", "-1", "1" * 19, "١٢"])
def test_a_chat_that_is_neither_main_nor_a_whole_number_is_not_found(web, junk):
    client, _ = web
    assert client.get(f"/api/history/{junk}").status_code == 404


def test_the_page_is_given_only_the_newest_messages_of_the_one_chat(web, monkeypatch):
    client, agent = web
    monkeypatch.setattr(diya_web, "MAX_PAGE_MESSAGES", 4)
    chat = agent.store.create_thread()
    for number in range(6):
        agent.store.add_message(chat, "user" if number % 2 == 0 else "assistant", f"m{number}")
    body = client.get("/api/history/main").json()
    assert [m["content"] for m in body["messages"]] == ["m2", "m3", "m4", "m5"] and body["more_before"] is True
    earlier = agent.store.create_thread()
    for number in range(6):
        agent.store.add_message(earlier, "user", f"e{number}")
    agent.store.add_message(chat, "user", "m6")  # the one chat stays the one chat
    assert len(client.get(f"/api/history/{earlier}").json()["messages"]) == 6  # an earlier chat is read whole, as it always was


def test_a_message_that_names_no_chat_goes_into_the_one_chat_every_time(web):
    client, agent = web
    first = client.post("/api/chat", json={"message": "hello"}).json()
    second = client.post("/api/chat", json={"message": "and again"}).json()
    assert first["thread_id"] == second["thread_id"] == agent.store.main_thread()
    assert [m["content"] for m in agent.store.get_history(first["thread_id"]) if m["role"] == "user"] == ["hello", "and again"]
    assert len(titles(agent.store)) == 1


def test_a_message_that_names_a_chat_still_goes_there(web):
    client, agent = web
    client.post("/api/chat", json={"message": "hello"})
    elsewhere = agent.store.create_thread()
    reply = client.post("/api/chat", json={"thread_id": elsewhere, "message": "in the other one"}).json()
    assert reply["thread_id"] == elsewhere and elsewhere != agent.store.main_thread()


# ---- Diya's own messages and the phone ------------------------------------------------------------------------------------------

def test_the_morning_message_goes_into_the_chat_the_person_is_already_in(store):
    chat = store.create_thread()
    store.add_message(chat, "user", "my chat, in use")
    store.add_message(chat, "assistant", "yes")
    from datetime import datetime
    (row,) = pro.Proactive(store).make(datetime(2026, 10, 12, 8, 45))
    assert row["thread_id"] == chat
    assert store.get_history(chat)[-1] == {"role": "assistant", "content": row["text"]}
    assert len(titles(store)) == 1


# ---- the page ------------------------------------------------------------------------------------------------------------------

def page():
    return (FRONTEND / "app" / "page.js").read_text(encoding="utf-8")


def test_the_page_keeps_no_chat_id_in_the_browser_and_asks_for_the_one_chat_by_name():
    source = page()
    assert "diya_thread_id" not in source  # a browser's own memory of a chat is what made a second chat on every other device
    assert "loadThread(urlThread || 'main')" in source
    assert "function handleNewChat" not in source


def test_an_earlier_chat_is_read_not_written_in():
    source = page()
    assert "setEarlierChat(data.is_main === false)" in source
    assert "if (loadingChat || loadProblem || earlierChat) return" in source  # the backstop in handleSend
    assert 'className="earlier-chat-bar"' in source and 'href="/"' in source[source.index("earlier-chat-bar"):]
    assert "Go back to your chat to write." in source  # the composer says why it is off
    assert "unavailable" in source[source.index("<VoiceBar"):]


def test_a_thread_in_the_address_is_used_only_if_it_is_a_whole_number():
    source = page()
    assert "/^[0-9]{1,18}$/.test(params.get('thread') || '')" in source


def test_the_history_page_says_diya_has_one_chat_and_marks_it():
    source = (FRONTEND / "app" / "history" / "page.js").read_text(encoding="utf-8")
    assert "Diya has one chat" in source and "Your chat now" in source and "t.main" in source


def test_the_composer_has_nothing_that_starts_another_chat():
    voice = (FRONTEND / "components" / "VoiceBar.jsx").read_text(encoding="utf-8")
    assert not re.search(r"new chat", voice, re.IGNORECASE)
