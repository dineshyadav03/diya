"""Managing the categories, and Diya's suggestions (diya_categories, diya_category_ideas, diya_categories_api, dreaming.look_for_categories; docs/ONE_CHAT_DESIGN.md, step 4), added 2026-10-16.

What this proves: a category can be merged into another without losing where its messages went (and code that knows it by its starter name still finds the one it went into); a category's messages can
be browsed across every chat; the model is asked for a topic NAME only and code checks every yes, so nothing is suggested from too few messages, from a name that is already a category or was refused,
or while another suggestion waits; the person ticks which messages move; sorting the earlier chats sorts only what is in no category, oldest first, one message at a time, and can be stopped; the
background jobs run one at a time and say how far they are; an earlier chat's messages carry their categories; and Dreaming sorts what is left and looks for a suggestion once a day, never raising.
"""
import dataclasses
import threading
import time

import pytest
from fastapi.testclient import TestClient

import diya
import diya_categories as cat
import diya_category_ideas as ideas
import diya_config
import diya_web
import dreaming
from diya_db import Store
from fakes import FakeClient, text_reply
from test_categories import FakeTranscriber, LOCAL, Said

NAMES = [name for name, _ in cat.STARTER]


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "m.db"))


@pytest.fixture
def book(store):
    return cat.Book(store)


def said(store, texts, thread=None):
    thread = thread or store.create_thread()
    return thread, [store.add_message(thread, "user", text) for text in texts]


def listing_ids(book):
    return {c["name"]: c["id"] for c in book.listing()}


# ---- merging and browsing ------------------------------------------------------------------------------------------------------

def test_merging_moves_the_messages_hides_the_category_and_keeps_the_name_code_knows_it_by(store, book):
    _, (a, b) = said(store, ["how hot is it", "hello"])
    book.assign(a, "Weather", "code")
    book.assign(b, "Chat", "code")
    ids = listing_ids(book)
    assert book.merge(ids["Weather"], ids["Chat"]) == "Chat"
    assert "Weather" not in listing_ids(book) and book.tags([a, b]) == {a: "Chat", b: "Chat"}
    _, (c,) = said(store, ["rain again"])
    assert book.assign(c, "Weather", "code") == "Chat"  # code still says Weather; it lands where Weather went
    assert {x["name"]: x["count"] for x in book.listing()}["Chat"] == 3


def test_a_merged_category_can_itself_be_merged_and_the_old_name_leads_to_the_last(store, book):
    ids = listing_ids(book)
    book.merge(ids["Weather"], ids["Learning"])
    book.merge(ids["Learning"], ids["About me"])
    _, (m,) = said(store, ["anything"])
    assert book.assign(m, "Weather", "code") == "About me" and book.assign(m, "learning", "person") == "About me"


def test_merging_what_cannot_be_merged_is_refused_and_changes_nothing(book):
    ids = listing_ids(book)
    for source, target in ((ids["Weather"], ids["Weather"]), (9999, ids["Chat"]), (ids["Chat"], 9999), (9999, 8888)):
        with pytest.raises(cat.CategoryError):
            book.merge(source, target)
    assert [c["name"] for c in book.listing()] == NAMES


def test_a_category_that_was_merged_away_cannot_be_merged_again_or_renamed(book):
    ids = listing_ids(book)
    book.merge(ids["Weather"], ids["Chat"])
    with pytest.raises(cat.CategoryError):
        book.merge(ids["Weather"], ids["Learning"])
    with pytest.raises(cat.CategoryError):
        book.rename(ids["Weather"], "Sky")


def test_a_category_name_that_was_merged_away_can_be_made_again_only_if_it_was_the_persons_own(store, book):
    new = book.add("School")
    ids = listing_ids(book)
    book.merge(new, ids["Chat"])
    assert book.add("School")  # it was theirs: the name is free again
    with pytest.raises(cat.CategoryError):
        book.add("Weather") if book.merge(ids["Weather"], ids["Chat"]) else None  # a starter one is still known by its first name


