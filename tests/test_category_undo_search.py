"""Taking a category merge back, and searching the one chat by words, category and day (diya_categories.Book.merges / undo_merge / search, diya_categories_api; docs/ONE_CHAT_DESIGN.md; migration 26;
tasks DIYA-156 and DIYA-160), added 2026-10-21.

What this proves, with the real store: a merge leaves a record of exactly which messages it moved; undoing it shows the category again under its own name and puts back those messages and no others (a
message the person moved afterwards, or one that joined the target afterwards, stays where it is, and the count says how many were left); an undo happens once, and not while it could not work (the
category it went into was merged away since, or another category took its name), changing nothing when it is refused; a starter category comes back in its own place and is found by its starter name again;
the same through the page. Search finds the person's words and Diya's, newest first, each with its day and category (a reply counts as the category of the message it answers), narrowed by category or by
the person's own calendar days or a phrase like "last week"; it treats % and _ as themselves, says nothing for a one-letter search, honours the limit, and changes nothing. It does not search by meaning.
"""
import dataclasses
import sqlite3
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import diya
import diya_categories as cat
import diya_config
import diya_web
from diya_db import Store
from fakes import FakeClient, text_reply
from test_categories import FakeTranscriber, LOCAL


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "m.db"))


@pytest.fixture
def book(store):
    return cat.Book(store)


def sql(store, query, args=()):
    conn = sqlite3.connect(store.path)
    try:
        conn.execute(query, args)
        conn.commit()
    finally:
        conn.close()


def said(store, texts, thread=None):
    thread = thread or store.create_thread()
    return thread, [store.add_message(thread, "user", text) for text in texts]


def ids(book):
    return {c["name"]: c["id"] for c in book.listing()}


def where(book, message_ids):
    return book.tags(message_ids)


# ---- taking a merge back ------------------------------------------------------------------------------------------------------

def test_a_merge_leaves_a_record_of_exactly_what_it_moved(store, book):
    _, (a, b, c) = said(store, ["how hot is it", "will it rain", "hello"])
    book.assign(a, "Weather", "code")
    book.assign(b, "Weather", "model")
    book.assign(c, "Chat", "person")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    (merge,) = book.merges()
    assert (merge["source"], merge["target"], merge["count"], merge["undone"], merge["can_undo"], merge["why_not"]) == ("Weather", "Chat", 2, False, True, "")
    assert where(book, [a, b, c]) == {a: "Chat", b: "Chat", c: "Chat"}


def test_undoing_it_shows_the_category_again_and_puts_back_only_the_messages_it_moved(store, book):
    _, (a, b, c) = said(store, ["how hot is it", "will it rain", "hello"])
    book.assign(a, "Weather", "code")
    book.assign(b, "Weather", "person")
    book.assign(c, "Chat", "person")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    assert "Weather" not in ids(book)
    outcome = book.undo_merge(book.merges()[0]["id"])
    assert outcome == {"name": "Weather", "restored": 2, "left": 0}
    assert where(book, [a, b, c]) == {a: "Weather", b: "Weather", c: "Chat"}  # the target's own message stayed
    assert ids(book)["Weather"] == by["Weather"]  # the same category, not a copy
    assert book.merges()[0]["undone"] is True and book.merges()[0]["can_undo"] is False


def test_a_message_changed_since_is_left_where_it_is_and_counted(store, book):
    _, (a, b, c) = said(store, ["how hot is it", "will it rain", "is it sunny"])
    for message in (a, b, c):
        book.assign(message, "Weather", "code")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    book.assign(b, "Learning", "person")  # the person moved this one afterwards
    sql(store, "UPDATE message_categories SET source = 'person' WHERE message_id = ?", (c,))  # and this one was sorted again
    outcome = book.undo_merge(book.merges()[0]["id"])
    assert outcome == {"name": "Weather", "restored": 1, "left": 2}
    assert where(book, [a, b, c]) == {a: "Weather", b: "Learning", c: "Chat"}


def test_a_message_that_joined_the_target_after_the_merge_stays_there(store, book):
    _, (a, b) = said(store, ["how hot is it", "hello"])
    book.assign(a, "Weather", "code")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    book.assign(b, "Chat", "person")
    book.undo_merge(book.merges()[0]["id"])
    assert where(book, [a, b]) == {a: "Weather", b: "Chat"}


def test_it_can_be_undone_once_and_a_refused_undo_changes_nothing(store, book):
    _, (a,) = said(store, ["how hot is it"])
    book.assign(a, "Weather", "code")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    merge_id = book.merges()[0]["id"]
    book.undo_merge(merge_id)
    before = (book.listing(), where(book, [a]), book.merges())
    for bad in (merge_id, 9999):
        with pytest.raises(cat.CategoryError):
            book.undo_merge(bad)
    assert (book.listing(), where(book, [a]), book.merges()) == before


