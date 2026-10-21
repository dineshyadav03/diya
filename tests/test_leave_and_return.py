"""Leaving the chat while Diya is thinking, and coming back (diya_web's "answering" record, frontend/app/page.js; docs/STREAMING_DESIGN.md), added 2026-10-21.

Found by the owner: send a message, go to another tab (Memory) while Diya is still thinking, come back, and the chat looked dead. The server was not at fault: it finishes the answer and saves it whether or not the page is
still there. The page was: a page that is left forgets it was waiting, and when it comes back it showed the person's message with no reply and nothing to say Diya was still working, and never looked again.

What this proves, with the real routes and a model that is held up until the test lets it go: while a message is being answered the history says so (`answering`), for the plain route and the streaming one, and says
nothing of the sort for another chat; a page that goes away in the middle of a stream (the connection is closed after the first line) does not stop the answer, which is saved, and the history stops saying
"answering" only after it is saved, so a page that asks next finds the reply; a turn that fails stops being "answering"; two messages at once are both counted; and the page shows "still working" and looks again every
few seconds while the server says so, without a loading screen or an error banner, and stops when the answer is there. It does not drive a browser: the pieces are checked here and the page's logic in its source.
"""
import asyncio
import dataclasses
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from fakes import FakeClient, text_reply
from test_categories import FakeTranscriber, LOCAL

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def world(tmp_path, monkeypatch):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "l.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("unused")]))
    client = TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL)
    release, started = threading.Event(), threading.Event()
    calls = []

    def slow_ask(history, thread_id=None, message_id=None, on_event=None):
        calls.append(message_id)
        started.set()
        release.wait(15)
        if getattr(slow_ask, "fail", False):
            raise RuntimeError("the model fell over")
        return "Here is the answer.", []

    monkeypatch.setattr(agent, "ask", slow_ask)
    return client, agent, slow_ask, release, started, calls


def stream_then_leave(app, message):
    """Send `message` to the streaming route as a browser would and then go away: the connection is closed (an ASGI disconnect) as soon as the first line of the reply has arrived. Returns that first line."""
    body = json.dumps({"message": message}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "https", "path": "/api/chat/stream", "raw_path": b"/api/chat/stream", "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())], "client": ("127.0.0.1", 50000), "server": ("localhost", 443),
    }

    async def run():
        leave, got, first = asyncio.Event(), {"request": False}, []

        async def receive():
            if not got["request"]:
                got["request"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            await leave.wait()
            return {"type": "http.disconnect"}

        async def send(event):
            if event["type"] == "http.response.body" and event.get("body") and not first:
                first.append(event["body"].decode())
                leave.set()  # the person goes to another tab

        await asyncio.wait_for(app(scope, receive, send), timeout=60)
        return first[0] if first else ""

    return asyncio.run(run())



def history(client, thread="main"):
    return client.get(f"/api/history/{thread}").json()


def wait_until(check, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def test_while_a_message_is_answered_the_history_says_so_and_stops_saying_it_once_the_answer_is_saved(world):
    client, agent, _ask, release, started, _calls = world
    assert history(client)["answering"] is False
    sender = threading.Thread(target=lambda: client.post("/api/chat", json={"message": "what is the weather"}))
    sender.start()
    assert started.wait(5)
    during = history(client)
    assert during["answering"] is True and [m["role"] for m in during["messages"]] == ["user"]  # the message is there, the reply is not yet
    release.set()
    sender.join(10)
    after = history(client)
    assert after["answering"] is False and [m["role"] for m in after["messages"]] == ["user", "assistant"] and after["messages"][-1]["content"] == "Here is the answer."


def test_leaving_in_the_middle_of_a_stream_does_not_stop_the_answer(world):
    client, agent, _ask, release, started, _calls = world
    first = stream_then_leave(client.app, "what is the weather")
    assert '"type":"start"' in first  # the page had the first line and then went to another tab: the connection was closed
    assert started.wait(5)
    assert history(client)["answering"] is True  # the person comes back: the server says Diya is still on it
    release.set()
    assert wait_until(lambda: history(client)["answering"] is False)
    after = history(client)
    assert [m["role"] for m in after["messages"]] == ["user", "assistant"] and after["messages"][-1]["content"] == "Here is the answer."  # saved though nobody was listening


def test_a_turn_that_fails_stops_being_answering(world):
    client, agent, ask, release, started, _calls = world
    ask.fail = True
    stream_then_leave(client.app, "what is the weather")
    assert started.wait(5)
    release.set()
    assert wait_until(lambda: history(client)["answering"] is False)
    assert [m["role"] for m in history(client)["messages"]] == ["user"]  # no reply was made up


def test_another_chat_is_not_called_answering_and_two_at_once_are_both_counted(world):
    client, agent, _ask, release, started, calls = world
    earlier = agent.store.create_thread()
    agent.store.add_message(earlier, "user", "an older chat")
    main = agent.store.create_thread()
    agent.store.add_message(main, "user", "newest")
    one = threading.Thread(target=lambda: client.post("/api/chat", json={"message": "first", "thread_id": main}))
    two = threading.Thread(target=lambda: client.post("/api/chat", json={"message": "second", "thread_id": main}))
    one.start()
    assert started.wait(5)
    two.start()
    assert wait_until(lambda: len(calls) == 2)
    assert history(client, main)["answering"] is True and history(client, earlier)["answering"] is False
    release.set()
    one.join(10)
    two.join(10)
    assert wait_until(lambda: history(client, main)["answering"] is False)


def test_the_page_shows_still_working_and_looks_again_while_the_server_says_so_and_then_stops():
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "setStillAnswering(data.answering === true)" in page
    assert "function loadThread(threadId, { quiet = false } = {})" in page
    assert "if (!quiet) {" in page and "if (!stale() && !quiet) setLoadProblem" in page  # a look-again shows no loading screen and no error banner
    assert "if (!stillAnswering || thinking) return undefined" in page and "loadThread(threadIdRef.current || 'main', { quiet: true })" in page and "ANSWER_POLL_MS" in page
    assert "[stillAnswering, thinking]" in page  # it stops when the answer is there, and does not run over a message this page is itself sending
    assert "Still working on your last message" in page and "(stillAnswering && !thinking)" in page


def test_no_page_declares_the_same_state_variable_twice():
    """Found on 2026-10-21: a second `const [answering, setAnswering]` in the chat page made it fail to compile, which a syntax check cannot see (only a build or a browser does). Declared names are counted per file."""
    import re
    from collections import Counter

    for path in list((ROOT / "frontend" / "app").rglob("*.js")) + list((ROOT / "frontend" / "components").rglob("*.jsx")):
        source = path.read_text(encoding="utf-8")
        names = re.findall(r"^\s*const \[(\w+), \w+\] = (?:useState|useReducer)\(", source, re.MULTILINE)
        twice = [name for name, count in Counter(names).items() if count > 1]
        assert twice == [], (path.name, twice)


def test_the_design_rig_has_the_leave_and_come_back_scenario():
    rig = (ROOT / "frontend" / "tools" / "design-rig" / "shots.mjs").read_text(encoding="utf-8")
    assert "name: 'chat-still-working'" in rig and "answering: !!window.__answering" in rig  # drawn in a real browser on 2026-10-21 (dark theme, desktop and phone width): every check passed
