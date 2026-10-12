"""Finding and naming past chats, and notes that are found the day they are written: diya_db.search_threads and set_thread_title, diya_threads_api.py, and Agent.notes refreshing itself.

What this proves: a search finds a chat by any message in it (the person's or Diya's) or by its name, ignores case, treats % and _ as themselves, finds nothing for under two characters, lists the
newest first and shows a short piece around what was found; a name replaces the first-message preview in the list, an empty one takes it back, a long one is cut, an unknown chat is a 404; the routes
make what they send safe to show and answer only the methods they should; and the notes index is built again when a note is added, edited or removed (and not when nothing changed), a
sub-folder is not a note, an empty folder is said, and an index that fails to rebuild leaves the old one working.
"""
import dataclasses
import os

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_db
import diya_web
from fakes import FakeClient

LOCAL = "https://localhost"


@pytest.fixture
def store(tmp_path):
    return diya_db.Store(str(tmp_path / "t.db"))


def chat(store, *messages):
    thread = store.create_thread()
    for role, text in messages:
        store.add_message(thread, role, text)
    return thread


# ---- the store ----------------------------------------------------------------------------------------------------------------

def test_a_search_finds_a_chat_by_any_message_in_it_ignoring_case(store):
    a = chat(store, ("user", "my flight is on Friday"), ("assistant", "Got it, your flight is Friday."))
    b = chat(store, ("user", "what is the weather"), ("assistant", "It is 28 C in Pune."))
    assert [t["id"] for t in store.search_threads("PUNE")] == [b] and [t["id"] for t in store.search_threads("flight")] == [a]
    assert store.search_threads("nothing like this") == []


def test_newest_first_and_the_match_is_a_short_piece_around_the_words(store):
    old = chat(store, ("user", "x " * 100 + "dentist appointment tuesday " + "y " * 100))
    new = chat(store, ("user", "dentist again"))
    found = store.search_threads("dentist")
    assert [t["id"] for t in found] == [new, old]
    assert found[1]["match"].startswith("…") and found[1]["match"].endswith("…") and "dentist appointment tuesday" in found[1]["match"] and len(found[1]["match"]) < 160


def test_under_two_characters_finds_nothing_and_percent_and_underscore_are_themselves(store):
    chat(store, ("user", "100% sure"), ("user", "a_b"), ("user", "axb"))
    assert store.search_threads("a") == [] and store.search_threads("") == [] and store.search_threads(None) == []
    assert len(store.search_threads("100%")) == 1 and len(store.search_threads("a_b")) == 1 and store.search_threads("%%") == []


def test_only_what_the_person_and_diya_said_is_searched(store):
    thread = chat(store, ("user", "hello"))
    store.add_message(thread, "tool", "SECRETWORD from a tool")
    assert store.search_threads("SECRETWORD") == []


def test_a_name_replaces_the_first_message_in_the_list_and_an_empty_one_takes_it_back(store):
    thread = chat(store, ("user", "my flight is on Friday"))
    assert store.set_thread_title(thread, "  Trip   to  Goa ") is True
    assert store.list_threads_with_preview()[0]["preview"] == "Trip to Goa" and [t["id"] for t in store.search_threads("goa")] == [thread]
    assert store.set_thread_title(thread, "") is True and store.list_threads_with_preview()[0]["preview"] == "my flight is on Friday"
    assert store.set_thread_title(999, "x") is False


def test_a_long_name_is_cut(store):
    thread = chat(store, ("user", "hi"))
    store.set_thread_title(thread, "n" * 500)
    assert len(store.list_threads_with_preview()[0]["preview"]) == diya_db.MAX_THREAD_TITLE


# ---- the routes ---------------------------------------------------------------------------------------------------------------

@pytest.fixture
def parts(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)
    agent = diya.Agent(config, client=FakeClient())
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL), agent


def test_the_search_route_returns_the_chats_with_what_was_found(parts):
    client, agent = parts
    thread = chat(agent.store, ("user", "book the dentist"), ("assistant", "Done."))
    body = client.get("/api/threads/search", params={"q": "dentist"}).json()
    assert [t["id"] for t in body["threads"]] == [thread] and set(body["threads"][0]) == {"id", "created_at", "preview", "match"} and "dentist" in body["threads"][0]["match"]
    assert client.get("/api/threads/search", params={"q": "d"}).json() == {"threads": []} and client.get("/api/threads/search").json() == {"threads": []}