def test_it_cannot_be_undone_while_the_category_it_went_into_has_itself_been_merged_away(store, book):
    _, (a,) = said(store, ["how hot is it"])
    book.assign(a, "Weather", "code")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])  # merge 1: Weather into Chat
    book.merge(by["Chat"], by["Learning"])  # merge 2: Chat into Tasks
    first, second = book.merges()[1], book.merges()[0]
    assert first["can_undo"] is False and "undo that merge first" in first["why_not"]
    with pytest.raises(cat.CategoryError, match="undo that merge first"):
        book.undo_merge(first["id"])
    book.undo_merge(second["id"])  # the later one first ...
    assert book.merges()[1]["can_undo"] is True
    book.undo_merge(first["id"])  # ... then the earlier
    assert where(book, [a]) == {a: "Weather"}


def test_it_cannot_be_undone_while_another_category_has_the_name_and_can_after_a_rename(store, book):
    book.add("Gym", "the first one")
    by = ids(book)
    book.merge(by["Gym"], by["Chat"])
    book.add("Gym", "a new one made after")  # a name the person made themselves can be made again
    (merge,) = book.merges()
    assert merge["can_undo"] is False and "already a category called Gym" in merge["why_not"]
    with pytest.raises(cat.CategoryError, match="already a category called Gym"):
        book.undo_merge(merge["id"])
    book.rename(ids(book)["Gym"], "Fitness")
    assert book.merges()[0]["can_undo"] is True
    book.undo_merge(merge["id"])
    assert {"Gym", "Fitness"} <= set(ids(book))


def test_a_starter_category_comes_back_in_its_own_place_and_is_found_by_its_starter_name(store, book):
    order = [c["name"] for c in book.listing()]
    _, (a,) = said(store, ["how hot is it"])
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    assert book.assign(a, "Weather", "code") == "Chat"  # a rule that still says "Weather" lands in the one it went into
    book.undo_merge(book.merges()[0]["id"])
    assert [c["name"] for c in book.listing()] == order
    assert book.assign(a, "Weather", "code") == "Weather"


def test_the_record_holds_message_numbers_and_never_their_words(store, book):
    _, (a,) = said(store, ["my secret dentist appointment"])
    book.assign(a, "Weather", "person")
    by = ids(book)
    book.merge(by["Weather"], by["Chat"])
    conn = sqlite3.connect(store.path)
    try:
        (moved,) = conn.execute("SELECT moved FROM category_merges").fetchone()
    finally:
        conn.close()
    assert "dentist" not in moved and f"[{a}," in moved.replace(" ", "")


def test_the_database_gets_the_table_in_migration_26(tmp_path):
    from diya_db import MIGRATIONS

    assert 26 in dict(MIGRATIONS)
    conn = Store(str(tmp_path / "x.db")).connect()
    try:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'category_merges'").fetchone()
    finally:
        conn.close()


# ---- searching ----------------------------------------------------------------------------------------------------------------

def talk(store, book, pairs, category="Chat"):
    """A chat of (what the person said, what Diya answered) pairs; the person's messages are put in `category`."""
    thread = store.create_thread()
    made = []
    for question, answer in pairs:
        q = store.add_message(thread, "user", question)
        a = store.add_message(thread, "assistant", answer)
        book.assign(q, category, "person")
        made.append((q, a))
    return thread, made


def test_a_search_finds_both_sides_newest_first_with_the_day_and_the_category(store, book):
    _, ((q1, a1), (q2, a2)) = talk(store, book, [("my dentist is on Thursday", "Noted, Thursday."), ("what about lunch", "Lunch is at one.")], "Chat")
    sql(store, "UPDATE messages SET created_at = '2026-10-12T09:00:00+00:00' WHERE id IN (?, ?)", (q1, a1))
    found = book.search("thursday")
    assert [m["id"] for m in found] == [a1, q1]  # newest first
    assert {m["role"] for m in found} == {"user", "assistant"} and {m["category"] for m in found} == {"Chat"}
    assert found[1]["at"].startswith("2026-10-12") and "dentist" in found[1]["text"]


def test_a_reply_counts_as_the_category_of_the_message_it_answers(store, book):
    talk(store, book, [("how hot is it in Pune", "Pune is 31 degrees.")], "Weather")
    talk(store, book, [("remind me about Pune", "Reminder set for Pune.")], "Learning")
    weather = book.search("pune", category_id=ids(book)["Weather"])
    assert len(weather) == 2 and {m["category"] for m in weather} == {"Weather"}
    assert len(book.search("pune")) == 4


