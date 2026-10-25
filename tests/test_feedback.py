"""What the person thinks of Diya's replies (diya_feedback, diya_feedback_api, the chat page, migration 27; docs/FEEDBACK_DESIGN.md), added 2026-10-21.

What this proves, with the real store and the real routes: a rating is kept against the person's own message and read back; the reason must be one of the fixed list and a note must hold words and fit the limit
and is kept exactly as written; saying the same thing again changes nothing, and changing it raises the version; a change made from a stale page is refused with the current item and writes nothing, and so is
removing something already changed or already gone; only a message of the person's own can be rated; the numbers (how many, how many not helpful, why) hold no note and no message; forgetting a message takes its
feedback with it; the routes say what is wrong in plain words (400) or what changed (409); the page offers the buttons on the person's own messages, sends everything through one function, and its list of reasons is the
same as the Python one; and the scorecard reports the counts. It does not read the notes to the model: nothing here is ever given to it.
"""
import dataclasses
import re
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
    store = Store(str(tmp_path / "f.db"))
    thread = store.create_thread()
    mine = store.add_message(thread, "user", "how hot is it in Pune")
    reply = store.add_message(thread, "assistant", "It is 31 degrees.")
    return store, fb.Feedback(store), mine, reply


def test_a_rating_is_kept_against_the_persons_message_and_read_back(world):
    store, feedback, mine, _reply = world
    item = feedback.put(mine, "negative", "wrong", "It said 31 but my phone says 28.")
    assert (item["message_id"], item["rating"], item["category"], item["note"], item["version"]) == (mine, "negative", "wrong", "It said 31 but my phone says 28.", 1)
    assert feedback.items([mine, 999]) == {mine: item}


def test_only_a_message_of_the_persons_own_can_be_rated(world):
    _store, feedback, _mine, reply = world
    for bad in (reply, 999):
        with pytest.raises(fb.FeedbackError, match="no such message of yours"):
            feedback.put(bad, "positive")


@pytest.mark.parametrize("kwargs, words", [
    ({"rating": "meh"}, "helpful or not helpful"), ({"rating": None}, "helpful or not helpful"),
    ({"rating": "negative", "category": "boring"}, "not one of the reasons"),
    ({"rating": "negative", "note": "   "}, "needs some words"), ({"rating": "negative", "note": ""}, "needs some words"), ({"rating": "negative", "note": 5}, "needs some words"),
    ({"rating": "negative", "note": "x" * (fb.MAX_NOTE_CHARS + 1)}, "at most"),
])
def test_what_cannot_be_kept_is_refused_in_words_and_nothing_is_written(world, kwargs, words):
    _store, feedback, mine, _reply = world
    with pytest.raises(fb.FeedbackError, match=words):
        feedback.put(mine, **kwargs)
    assert feedback.items([mine]) == {}


def test_a_note_is_kept_exactly_as_written_and_the_longest_allowed_is_kept(world):
    _store, feedback, mine, _reply = world
    note = "  two spaces first, a tab\tand a last line\n"
    assert feedback.put(mine, "negative", None, note)["note"] == note
    other = feedback.put(mine, "negative", None, "y" * fb.MAX_NOTE_CHARS, version=1)
    assert len(other["note"]) == fb.MAX_NOTE_CHARS


def test_saying_the_same_again_changes_nothing_and_a_change_raises_the_version(world):
    _store, feedback, mine, _reply = world
    first = feedback.put(mine, "positive")
    assert feedback.put(mine, "positive", version=first["version"]) == first  # no new version, same time
    second = feedback.put(mine, "negative", "slow", version=first["version"])
    assert second["version"] == 2 and second["rating"] == "negative" and second["category"] == "slow"


def test_a_stale_page_is_refused_with_the_current_item_and_writes_nothing(world):
    _store, feedback, mine, _reply = world
    first = feedback.put(mine, "positive")
    feedback.put(mine, "negative", "wrong", version=first["version"])  # another page changed it
    with pytest.raises(fb.Conflict) as caught:
        feedback.put(mine, "positive", version=first["version"])  # this page still thinks it is version 1
    assert caught.value.current["rating"] == "negative" and caught.value.current["version"] == 2
    assert feedback.items([mine])[mine]["rating"] == "negative"
    with pytest.raises(fb.Conflict):
        feedback.put(mine, "positive")  # creating what already exists
    feedback.delete(mine, 2)
    with pytest.raises(fb.Conflict) as gone:
        feedback.put(mine, "positive", version=2)  # changing what another page has removed
    assert gone.value.current is None


def test_removing_needs_the_version_seen_and_fails_if_it_is_already_gone(world):
    _store, feedback, mine, _reply = world
    item = feedback.put(mine, "positive")
    with pytest.raises(fb.Conflict):
        feedback.delete(mine, item["version"] + 1)
    assert mine in feedback.items([mine])
    feedback.delete(mine, item["version"])
    assert feedback.items([mine]) == {}
    with pytest.raises(fb.Conflict):
        feedback.delete(mine, item["version"])


