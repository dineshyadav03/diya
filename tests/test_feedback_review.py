"""Looking back at the replies that were marked not helpful (diya_feedback.Feedback.negatives, POST /api/feedback {"action": "negatives"}, a section of the Activity page), added 2026-10-25.

The buttons under a reply record what the person thought; until now nothing let them read it back. What this proves, with the real store and routes: only "not helpful" ratings are listed, newest first, each
with the person's words, the reply that followed in the same thread (None if there is none yet, never another chat's) and the reason and note; the number is capped; what is sent is made safe to show
(control and invisible characters escaped, long text cut); forgetting a message takes its line out of the list; and the page shows it read-only, with no button that changes or removes anything. It does not
read these to the model: nothing in this feature is ever given to it.
"""
import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_feedback as fb
import diya_web
from diya_db import Store
from fakes import FakeClient, text_reply
from test_categories import FakeTranscriber, LOCAL

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def world(tmp_path):
    store = Store(str(tmp_path / "n.db"))
    return store, fb.Feedback(store)


def asked(store, thread, question, answer=None):
    message = store.add_message(thread, "user", question)
    reply = store.add_message(thread, "assistant", answer) if answer is not None else None
    return message, reply


def test_only_not_helpful_ones_are_listed_newest_first_with_the_words_the_reply_and_the_reason(world):
    store, feedback = world
    thread = store.create_thread()
    first, _ = asked(store, thread, "how hot is it in Pune", "It is 31 degrees.")
    second, _ = asked(store, thread, "what is my dog called", "Your dog is called Rocky.")
    third, _ = asked(store, thread, "remind me at 5", "Done.")
    feedback.put(first, "negative", "wrong", "my phone says 28")
    feedback.put(second, "positive")
    feedback.put(third, "negative")
    found = feedback.negatives()
    assert [item["message_id"] for item in found] == [third, first]  # newest first, the helpful one left out
    top = found[1]
    assert (top["message"], top["reply"], top["category"], top["note"], top["rating"]) == ("how hot is it in Pune", "It is 31 degrees.", "wrong", "my phone says 28", "negative")
    assert found[0]["category"] is None and found[0]["note"] is None


def test_the_reply_is_the_one_that_followed_in_the_same_chat_and_none_when_there_is_none_yet(world):
    store, feedback = world
    one, two = store.create_thread(), store.create_thread()
    unanswered, _ = asked(store, one, "a question with no answer yet")
    asked(store, two, "another chat", "an answer in another chat")  # must never be mixed in
    feedback.put(unanswered, "negative")
    assert feedback.negatives()[0]["reply"] is None


def test_the_list_is_capped_and_the_cap_is_a_number_not_a_guess(world):
    store, feedback = world
    thread = store.create_thread()
    for number in range(30):
        message, _ = asked(store, thread, f"question {number}", f"answer {number}")
        feedback.put(message, "negative")
    assert len(feedback.negatives()) == fb.REVIEW_LIMIT == 20
    assert len(feedback.negatives(limit=5)) == 5
    assert len(feedback.negatives(limit=10_000)) == 30  # a larger ask is allowed up to what exists, never beyond the hard cap
    assert fb.REVIEW_HARD_CAP >= 30


def test_forgetting_a_message_takes_it_out_of_the_list(world, tmp_path):
    import diya_forget
    import diya_memory

    store, feedback = world
    thread = store.create_thread()
    message, _ = asked(store, thread, "something to forget", "an answer")
    feedback.put(message, "negative", "other", "a note")
    config = dataclasses.replace(diya_config.load_config({}), db_path=store.path, profile_path=str(tmp_path / "p.txt"), dream_pending_path=str(tmp_path / "pending.jsonl"))
    diya_forget.forget_message(store, diya_memory.open_memory(store, config), config, message)
    assert feedback.negatives() == []


@pytest.fixture
def web(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "w.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")]))
    return TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL), agent.store


def test_the_route_sends_them_made_safe_to_show_and_cut_short(web):
    client, store = web
    thread = store.create_thread()
    message, _ = asked(store, thread, "hello" + chr(0x1b) + "[31m there" + "\U000e0041" + " " + "q" * 900, "reply" + chr(0x202e) + "evil " + "r" * 900)
    client.post("/api/feedback", json={"action": "put", "message_id": message, "rating": "negative", "category": "wrong", "note": "bad" + chr(0x1b) + "[1m"})
    body = client.post("/api/feedback", json={"action": "negatives"}).json()
    item = body["items"][0]
    assert body["reasons"] == fb.CATEGORIES and item["category"] == "wrong"
    for text in (item["message"], item["reply"], item["note"]):
        assert chr(0x1b) not in text and chr(0x202e) not in text and "\U000e0041" not in text
    assert item["message"].endswith("...") and item["reply"].endswith("...") and len(item["message"]) < 400 and len(item["reply"]) < 700  # cut with an ellipsis, not sent whole (the escapes add a few characters)
    assert item["version"] == 1 and "message_id" in item


def test_the_route_with_nothing_marked_says_so_with_an_empty_list(web):
    client, _store = web
    assert client.post("/api/feedback", json={"action": "negatives"}).json()["items"] == []


def test_the_activity_page_shows_them_and_offers_nothing_that_changes_them():
    page = (ROOT / "frontend" / "app" / "activity" / "page.js").read_text(encoding="utf-8")
    assert "Replies you marked not helpful" in page and "action: 'negatives'" in page and "fetch('/api/feedback'" in page
    section = page.split('aria-label="Replies you marked not helpful"', 1)[1].split("</section>", 1)[0]
    assert "<button" not in section and "onClick" not in section and "method: 'DELETE'" not in section  # a list to read, nothing here changes or removes feedback
    assert "dangerouslySetInnerHTML" not in page  # what is shown is text, never markup