def test_a_search_can_be_narrowed_to_the_persons_own_days(store, book):
    _, ((q1, a1), (q2, a2)) = talk(store, book, [("budget meeting on Monday", "ok"), ("budget numbers again", "ok")])
    sql(store, "UPDATE messages SET created_at = '2026-10-05T12:00:00+00:00' WHERE id IN (?, ?)", (q1, a1))
    sql(store, "UPDATE messages SET created_at = '2026-10-19T12:00:00+00:00' WHERE id IN (?, ?)", (q2, a2))
    from datetime import date

    assert [m["id"] for m in book.search("budget", since=date(2026, 10, 12))] == [q2]
    assert [m["id"] for m in book.search("budget", until=date(2026, 10, 12))] == [q1]
    assert [m["id"] for m in book.search("budget", since=date(2026, 10, 5), until=date(2026, 10, 5))] == [q1]
    assert book.search("budget", since=date(2026, 11, 1)) == []


def test_percent_and_underscore_are_only_themselves_and_a_short_search_says_nothing(store, book):
    talk(store, book, [("it was 100% sure", "ok"), ("a snake_case name", "ok"), ("plain words", "ok")])
    assert len(book.search("100%")) == 1 and len(book.search("snake_case")) == 1
    assert book.search("%") == [] and book.search("x") == [] and book.search("") == [] and book.search(None) == []
    assert book.search("100_") == []  # an underscore is not "any one letter"


def test_the_limit_is_honoured_and_a_search_changes_nothing(store, book):
    talk(store, book, [(f"note number {n}", "ok") for n in range(8)])
    before = (book.listing(), book.merges())
    assert len(book.search("note number", limit=3)) == 3
    assert (book.listing(), book.merges()) == before


# ---- through the page ---------------------------------------------------------------------------------------------------------

def page(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "p.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"),
        dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")]))
    return TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL), agent


def test_a_merge_is_listed_and_undone_through_the_page(tmp_path):
    client, agent = page(tmp_path)
    _, (a,) = said(agent.store, ["how hot is it"])
    book = cat.Book(agent.store)
    book.assign(a, "Weather", "code")
    by = ids(book)
    client.post("/api/categories", json={"action": "merge", "category_id": by["Weather"], "into_id": by["Chat"]})
    shown = client.get("/api/categories").json()
    (merge,) = shown["merges"]
    assert merge["source"] == "Weather" and merge["target"] == "Chat" and merge["count"] == 1 and merge["can_undo"] is True
    answer = client.post("/api/categories", json={"action": "undo_merge", "merge_id": merge["id"]}).json()
    assert answer["undone"] == {"name": "Weather", "restored": 1, "left": 0}
    assert any(c["name"] == "Weather" for c in answer["categories"]) and answer["merges"][0]["undone"] is True
    again = client.post("/api/categories", json={"action": "undo_merge", "merge_id": merge["id"]})
    assert again.status_code == 400 and "already undone" in again.json()["detail"]


def test_a_search_works_through_the_page_and_refuses_what_it_cannot_read(tmp_path):
    client, agent = page(tmp_path)
    book = cat.Book(agent.store)
    _, ((q, a),) = talk(agent.store, book, [("the dentist said \x1b[31mnext week", "Noted.")], "Chat")
    answer = client.post("/api/categories", json={"action": "search", "query": "dentist"}).json()
    (hit,) = answer["results"]
    assert hit["id"] == q and hit["category"] == "Chat" and "\x1b" not in hit["text"]
    today = datetime.now().astimezone().date()
    sql(agent.store, "UPDATE messages SET created_at = ? WHERE id IN (?, ?)", ((datetime.now().astimezone() - timedelta(days=40)).isoformat(), q, a))
    assert client.post("/api/categories", json={"action": "search", "query": "dentist", "when": "yesterday"}).json()["results"] == []
    assert len(client.post("/api/categories", json={"action": "search", "query": "dentist", "until": today.isoformat()}).json()["results"]) == 1
    for body in ({"since": "12/10/2026"}, {"when": "whenever"}):
        refused = client.post("/api/categories", json={"action": "search", "query": "dentist", **body})
        assert refused.status_code == 400 and refused.json()["detail"]


# ---- the page and the API do the same things (task DIYA-237) -------------------------------------------------------------------

def test_every_thing_the_categories_api_can_do_has_a_control_on_a_page():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    api = (root / "diya_categories_api.py").read_text(encoding="utf-8")
    actions = set(re.findall(r'body\.action == "([a-z_]+)"', api))
    assert {"assign", "add", "rename", "merge", "browse", "undo_merge", "search", "suggest", "sort_earlier", "answer_suggestion"} <= actions
    pages = "\n".join(path.read_text(encoding="utf-8") for path in (root / "frontend" / "app").rglob("*.js"))
    missing = [action for action in sorted(actions) if not re.search(rf"action: '{action}'", pages)]
    assert missing == []
