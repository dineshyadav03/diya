"""Putting what is said into categories (diya_categories, diya_categories_api; docs/ONE_CHAT_DESIGN.md, step 2), added 2026-10-16.

What this proves: code places a message only when it can tell and is never wrong when it does (measured on a labelled set); an answer from the model is read strictly (exactly one of the listed
names, or nothing); a model that cannot answer, or answers something that is not on the list, loses nothing: the message takes the category of the one before it, else Chat; there is no "Other"
and the model cannot make up a category; the person can add, rename and re-assign, and a renamed starter category is still found by the name code knows it by; each exchange is sorted after the
reply (both chat routes), never before it, and a failure to sort never breaks a chat; the one chat's history carries each message's id and category; and DIYA_CATEGORIES=0 turns it off.
"""
import dataclasses
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import diya
import diya_categories as cat
import diya_config
import diya_web
from diya_db import Store
from fakes import FakeClient, text_reply
from labelled_categories import LETTERS, MESSAGES

LOCAL = "https://localhost"


class FakeTranscriber:
    def transcribe(self, path):
        return "hello"


class Said:
    """A stand-in for the model that answers a classification: records what it was asked."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.asked.append(kwargs)
        answer = self.answers.pop(0) if self.answers else ""
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "c.db"))


@pytest.fixture
def book(store):
    return cat.Book(store)


def user_message(store, text, thread=None):
    thread = thread or store.create_thread()
    return thread, store.add_message(thread, "user", text)


# ---- code decides what it can ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tools, expected", [
    (["get_weather"], "Weather"), (["add_reminder"], "Reminders & tasks"), (["list_tasks"], "Reminders & tasks"), (["search_notes"], "About me"),
    (["list_files"], "About Diya"), (["web_search"], "Learning"), (["something_new", "get_weather", "add_task"], "Weather"),  # the first known tool decides
])
def test_a_tool_that_ran_says_what_the_exchange_was_about(tools, expected):
    assert cat.by_code("anything at all", tools) == expected


@pytest.mark.parametrize("text, expected", [
    ("hey", "Chat"), ("good morning", "Chat"), ("what can you do", "About Diya"), ("how do i connect you to my google account", "About Diya"),
    ("remind me to call mom tomorrow", "Reminders & tasks"), ("add buy milk to my to-do list", "Reminders & tasks"), ("I'm allergic to peanuts", "About me"),
    ("what's the weather in Pune", "Weather"), ("quick check", "Chat"), ("final verification test", "Chat"),
    ("check the weather then", "Weather"), ("remind me to check the audit results tomorrow", "Reminders & tasks"),  # a "check" that is about something else is not a test
])
def test_the_shape_of_a_message_places_it_when_it_is_clear(text, expected):
    assert cat.by_code(text) == expected


@pytest.mark.parametrize("text", ["how does a transformer neural network work", "who won the world cup in 2018", "what should I do this weekend", "", "   ", None, 5, "check the long report and tell me what is wrong with the third chapter now"])
def test_what_code_cannot_tell_is_left_to_the_model(text):
    assert cat.by_code(text) is None


def test_whatever_code_places_in_the_labelled_set_it_places_right():
    placed = [(text, letters, cat.by_code(text)) for text, letters in MESSAGES if cat.by_code(text)]
    assert len(placed) >= 10  # it is not a rule that never fires
    assert [(t, got) for t, letters, got in placed if got not in {LETTERS[letter] for letter in letters}] == []


# ---- the model's answer is read strictly -----------------------------------------------------------------------------------------

NAMES = [name for name, _ in cat.STARTER]


@pytest.mark.parametrize("answer, expected", [
    ("Weather", "Weather"), ("weather", "Weather"), ("  \"About me\"  ", "About me"), ("Learning.", "Learning"), ("**About Diya**", "About Diya"),
    ("Category: Reminders & tasks", "Reminders & tasks"), ("Chat\nbecause it is a greeting", "Chat"),
    ("Weather or Chat", None), ("Other", None), ("NEW: School", None), ("", None), ("   ", None), (None, None), (5, None),
])
def test_the_models_answer_counts_only_if_it_names_exactly_one_listed_category(answer, expected):
    assert cat.read_answer(answer, NAMES) == expected


def test_a_word_inside_a_longer_word_is_not_a_category():
    assert cat.read_answer("Chatting", NAMES) is None and cat.read_answer("Weathering", NAMES) is None


def test_the_question_names_every_category_and_the_message_and_asks_for_the_closest():
    asked = cat.prompt_for("how hot is it\nin Chennai", cat.STARTER)
    assert all(name in asked for name in NAMES) and "how hot is it in Chennai" in asked and "closest" in asked
    assert "NEW" not in asked and "Other" not in asked  # the model is never offered a way out


def test_a_long_message_is_cut_before_it_is_shown_to_the_model():
    assert "x" * cat.MAX_TEXT_CHARS in cat.prompt_for("x" * 5000, cat.STARTER) and "x" * (cat.MAX_TEXT_CHARS + 1) not in cat.prompt_for("x" * 5000, cat.STARTER)


def test_an_answer_that_is_not_usable_is_asked_for_again_once_then_given_up_on():
    model = Said("hmm, hard to say", "Weather")
    assert cat.by_model(model, "m", "how hot is it", cat.STARTER) == "Weather" and len(model.asked) == 2
    model = Said("no idea", "still no idea", "Weather")
    assert cat.by_model(model, "m", "how hot is it", cat.STARTER) is None and len(model.asked) == 2


def test_the_question_is_asked_with_no_creativity_and_a_short_answer():
    model = Said("Chat")
    cat.by_model(model, "my-model", "ok", cat.STARTER)
    assert model.asked[0]["model"] == "my-model" and model.asked[0]["temperature"] == 0 and model.asked[0]["max_tokens"] <= 32


# ---- the book -----------------------------------------------------------------------------------------------------------------

def test_the_starter_categories_are_made_once_in_order_with_nothing_called_other(book):
    first = [name for name, _ in book.categories()]
    assert first == NAMES and not [n for n in first if n.lower() == "other"]
    assert [name for name, _ in book.categories()] == first and len(book.listing()) == len(NAMES)


def test_a_message_is_in_one_category_and_can_be_moved(store, book):
    _, message = user_message(store, "hello")
    assert book.assign(message, "weather", "code") == "Weather"  # the name is found whatever the case, and returned as kept
    assert book.tags([message]) == {message: "Weather"}
    book.assign(message, "Chat", "person")
    assert book.tags([message]) == {message: "Chat"} and sum(c["count"] for c in book.listing()) == 1


def test_only_a_message_of_the_persons_that_exists_can_be_put_in_a_category_that_exists(store, book):
    thread, message = user_message(store, "hello")
    reply = store.add_message(thread, "assistant", "hi")
    for message_id, name in ((reply, "Chat"), (9999, "Chat"), (message, "Nonsense"), (message, "Other")):
        with pytest.raises(cat.CategoryError):
            book.assign(message_id, name, "person")
    assert book.tags([message, reply]) == {}


def test_a_message_with_none_before_it_has_no_previous_and_the_previous_is_from_the_same_chat_only(store, book):
    thread, first = user_message(store, "what's the weather")
    store.add_message(thread, "assistant", "sunny")
    second = store.add_message(thread, "user", "and tomorrow?")
    _, elsewhere = user_message(store, "unrelated, in another chat")
    assert book.previous(first) is None
    book.assign(first, "Weather", "code")
    assert book.previous(second) == "Weather" and book.previous(elsewhere) is None


def test_the_person_can_add_a_category_with_a_usable_name(store, book):
    new = book.add("school work", "classes, exams, homework")
    assert {c["id"]: c["name"] for c in book.listing()}[new] == "School work"
    for bad in ("", "   ", "one two three four", "x" * 31, "!!!"):
        with pytest.raises(cat.CategoryError):
            book.add(bad)
    for taken in ("school WORK", "weather"):
        with pytest.raises(cat.CategoryError):
            book.add(taken)


def test_there_can_be_only_so_many_categories(book):
    for number in range(cat.MAX_CATEGORIES - len(cat.STARTER)):
        book.add(f"Topic {number}")
    with pytest.raises(cat.CategoryError):
        book.add("One too many")


def test_a_renamed_starter_category_is_still_found_by_the_name_code_knows_it_by(store, book):
    weather = next(c["id"] for c in book.listing() if c["name"] == "Weather")
    assert book.rename(weather, "weather and travel") == "Weather and travel"
    _, message = user_message(store, "how hot is it")
    assert book.assign(message, "Weather", "code") == "Weather and travel"
    assert "Weather and travel" in [name for name, _ in book.categories()] and "Weather" not in [name for name, _ in book.categories()]
    with pytest.raises(cat.CategoryError):
        book.rename(weather, "Chat")  # another category's name
    with pytest.raises(cat.CategoryError):
        book.rename(9999, "Anything")


# ---- sorting one message --------------------------------------------------------------------------------------------------------

def test_code_places_a_message_without_asking_the_model(store, book):
    _, message = user_message(store, "what's the weather in Pune")
    model = Said()
    assert cat.sort(book, model, "m", message, "what's the weather in Pune") == ("Weather", "code") and model.asked == []


def test_the_model_places_what_code_cannot(store, book):
    _, message = user_message(store, "how does a transformer neural network work")
    assert cat.sort(book, Said("Learning"), "m", message, "how does a transformer neural network work") == ("Learning", "model")


def test_a_model_that_is_down_or_unclear_never_loses_the_message(store, book):
    thread, first = user_message(store, "what's the weather")
    cat.sort(book, Said(), "m", first, "what's the weather")
    second = store.add_message(thread, "user", "a muddled thing")
    assert cat.sort(book, Said("hmm", "hmm"), "m", second, "a muddled thing") == ("Weather", "continued")  # stays on the subject of the one before
    third = store.add_message(thread, "user", "another muddled thing")
    assert cat.sort(book, Said(RuntimeError("Ollama is down")), "m", third, "another muddled thing") == ("Weather", "continued")
    _, alone = user_message(store, "a muddled thing, first in its chat")
    assert cat.sort(book, Said(RuntimeError("down")), "m", alone, "a muddled thing, first in its chat") == ("Chat", "continued")


def test_the_model_cannot_make_up_a_category(store, book):
    _, message = user_message(store, "file access limits please")
    assert cat.sort(book, Said("NEW: File access limits", "NEW: File access limits"), "m", message, "file access limits please")[0] == "Chat"
    assert [name for name, _ in book.categories()] == NAMES


# ---- the routes ---------------------------------------------------------------------------------------------------------------

def build(tmp_path, *replies, **changes):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False, categories=True, **changes)
    model = FakeClient(list(replies))
    agent = diya.Agent(config, client=model)
    return TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL), agent, model


def test_each_exchange_is_sorted_after_the_reply_and_the_history_says_where(tmp_path):
    client, agent, model = build(tmp_path, text_reply("Hi there!"), text_reply("A transformer works by attention."), text_reply("Learning"))
    first = client.post("/api/chat", json={"message": "hello"}).json()
    second = client.post("/api/chat", json={"message": "how does a transformer neural network work"}).json()
    history = client.get("/api/history/main").json()["messages"]
    by_id = {m["id"]: m for m in history}
    assert by_id[first["message_id"]]["category"] == "Chat" and by_id[second["message_id"]]["category"] == "Learning"
    assert all("category" not in m for m in history if m["role"] == "assistant")
    assert len(model.chat_calls) == 3  # two answers and ONE question to the model: code placed the greeting


def test_the_reply_comes_before_the_sorting_and_a_model_that_fails_to_sort_breaks_nothing(tmp_path):
    client, agent, model = build(tmp_path, text_reply("A transformer works by attention."))  # nothing left for the question that follows
    body = client.post("/api/chat", json={"message": "how does a transformer neural network work"}).json()
    assert body["answer"] == "A transformer works by attention."
    assert client.get("/api/history/main").json()["messages"][0]["category"] == "Chat"  # no usable answer, nothing before it: Chat, never nowhere


def test_the_streamed_route_sorts_too(tmp_path):
    client, agent, _ = build(tmp_path, text_reply("Hi!"))
    start = client.post("/api/chat/stream", json={"message": "hey"}).text
    assert '"type":"done"' in start
    message = agent.store.get_messages(agent.store.main_thread())[0]["id"]
    assert agent.store.connect().execute("SELECT COUNT(*) FROM message_categories WHERE message_id = ?", (message,)).fetchone()[0] == 1


def test_with_categories_off_nothing_is_sorted_and_the_model_is_not_asked(tmp_path):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "off.db"), profile_path=str(tmp_path / "p.txt"), require_token=False, categories=False)
    model = FakeClient([text_reply("Hi!")])
    client = TestClient(diya_web.create_app(config, diya.Agent(config, client=model), FakeTranscriber()), base_url=LOCAL)
    client.post("/api/chat", json={"message": "hello"})
    assert all("category" not in m for m in client.get("/api/history/main").json()["messages"])


def test_the_list_and_where_the_newest_messages_are(tmp_path):
    client, agent, _ = build(tmp_path, text_reply("Hi!"))
    sent = client.post("/api/chat", json={"message": "hello"}).json()
    body = client.get("/api/categories").json()
    assert [c["name"] for c in body["categories"]] == NAMES and body["tags"] == {str(sent["message_id"]): "Chat"}
    assert {c["name"]: c["count"] for c in body["categories"]}["Chat"] == 1


def test_the_list_on_a_new_database_makes_no_chat(tmp_path):
    client, agent, _ = build(tmp_path)
    assert client.get("/api/categories").json()["tags"] == {} and agent.store.list_threads() == []


def test_the_person_can_move_a_message_add_a_category_and_rename_one(tmp_path):
    client, agent, _ = build(tmp_path, text_reply("Hi!"))
    sent = client.post("/api/chat", json={"message": "hello"}).json()
    moved = client.post("/api/categories", json={"action": "assign", "message_id": sent["message_id"], "category": "About me"}).json()
    assert moved["tags"] == {str(sent["message_id"]): "About me"}
    added = client.post("/api/categories", json={"action": "add", "name": "School", "meaning": "classes and exams"}).json()
    school = next(c for c in added["categories"] if c["name"] == "School")
    renamed = client.post("/api/categories", json={"action": "rename", "category_id": school["id"], "name": "College"}).json()
    assert "College" in [c["name"] for c in renamed["categories"]] and "School" not in [c["name"] for c in renamed["categories"]]
    again = client.post("/api/categories", json={"action": "assign", "message_id": sent["message_id"], "category": "College"}).json()
    assert again["tags"] == {str(sent["message_id"]): "College"}


@pytest.mark.parametrize("body", [
    {"action": "assign", "message_id": 1, "category": "Nonsense"}, {"action": "assign", "category": "Chat"}, {"action": "add", "name": ""},
    {"action": "add", "name": "Weather"}, {"action": "rename", "category_id": 9999, "name": "X"}, {"action": "delete"}, {"action": "add"},
])
def test_what_cannot_be_done_is_refused_in_plain_words_and_changes_nothing(tmp_path, body):
    client, agent, _ = build(tmp_path)
    response = client.post("/api/categories", json=body)
    assert response.status_code == 400 and isinstance(response.json()["detail"], str) and response.json()["detail"]
    assert [c["name"] for c in client.get("/api/categories").json()["categories"]] == NAMES


def test_sorting_two_exchanges_at_once_does_not_trip_over_itself(tmp_path):
    client, agent, _ = build(tmp_path)
    thread = agent.store.create_thread()
    ids = [agent.store.add_message(thread, "user", text) for text in ("hey", "hello", "good morning", "hi", "yo")]
    book = cat.Book(agent.store)
    workers = [threading.Thread(target=cat.sort, args=(book, Said(), "m", i, text)) for i, text in zip(ids, ("hey", "hello", "good morning", "hi", "yo"))]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert book.tags(ids) == {i: "Chat" for i in ids} and len(book.listing()) == len(NAMES)


# ---- the page ------------------------------------------------------------------------------------------------------------------

def page_source():
    from pathlib import Path

    return (Path(__file__).resolve().parent.parent / "frontend" / "app" / "page.js").read_text(encoding="utf-8")


def test_the_page_shows_each_message_with_its_category_as_a_menu_and_puts_back_a_change_that_failed():
    source = page_source()
    assert "select className=\"msg-tag\"" in source and "aria-label=\"Category of this message\"" in source
    start = source.index("async function moveMessage")
    move = source[start:source.index("\n  }\n", start)]
    assert "action: 'assign'" in move and "setTags((shown) => ({ ...shown, [serverId]: before }))" in move  # put back
    assert "Nothing was changed" in move


def test_the_page_can_look_at_the_chat_by_category_and_a_new_message_is_never_hidden_by_it():
    source = page_source()
    assert "function inCategory(messages, tags, name)" in source and "lookingAt ? inCategory(messages, tags, lookingAt) : messages" in source
    assert "aria-pressed={lookingAt === null}" in source and "aria-pressed={lookingAt === name}" in source
    send = source[source.index("async function handleSend"):]
    assert send.index("setLookingAt(null)") < send.index("addMsg('user'")


def test_the_page_looks_for_where_a_new_message_went_after_diya_has_had_time_to_sort_it():
    source = page_source()
    assert "serverId: data.message_id" in source and "setTimeout(loadCategories, 4000)" in source and "setTimeout(loadCategories, 15000)" in source


def test_there_is_no_other_category_anywhere_in_the_starting_list_or_the_page():
    assert not [name for name, _ in cat.STARTER if name.lower() == "other"]
    assert "'Other'" not in page_source() and '"Other"' not in page_source()