def test_browsing_a_category_shows_its_newest_messages_from_every_chat_with_the_reply(store, book):
    first, (a,) = said(store, ["what's the weather in Pune"])
    store.add_message(first, "assistant", "Sunny, 31 degrees.")
    second, (b,) = said(store, ["weather in Berlin?"])
    store.add_message(second, "assistant", "Cold.")
    c = store.add_message(second, "user", "and tomorrow?")
    for message in (a, b, c):
        book.assign(message, "Weather", "code")
    weather = listing_ids(book)["Weather"]
    found = book.messages_in(weather, 10)
    assert [m["text"] for m in found] == ["and tomorrow?", "weather in Berlin?", "what's the weather in Pune"]  # newest first
    assert [m["reply"] for m in found] == ["", "Cold.", "Sunny, 31 degrees."] and found[0]["thread_id"] == second and found[0]["source"] == "code"
    assert len(book.messages_in(weather, 2)) == 2


def test_the_messages_in_no_category_are_found_oldest_first_and_a_limit_is_honoured(store, book):
    _, ids = said(store, ["one", "two", "three"])
    book.assign(ids[1], "Chat", "code")
    assert book.unsorted() == [(ids[0], "one"), (ids[2], "three")] and book.unsorted(1) == [(ids[0], "one")]


def test_a_small_value_can_be_remembered_and_changed(book):
    assert book.state("x") is None
    book.set_state("x", "1")
    book.set_state("x", "2")
    assert book.state("x") == "2"


# ---- what the person is shown as a suggestion --------------------------------------------------------------------------------------

def test_the_messages_looked_at_for_a_new_category_are_the_ones_no_rule_could_place_and_not_the_persons_own(store, book):
    _, ids = said(store, ["a", "b", "c", "d", "e", "A"])
    for message, source in zip(ids, ("model", "continued", "code", "person", "model", "model")):
        book.assign(message, "Chat", source)
    store.add_message(1, "user", "never sorted")
    assert [text for _, text in book.recent_for_ideas(10)] == ["b", "e", "A"]  # code-placed, the person's own and unsorted are left out; "A" repeats "a", and the newer copy is kept
    assert [text for _, text in book.recent_for_ideas(2)] == ["e", "A"]  # the newest ones, oldest of those first


def test_a_suggestion_is_kept_until_answered_and_yes_moves_only_the_messages_left_ticked(store, book):
    _, ids = said(store, ["exam friday", "assignment due", "the lecture moved", "thanks", "quiz me on chemistry"])
    suggestion = book.add_suggestion("school work", ids)
    (waiting,) = book.open_suggestions()
    assert waiting["id"] == suggestion and waiting["name"] == "School work" and [m["text"] for m in waiting["messages"]] == ["exam friday", "assignment due", "the lecture moved", "thanks", "quiz me on chemistry"]
    with pytest.raises(cat.CategoryError):
        book.answer_suggestion(suggestion, True, [])  # yes with nothing ticked is not an answer
    assert book.answer_suggestion(suggestion, True, [ids[0], ids[1], ids[2], ids[4]]) == "School work"
    assert book.tags(ids) == {ids[0]: "School work", ids[1]: "School work", ids[2]: "School work", ids[4]: "School work"}  # "thanks" stayed where it was
    assert book.open_suggestions() == [] and "School work" in listing_ids(book)
    with pytest.raises(cat.CategoryError):
        book.answer_suggestion(suggestion, True)  # answered once


def test_yes_to_a_name_that_is_already_a_category_moves_the_messages_into_it(store, book):
    _, ids = said(store, ["a", "b", "c", "d", "e"])
    suggestion = book.add_suggestion("Learning", ids)
    assert book.answer_suggestion(suggestion, True) == "Learning" and set(book.tags(ids).values()) == {"Learning"}


def test_no_is_remembered_so_the_same_name_is_not_suggested_again(store, book):
    _, ids = said(store, ["a", "b", "c", "d", "e"])
    book.answer_suggestion(book.add_suggestion("School", ids), False)
    assert book.tags(ids) == {} and "school" in book.known_suggestion_names() and "School" not in listing_ids(book)


# ---- asking the model for a name, and checking every yes -----------------------------------------------------------------------

@pytest.mark.parametrize("answer, expected", [
    ("School", "School"), ("  \"study plan\" ", "Study plan"), ("Topic: Cooking", "Cooking"), ("Name: **Health**.", "Health"),
    ("NONE", None), ("none.", None), ("Other", None), ("", None), (None, None), ("one two three four", None), ("x" * 40, None), ("Weather", None),
])
def test_the_name_the_model_gives_is_used_only_if_it_is_a_usable_new_name(answer, expected):
    assert ideas.read_name(answer, {"weather", "learning"}) == expected