def test_what_the_search_route_sends_is_made_safe(parts):
    client, agent = parts
    chat(agent.store, ("assistant", f"found {chr(27)}[31mred{chr(0x202E)} text"))
    text = client.get("/api/threads/search", params={"q": "found"}).json()["threads"][0]["match"]
    assert chr(27) not in text and chr(0x202E) not in text


def test_rename_names_the_chat_and_refuses_what_it_cannot(parts):
    client, agent = parts
    thread = chat(agent.store, ("user", "hello there"))
    assert client.post(f"/api/threads/{thread}/rename", json={"title": " Trip  to Goa "}).json() == {"id": thread, "title": "Trip to Goa"}
    assert client.get("/api/threads").json()["threads"][0]["preview"] == "Trip to Goa"
    assert client.post(f"/api/threads/{thread}/rename", json={"title": ""}).json() == {"id": thread, "title": None}
    assert client.post("/api/threads/99/rename", json={"title": "x"}).status_code == 404 and client.post(f"/api/threads/{2**63}/rename", json={"title": "x"}).status_code == 404
    assert client.post(f"/api/threads/{thread}/rename", json={"title": "x" * 400}).status_code == 422 and client.post(f"/api/threads/{thread}/rename", json={}).status_code == 422
    assert client.get(f"/api/threads/{thread}/rename").status_code == 405 and client.post("/api/threads/search").status_code == 405


# ---- notes found the day they are written -----------------------------------------------------------------------------------

@pytest.fixture
def notes(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    (folder / "guitar.txt").write_text("Buy new guitar strings before the weekend.")
    return folder


def notes_agent(tmp_path, notes, **client_kwargs):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "n.db"), profile_path=str(tmp_path / "p.txt"), notes_dir=str(notes))
    client = FakeClient(**client_kwargs)
    return diya.Agent(config, client=client), client



def test_a_note_added_after_the_index_was_built_is_found_without_a_restart(tmp_path, notes):
    agent, _ = notes_agent(tmp_path, notes)
    assert agent.search_notes("guitar") == "Buy new guitar strings before the weekend."
    (notes / "dentist.txt").write_text("Dentist appointment on Tuesday at 3pm.")
    assert agent.search_notes("dentist") == "Dentist appointment on Tuesday at 3pm."


def test_an_edited_or_removed_note_is_noticed_too(tmp_path, notes):
    agent, _ = notes_agent(tmp_path, notes)
    agent.notes
    (notes / "guitar.txt").write_text("Buy a new guitar strap, not strings, before the weekend!")
    assert agent.search_notes("guitar") == "Buy a new guitar strap, not strings, before the weekend!"
    (notes / "guitar.txt").unlink()
    assert agent.search_notes("guitar") == "There are no notes to search."


def test_nothing_is_embedded_again_while_the_folder_is_unchanged(tmp_path, notes):
    agent, client = notes_agent(tmp_path, notes)
    agent.search_notes("guitar")
    agent.search_notes("guitar strings")
    assert [c["input"] for c in client.embed_calls].count("Buy new guitar strings before the weekend.") == 1


def test_a_sub_folder_is_not_a_note(tmp_path, notes):
    (notes / "old").mkdir()
    agent, _ = notes_agent(tmp_path, notes)
    assert agent.search_notes("guitar") == "Buy new guitar strings before the weekend." and agent.notes.count() == 1


def test_an_index_that_cannot_be_rebuilt_leaves_the_old_one_working(tmp_path, notes, monkeypatch):
    agent, _ = notes_agent(tmp_path, notes)
    first = agent.notes
    (notes / "garden.txt").write_text("Water the garden every morning.")
    monkeypatch.setattr(agent, "_build_notes", lambda signature=None: (_ for _ in ()).throw(ConnectionError("down")))
    with pytest.raises(ConnectionError):
        agent.notes
    assert agent._notes is first and agent._notes_signature != agent._notes_files()  # still out of date, so the next try rebuilds
    monkeypatch.undo()
    assert agent.notes is not first and agent.notes.count() == 2