def test_the_numbers_hold_counts_only_never_a_note_or_a_message(world):
    store, feedback, mine, _reply = world
    thread = store.main_thread()
    second = store.add_message(thread, "user", "my secret dentist visit")
    third = store.add_message(thread, "user", "and another")
    feedback.put(mine, "negative", "wrong", "private words about my dentist")
    feedback.put(second, "negative", "wrong")
    feedback.put(third, "positive")
    summary = feedback.summary()
    assert summary == {"rated": 3, "positive": 1, "negative": 2, "by_reason": {"wrong": 2}}
    assert "dentist" not in str(summary) and "Pune" not in str(summary)
    assert feedback.summary(days=0, now=fb.datetime.now(fb.timezone.utc) + fb.timedelta(days=1)) == {"rated": 0, "positive": 0, "negative": 0, "by_reason": {}}


def test_forgetting_a_message_takes_its_feedback_with_it(world, tmp_path):
    import dataclasses as dc

    import diya_forget
    import diya_memory

    store, feedback, mine, _reply = world
    feedback.put(mine, "negative", "wrong", "a note")
    config = dc.replace(diya_config.load_config({}), db_path=store.path, profile_path=str(tmp_path / "p.txt"), dream_pending_path=str(tmp_path / "pending.jsonl"))
    diya_forget.forget_message(store, diya_memory.open_memory(store, config), config, mine)
    assert feedback.items([mine]) == {}
    conn = store.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM reply_feedback").fetchone()[0] == 0
    finally:
        conn.close()


# ---- the routes ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def web(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "w.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")]))
    thread = agent.store.create_thread()
    mine = agent.store.add_message(thread, "user", "how hot is it")
    return TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL), mine


def test_the_routes_create_list_change_and_remove(web):
    client, mine = web
    made = client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "negative", "category": "made-up", "note": "invented a number"}).json()["item"]
    assert made["version"] == 1 and made["category"] == "made-up"
    listed = client.post("/api/feedback", json={"action": "list", "message_ids": [mine, 999]}).json()
    assert list(listed["items"]) == [str(mine)] and listed["reasons"] == fb.CATEGORIES
    changed = client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "positive", "version": 1}).json()["item"]
    assert changed["version"] == 2 and changed["rating"] == "positive"
    assert client.post("/api/feedback", json={"action": "delete", "message_id": mine, "version": 2}).json() == {"deleted": True}
    assert client.post("/api/feedback", json={"action": "list", "message_ids": [mine]}).json()["items"] == {}


def test_a_refusal_is_a_400_in_words_and_a_stale_change_is_a_409_with_the_current_item(web):
    client, mine = web
    refused = client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "great"})
    assert refused.status_code == 400 and "helpful or not helpful" in refused.json()["detail"]
    assert client.post("/api/feedback", json={"action": "nonsense"}).status_code == 400
    client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "positive"})
    stale = client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "negative", "version": 7})
    assert stale.status_code == 409 and stale.json()["current"]["rating"] == "positive" and "another page" in stale.json()["detail"]
    assert client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "positive"}).status_code == 409  # creating what exists


def test_a_note_is_shown_as_text_with_control_characters_removed(web):
    client, mine = web
    item = client.post("/api/feedback", json={"action": "put", "message_id": mine, "rating": "negative", "note": "bad" + chr(0x1b) + "[31m reply"}).json()["item"]
    assert chr(0x1b) not in item["note"]


# ---- the page -----------------------------------------------------------------------------------------------------------------

def test_the_page_offers_the_buttons_on_the_persons_own_messages_and_its_reasons_are_the_python_ones():
    page = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
    assert "Helpful" in page and "Not helpful" in page and "What was wrong?" in page and page.count("fetch('/api/feedback'") == 1  # every kind of request goes through one function
    block = page.split("const FEEDBACK_REASONS = {", 1)[1].split("}", 1)[0]
    reasons = dict(re.findall(r"'?([a-z-]+)'?: '([^']+)'", block))
    assert reasons == fb.CATEGORIES
    assert (ROOT / "frontend" / "app" / "api" / "feedback" / "route.js").is_file()
    assert "{replyTo !== null && renderRating(replyTo, { text: m.text, asked })}" in page  # under Diya's reply, for the message it answers
    row = page.split('className="msg-tag-row"', 1)[1].split("</div>", 1)[0]
    assert "msg-rate" not in row and "Helpful" not in row  # and not under the person's own message
    rig = (ROOT / "frontend" / "tools" / "design-rig" / "shots.mjs").read_text(encoding="utf-8")
    assert "name: 'chat-feedback'" in rig


def test_the_scorecard_reports_the_counts(world, monkeypatch):
    import diya_scorecard as sc

    store, feedback, mine, _reply = world
    feedback.put(mine, "negative", "wrong")
    found = sc.measure_live(store)
    assert found["rated"] == 1 and found["not_helpful"] == 1
    text = sc.render(found, {"rules": {"labelled": 1, "placed": 1, "right": 1}, "tests": 1}, [], sc.datetime.now(sc.timezone.utc))
    assert "Replies rated not helpful" in text and "| 1 of 1 |" in text