def test_the_two_questions_say_what_they_ask_and_offer_no_way_to_call_it_other():
    asked = ideas.name_prompt(["I have an exam", "hello"], cat.STARTER)
    assert all(name in asked for name in NAMES) and "1. I have an exam" in asked and "2. hello" in asked and "NONE" in asked
    about = ideas.about_prompt("School", "I have an exam")
    assert "\"School\"" in about and "I have an exam" in about and "yes or no" in about
    assert ideas.says_yes("Yes") and ideas.says_yes(" yes.") and not ideas.says_yes("No") and not ideas.says_yes("Maybe, yes") and not ideas.says_yes(None)


def candidates(store, book, texts, source="model"):
    _, ids = said(store, texts)
    for message in ids:
        book.assign(message, "Chat", source)
    return ids


def topic_texts():
    return [f"school thing {n}" for n in range(8)] + [f"something else {n}" for n in range(8)]


def test_a_suggestion_needs_a_name_from_the_model_and_enough_yeses_from_code(store, book):
    ids = candidates(store, book, topic_texts())
    answers = ["School"] + ["yes" if n < 6 else "no" for n in range(16)]
    model = Said(*answers)
    assert ideas.suggest(book, model, "m")
    (made,) = book.open_suggestions()
    assert made["name"] == "School" and made["message_ids"] == ids[:6] and len(model.asked) == 17  # one name question, then one yes or no for each message
    assert ideas.suggest(book, Said(), "m") is None  # one suggestion waits at a time, and the model is not even asked


@pytest.mark.parametrize("name_answer, yeses", [("NONE", 0), ("Weather", 8), ("Learning", 8), ("School", 4), ("School", 0), ("", 8)])
def test_nothing_is_suggested_when_the_name_is_none_or_taken_or_too_few_messages_are_about_it(store, book, name_answer, yeses):
    candidates(store, book, topic_texts())
    model = Said(name_answer, *(["yes"] * yeses + ["no"] * 16))
    assert ideas.suggest(book, model, "m") is None and book.open_suggestions() == []


def test_a_name_the_person_refused_is_not_suggested_again(store, book):
    ids = candidates(store, book, topic_texts())
    book.answer_suggestion(book.add_suggestion("School", ids[:5]), False)
    assert ideas.suggest(book, Said("School", *(["yes"] * 16)), "m") is None


def test_too_few_messages_are_not_enough_to_look_at_and_the_model_is_not_asked(store, book):
    candidates(store, book, [f"message {n}" for n in range(ideas.MIN_MESSAGES - 1)])
    model = Said("School")
    assert ideas.suggest(book, model, "m") is None and model.asked == []


def test_messages_a_rule_placed_are_not_what_a_new_category_is_looked_for_in(store, book):
    candidates(store, book, topic_texts(), source="code")
    assert ideas.suggest(book, Said("School"), "m") is None


# ---- sorting the earlier chats ---------------------------------------------------------------------------------------------------

def test_only_the_messages_in_no_category_are_sorted_oldest_first_one_at_a_time(store, book):
    _, ids = said(store, ["hey", "what's the weather in Pune", "how does a transformer neural network work", "hello"])
    book.assign(ids[0], "About me", "person")  # already placed (by the person): left alone
    seen = []
    lock = threading.Lock()

    def progress(done, total):
        seen.append((done, total, lock.locked()))

    assert ideas.sort_earlier(book, Said("Learning"), "m", lock, progress) == 3
    assert book.tags(ids) == {ids[0]: "About me", ids[1]: "Weather", ids[2]: "Learning", ids[3]: "Chat"}
    assert [(d, t) for d, t, _ in seen] == [(1, 3), (2, 3), (3, 3)] and not any(held for _, _, held in seen)  # the lock is let go between messages


def test_sorting_the_earlier_chats_can_be_stopped_and_picked_up_again(store, book):
    _, ids = said(store, ["hey", "hello", "hi", "yo"])
    count = []
    assert ideas.sort_earlier(book, Said(), "m", threading.Lock(), progress=lambda d, t: count.append(d), stop=lambda: len(count) >= 2) == 2
    assert len(book.unsorted()) == 2
    assert ideas.sort_earlier(book, Said(), "m", threading.Lock()) == 2 and book.unsorted() == []


def test_an_earlier_message_with_no_usable_answer_takes_the_subject_of_the_one_before_it(store, book):
    thread, ids = said(store, ["what's the weather in Pune", "a muddled thing"])
    ideas.sort_earlier(book, Said("???", "???"), "m", threading.Lock())
    assert book.tags(ids) == {ids[0]: "Weather", ids[1]: "Weather"}


# ---- the routes ---------------------------------------------------------------------------------------------------------------------

def build(tmp_path, *replies, **changes):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False, categories=True, **changes)
    agent = diya.Agent(config, client=FakeClient(list(replies)))
    return TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL), agent


def post(client, **body):
    return client.post("/api/categories", json=body)


def wait_for_the_job(client, seconds=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        job = client.get("/api/categories").json()["job"]
        if not job["running"]:
            return job
        time.sleep(0.05)
    raise AssertionError("the job did not finish")


def test_the_list_says_what_is_waiting_and_what_is_running(tmp_path):
    client, agent = build(tmp_path)
    body = client.get("/api/categories").json()
    assert body["suggestions"] == [] and body["unsorted"] == 0 and body["job"] == {"kind": None, "running": False, "done": 0, "total": 0, "note": ""}


def test_merge_and_browse_work_through_the_page(tmp_path):
    client, agent = build(tmp_path)
    _, ids = said(agent.store, ["weather in Berlin?", "hello"])
    book = cat.Book(agent.store)
    book.assign(ids[0], "Weather", "code")
    book.assign(ids[1], "Chat", "code")
    by_name = {c["name"]: c["id"] for c in client.get("/api/categories").json()["categories"]}
    browsed = post(client, action="browse", category_id=by_name["Weather"]).json()["messages"]
    assert [m["text"] for m in browsed] == ["weather in Berlin?"] and browsed[0]["source"] == "code"
    merged = post(client, action="merge", category_id=by_name["Weather"], into_id=by_name["Chat"]).json()
    assert "Weather" not in [c["name"] for c in merged["categories"]] and {c["name"]: c["count"] for c in merged["categories"]}["Chat"] == 2
    assert post(client, action="merge", category_id=by_name["Weather"], into_id=by_name["Chat"]).status_code == 400  # it is gone


def test_a_suggestion_is_found_shown_and_answered_through_the_page(tmp_path):
    answers = ["School"] + ["yes" if n < 6 else "no" for n in range(16)]
    client, agent = build(tmp_path, *[text_reply(a) for a in answers])
    candidates(agent.store, cat.Book(agent.store), topic_texts())
    assert post(client, action="suggest").status_code == 200
    job = wait_for_the_job(client)
    assert job["kind"] == "suggest" and "suggestion" in job["note"]
    (suggestion,) = client.get("/api/categories").json()["suggestions"]
    assert suggestion["name"] == "School" and len(suggestion["messages"]) == 6
    keep = [m["id"] for m in suggestion["messages"][:4]]
    done = post(client, action="answer_suggestion", suggestion_id=suggestion["id"], accept=True, message_ids=keep).json()
    assert done["suggestions"] == [] and {c["name"]: c["count"] for c in done["categories"]}["School"] == 4


def test_a_no_to_a_suggestion_goes_through_the_page_and_is_remembered(tmp_path):
    client, agent = build(tmp_path)
    book = cat.Book(agent.store)
    ids = candidates(agent.store, book, topic_texts())
    sid = book.add_suggestion("School", ids[:5])
    assert post(client, action="answer_suggestion", suggestion_id=sid, accept=False).json()["suggestions"] == []
    assert post(client, action="answer_suggestion", suggestion_id=sid, accept=True).status_code == 400  # answered already
    assert "school" in book.known_suggestion_names()


def test_the_earlier_chats_are_sorted_in_the_background_and_the_page_can_see_how_far(tmp_path):
    client, agent = build(tmp_path, text_reply("Learning"))
    said(agent.store, ["hey", "how does a transformer neural network work"])
    assert client.get("/api/categories").json()["unsorted"] == 2
    assert post(client, action="sort_earlier").status_code == 200
    job = wait_for_the_job(client)
    assert job["kind"] == "sort_earlier" and (job["done"], job["total"]) == (2, 2) and "Sorted 2" in job["note"]
    assert client.get("/api/categories").json()["unsorted"] == 0
    assert post(client, action="sort_earlier").status_code == 200 and "already in a category" in wait_for_the_job(client)["note"]


def test_one_job_runs_at_a_time(tmp_path):
    client, agent = build(tmp_path)
    said(agent.store, ["hey"])
    with diya_categories_lock():
        assert post(client, action="sort_earlier").status_code == 200  # it starts, then waits for the lock
        time.sleep(0.2)
        assert client.get("/api/categories").json()["job"]["running"] is True
        refused = post(client, action="suggest")
        assert refused.status_code == 400 and "already running" in refused.json()["detail"]
    wait_for_the_job(client)


class diya_categories_lock:
    def __enter__(self):
        cat.SORT_LOCK.acquire()

    def __exit__(self, *exc):
        cat.SORT_LOCK.release()


def test_the_jobs_refuse_when_sorting_is_turned_off(tmp_path):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "off.db"), profile_path=str(tmp_path / "p.txt"), require_token=False, categories=False)
    client = TestClient(diya_web.create_app(config, diya.Agent(config, client=FakeClient([])), FakeTranscriber()), base_url=LOCAL)
    for action in ("suggest", "sort_earlier"):
        response = post(client, action=action)
        assert response.status_code == 400 and "DIYA_CATEGORIES=0" in response.json()["detail"]


@pytest.mark.parametrize("body", [
    {"action": "merge", "category_id": 1}, {"action": "merge", "category_id": 1, "into_id": 1}, {"action": "browse"}, {"action": "answer_suggestion", "suggestion_id": 1},
    {"action": "answer_suggestion", "suggestion_id": 99, "accept": True},
])
def test_what_cannot_be_done_with_a_category_is_refused_in_plain_words(tmp_path, body):
    client, _ = build(tmp_path)
    response = post(client, **body)
    assert response.status_code == 400 and isinstance(response.json()["detail"], str)


def test_an_earlier_chats_messages_carry_their_ids_and_categories(tmp_path):
    client, agent = build(tmp_path)
    main_thread, _ = said(agent.store, ["the one chat"])
    earlier = agent.store.create_thread()
    old = agent.store.add_message(earlier, "user", "how hot is it")
    agent.store.add_message(earlier, "assistant", "Hot.")
    agent.store.add_message(main_thread, "user", "newest, so the one chat is this")
    cat.Book(agent.store).assign(old, "Weather", "code")
    body = client.get(f"/api/history/{earlier}").json()
    assert body["is_main"] is False and body["messages"][0] == {"id": old, "role": "user", "content": "how hot is it", "category": "Weather"}
    assert "category" not in body["messages"][1] and body["messages"][1]["role"] == "assistant"


# ---- Dreaming -------------------------------------------------------------------------------------------------------------------------

def dreamer(tmp_path, *replies, **changes):
    config = dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "d.db"), profile_path=str(tmp_path / "p.txt"), **dict({"categories": True}, **changes))
    client = Said(*replies)
    return dreaming.Dreamer(config, client=client, store=Store(config.db_path)), client


def test_dreaming_sorts_what_is_left_a_batch_a_cycle_and_looks_for_a_suggestion_once_a_day(tmp_path):
    from datetime import datetime

    d, model = dreamer(tmp_path, "NONE")
    _, ids = said(d.store, ["hey", "hello", "hi", "yo", "morning"])
    d.look_for_categories(now=datetime(2026, 10, 16, 3, 0), max_sorted=3)
    assert len(cat.Book(d.store).unsorted()) == 2 and len(model.asked) == 0  # a greeting needs no model; a batch of three; and under the minimum, nothing to look at
    d.look_for_categories(now=datetime(2026, 10, 16, 15, 0))
    assert cat.Book(d.store).unsorted() == [] and cat.Book(d.store).state("category_ideas_on") == "2026-10-16"


def test_dreaming_looks_once_per_day_not_once_per_cycle(tmp_path):
    from datetime import datetime

    d, model = dreamer(tmp_path, "NONE", "NONE")
    candidates(d.store, cat.Book(d.store), topic_texts())
    d.look_for_categories(now=datetime(2026, 10, 16, 3, 0))
    asked = len(model.asked)
    assert asked >= 1
    d.look_for_categories(now=datetime(2026, 10, 16, 15, 0))
    assert len(model.asked) == asked  # the same day: not again
    d.look_for_categories(now=datetime(2026, 10, 17, 3, 0))
    assert len(model.asked) > asked


def test_dreaming_does_nothing_with_categories_off_and_never_raises(tmp_path):
    d, model = dreamer(tmp_path, categories=False)
    said(d.store, ["hey"])
    d.look_for_categories()
    assert cat.Book(d.store).unsorted() == [(1, "hey")] and model.asked == []
    d, _ = dreamer(tmp_path)
    d.store = None  # something is badly wrong
    d.look_for_categories()  # written to the log, not raised
