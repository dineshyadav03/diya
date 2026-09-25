"""Reviewing facts over HTTP (docs/STAGE2_DESIGN.md, D6 and unit 6): diya_memory_api.py.

What this proves: the routes carry diya_memory's rules and no others (every action applies or is refused with
the right status and a reason, and a refusal changes nothing); everything a person is shown that came from the
database reaches the browser with control, invisible and direction-changing characters as visible escapes;
only GET and POST exist; nothing is reachable without the access token (and a refused write writes nothing);
an oversized body is turned away before anything is stored; and what a person accepts here is what the model
is told on the very next message.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
import json

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_memory
import diya_web
from diya_db import Store
from diya_memory import Memory
from dreaming import Dreamer
from fakes import FakeClient, text_reply

LOCAL = "https://localhost"
ESC, BIDI, ZWSP, LINE_SEP = chr(27), chr(0x202E), chr(0x200B), chr(0x2028)
STAGED_AT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "api.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"),
        require_token=False,
    )


@pytest.fixture
def app_parts(config):
    model = FakeClient([text_reply("ok")] * 10)
    agent = diya.Agent(config, client=model)
    client = TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL)
    return client, agent, model


@pytest.fixture
def client(app_parts):
    return app_parts[0]


@pytest.fixture
def memory(app_parts):
    return Memory(app_parts[1].store)


def stage(config, agent, *rows_and_replies):
    """Real messages and one real Dreaming cycle each; returns nothing, the queue file is what matters."""
    store = agent.store
    threads = store.list_threads()
    thread = threads[0][0] if threads else store.create_thread()
    for message, reply in rows_and_replies:
        store.add_message(thread, "user", message)
        Dreamer(config, client=FakeClient([text_reply(reply)]), store=store).dream_cycle()


def add_candidate(memory, text, first=1, last=1, position=0, **extra):
    return memory.add_candidate(text, batch_first=first, batch_last=last, position=position, model="qwen2.5:3b",
                                extracted_at=STAGED_AT, raw="- " + text, **extra)


def no_hidden(value):
    """True if no string anywhere inside `value` has a control, invisible or direction-changing character."""
    if isinstance(value, str):
        return all(not diya_memory._unwanted(ch) for ch in value)
    if isinstance(value, dict):
        return all(no_hidden(k) and no_hidden(v) for k, v in value.items())
    if isinstance(value, list):
        return all(no_hidden(v) for v in value)
    return True


# --- listing ------------------------------------------------------------------------------------------

def test_an_empty_memory_lists_nothing_and_says_how_big_it_may_grow(client):
    body = client.get("/api/memory").json()
    assert body == {"summary": {"counts": {"candidate": 0, "accepted": 0, "rejected": 0, "retired": 0},
                                "used": 0, "limit": 2000, "max_fact_chars": 200}, "facts": []}


def test_the_list_carries_status_flags_in_words_and_the_size_used(client, memory, app_parts):
    store = app_parts[1].store
    store.add_message(store.create_thread(), "user", "I adopted a cat named Pixel")
    add_candidate(memory, "has a cat named Pixel")
    add_candidate(memory, "is a doctor", position=1)
    memory.run_checks("cli")
    memory.decide(1, "accept", "cli")

    body = client.get("/api/memory").json()

    assert body["summary"] == {"counts": {"candidate": 1, "accepted": 1, "rejected": 0, "retired": 0},
                               "used": len("- has a cat named Pixel"), "limit": 2000, "max_fact_chars": 200}
    first, second = body["facts"]
    assert (first["id"], first["text"], first["status"], first["source"]) == (1, "has a cat named Pixel", "accepted", "dreaming")
    assert first["flags"] == [{"code": "source_message:1", "label": "source message 1"}]
    assert second["flags"] == [{"code": "ungrounded", "label": "ungrounded"}]


def test_the_list_sends_only_what_a_list_needs(client, memory):
    add_candidate(memory, "likes tea")
    (fact,) = client.get("/api/memory").json()["facts"]
    assert set(fact) == {"id", "text", "status", "source", "flags", "created_at"}  # not the staged line, the model or the history


# --- one fact ---------------------------------------------------------------------------------------

def test_a_fact_in_detail_shows_where_it_came_from_and_what_has_happened_to_it(client, memory, app_parts):
    store = app_parts[1].store
    thread = store.create_thread()
    store.add_message(thread, "user", "I adopted a cat named Pixel")
    store.add_message(thread, "assistant", "Congratulations on the kitten!")
    store.add_message(thread, "user", "and I like tea")
    add_candidate(memory, "has a cat named Pixel", first=1, last=3)
    memory.run_checks("cli")

    body = client.get("/api/memory/1").json()

    assert body["fact"]["text"] == "has a cat named Pixel"
    assert body["staged"] == "- has a cat named Pixel"
    assert (body["model"], body["extracted_at"], body["range"]) == ("qwen2.5:3b", STAGED_AT, [1, 3])
    assert body["sources"] == [{"id": 1, "thread_id": thread, "text": "I adopted a cat named Pixel"},
                               {"id": 3, "thread_id": thread, "text": "and I like tea"}]  # only what the user said
    assert body["flag_details"] == ["source_message: the message it best matches is 1"]
    assert [(e["event"], e["actor"]) for e in body["events"]] == [("ingested", "system"), ("flagged", "cli")]
    assert body["events"][1]["detail"] == '{"from": [], "to": ["source_message:1"]}'


def test_a_typed_fact_has_no_staged_line_no_range_and_no_sources(client, memory):
    memory.add_manual("likes tea", "cli")
    body = client.get("/api/memory/1").json()
    assert (body["staged"], body["model"], body["extracted_at"], body["range"], body["sources"]) == (None, None, None, None, [])


def test_a_long_source_message_is_cut(client, memory, app_parts):
    store = app_parts[1].store
    store.add_message(store.create_thread(), "user", "word " * 200)
    add_candidate(memory, "says a word")
    (source,) = client.get("/api/memory/1").json()["sources"]
    assert source["text"].endswith("...") and len(source["text"]) <= diya_memory.printable("x").__len__() + 303


def test_a_flag_that_points_at_another_fact_names_it(client, memory, app_parts):
    store = app_parts[1].store
    store.add_message(store.create_thread(), "user", "I like green tea")
    memory.add_manual("likes green tea", "cli")
    add_candidate(memory, "Likes Green Tea", position=1)
    memory.run_checks("cli")
    details = client.get("/api/memory/2").json()["flag_details"]
    assert "duplicate: says the same as fact 1 (accepted): likes green tea" in details


@pytest.mark.parametrize("fact_id", ["0", "-1", "99", str(2**63), "99999999999999999999999"])
def test_a_fact_that_is_not_there_is_a_404_and_never_an_error(client, fact_id):
    response = client.get(f"/api/memory/{fact_id}")
    assert response.status_code == 404
    assert "there is no fact" in response.json()["detail"]


@pytest.mark.parametrize("fact_id", ["abc", "1.5", "one"])
def test_an_id_that_is_not_a_whole_number_is_refused_before_anything_runs(client, fact_id):
    assert client.get(f"/api/memory/{fact_id}").status_code == 422


# --- deciding -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("start, action, becomes", [
    ("candidate", "accept", "accepted"), ("candidate", "reject", "rejected"), ("rejected", "reopen", "candidate"),
    ("accepted", "retire", "retired"), ("retired", "restore", "accepted"),
])
def test_every_action_applies_and_says_what_the_memory_now_holds(client, memory, start, action, becomes):
    fact_id = add_candidate(memory, "likes tea")
    for step in {"candidate": [], "rejected": ["reject"], "accepted": ["accept"], "retired": ["accept", "retire"]}[start]:
        memory.decide(fact_id, step, "cli")

    response = client.post(f"/api/memory/{fact_id}/{action}")

    assert response.status_code == 200
    body = response.json()
    assert body["fact"]["status"] == becomes and body["fact"]["id"] == fact_id
    assert body["summary"]["counts"][becomes] == 1
    *_, (event, actor, _at, _detail) = [e for e in memory.events(fact_id) if e[0] != "flagged"]
    assert actor == "api"
    assert memory.verify_integrity() == []


@pytest.mark.parametrize("action, fact_status, status_code, phrase", [
    ("accept", "accepted", 409, "only a candidate fact can be accepted"),
    ("retire", "candidate", 409, "only an accepted fact can be retired"),
    ("restore", "accepted", 409, "only a retired fact can be restored"),
    ("reopen", "candidate", 409, "only a rejected fact can be reopened"),
    ("reject", "rejected", 409, "only a candidate fact can be rejected"),
])
def test_a_change_that_does_not_apply_is_a_409_with_the_reason_and_changes_nothing(client, memory, action, fact_status, status_code, phrase):
    fact_id = add_candidate(memory, "likes tea")
    for step in {"candidate": [], "accepted": ["accept"], "rejected": ["reject"]}[fact_status]:
        memory.decide(fact_id, step, "cli")
    before = (memory.facts(), memory.events(fact_id))
    response = client.post(f"/api/memory/{fact_id}/{action}")
    assert response.status_code == status_code and phrase in response.json()["detail"]
    assert (memory.facts(), memory.events(fact_id)) == before


def test_a_repeat_and_a_full_profile_are_a_409_with_the_reason(client, memory, monkeypatch):
    memory.add_manual("Likes Tea", "cli")
    twin = add_candidate(memory, "likes tea")
    other = add_candidate(memory, "prefers strong coffee in the morning", position=1)
    response = client.post(f"/api/memory/{twin}/accept")
    assert response.status_code == 409 and "already accepted" in response.json()["detail"]
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", 20)
    response = client.post(f"/api/memory/{other}/accept")
    assert response.status_code == 409 and "memory is full" in response.json()["detail"]
    assert memory.get(other)["status"] == "candidate"


def test_a_fact_too_long_to_accept_is_a_422_that_says_how_to_fix_it(client, memory):
    fact_id = add_candidate(memory, ("long " * 60).strip())
    memory.run_checks("cli")  # (ingesting from the page does this; the candidate here was put in directly)
    response = client.post(f"/api/memory/{fact_id}/accept")
    assert response.status_code == 422 and "edit it shorter first" in response.json()["detail"]
    assert "too_long" in [f["code"] for f in client.get("/api/memory").json()["facts"][0]["flags"]]
    fixed = client.post(f"/api/memory/{fact_id}/edit", json={"text": "likes long words"})
    assert fixed.status_code == 200 and "too_long" not in [f["code"] for f in fixed.json()["fact"]["flags"]]  # the flag follows the edit
    assert client.post(f"/api/memory/{fact_id}/accept").status_code == 200


@pytest.mark.parametrize("path, status_code", [
    ("/api/memory/99/accept", 404), ("/api/memory/0/accept", 404), (f"/api/memory/{2**63}/accept", 404),
    ("/api/memory/1/dance", 404), ("/api/memory/1/ACCEPT", 404), ("/api/memory/1/add", 404),
    ("/api/memory/abc/accept", 422),
])
def test_an_unknown_fact_or_action_is_refused(client, memory, path, status_code):
    add_candidate(memory, "likes tea")
    assert client.post(path).status_code == status_code
    assert memory.get(1)["status"] == "candidate"


def test_editing_cleans_the_text_and_keeps_the_old_wording_in_the_history(client, memory):
    fact_id = add_candidate(memory, "likes tea")
    response = client.post(f"/api/memory/{fact_id}/edit", json={"text": "  - likes   green tea " + ESC})
    assert response.status_code == 200 and response.json()["fact"]["text"] == "likes green tea"
    detail = client.get(f"/api/memory/{fact_id}").json()
    assert [e["event"] for e in detail["events"]][-1] in ("edited", "flagged")
    assert any(e["event"] == "edited" and e["detail"] == '{"from": "likes tea"}' for e in detail["events"])


@pytest.mark.parametrize("payload, status_code", [
    ({"text": ""}, 422), ({"text": "-"}, 422), ({"text": "NONE"}, 422), ({"text": ESC}, 422),
    (None, 422), ({}, 422), ({"text": 5}, 422), ({"wrong": "field"}, 422),
])
def test_a_bad_edit_is_a_422_and_changes_nothing(client, memory, payload, status_code):
    fact_id = add_candidate(memory, "likes tea")
    response = client.post(f"/api/memory/{fact_id}/edit", json=payload) if payload is not None else client.post(f"/api/memory/{fact_id}/edit")
    assert response.status_code == status_code
    assert memory.get(fact_id)["text"] == "likes tea"


@pytest.mark.parametrize("status", ["accepted", "rejected", "retired"])
def test_only_a_candidate_can_be_edited_over_http_too(client, memory, status):
    fact_id = add_candidate(memory, "likes tea")
    for step in {"accepted": ["accept"], "rejected": ["reject"], "retired": ["accept", "retire"]}[status]:
        memory.decide(fact_id, step, "cli")
    response = client.post(f"/api/memory/{fact_id}/edit", json={"text": "reworded"})
    assert response.status_code == 409 and "only a candidate can be edited" in response.json()["detail"]


def test_the_checks_are_refreshed_after_every_change(client, memory, app_parts):
    store = app_parts[1].store
    store.add_message(store.create_thread(), "user", "I like green tea")
    first = add_candidate(memory, "likes green tea")
    second = add_candidate(memory, "Likes Green Tea", position=1)
    memory.run_checks("cli")
    assert [f["code"] for f in client.get("/api/memory").json()["facts"][1]["flags"]] == [f"source_message:1", f"duplicate:{first}"]
    client.post(f"/api/memory/{first}/reject")  # the fact it repeated is gone: it is no longer a repeat
    assert [f["code"] for f in client.get("/api/memory").json()["facts"][1]["flags"]] == ["source_message:1", f"previously_rejected:{first}"]
    assert second


# --- typing a fact ----------------------------------------------------------------------------------

def test_a_typed_fact_is_cleaned_and_goes_in_accepted_with_a_201(client, memory):
    response = client.post("/api/memory/add", json={"text": "  * works   in the evenings "})
    assert response.status_code == 201
    body = response.json()
    assert (body["fact"]["text"], body["fact"]["status"], body["fact"]["source"]) == ("works in the evenings", "accepted", "manual")
    assert body["summary"]["counts"]["accepted"] == 1
    assert memory.accepted_texts() == ["works in the evenings"]
    assert memory.events(1)[0][:2] == ("added", "api")


@pytest.mark.parametrize("payload, status_code, phrase", [
    ({"text": "Works In The Evenings"}, 409, "already accepted"),
    ({"text": "-"}, 422, "nothing left of that text"),
    ({"text": "x" * 201}, 422, "the limit is 200"),
    ({"text": ""}, 422, "nothing left"),
    ({}, 422, None), ({"text": None}, 422, None), ({"text": ["a"]}, 422, None),
])
def test_a_typed_fact_that_may_not_go_in_is_refused_and_nothing_is_stored(client, memory, payload, status_code, phrase):
    memory.add_manual("works in the evenings", "cli")
    response = client.post("/api/memory/add", json=payload)
    assert response.status_code == status_code
    if phrase:
        assert phrase in response.json()["detail"]
    assert memory.accepted_texts() == ["works in the evenings"]


def test_a_body_that_is_not_json_is_refused(client, memory):
    assert client.post("/api/memory/add", content=b"likes tea", headers={"Content-Type": "application/json"}).status_code == 422
    assert client.post("/api/memory/add").status_code == 422
    assert memory.facts() == []


def test_markup_in_a_fact_is_data_not_something_the_response_interprets(client, memory):
    response = client.post("/api/memory/add", json={"text": "<script>alert(1)</script>"})
    assert response.status_code == 201
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["fact"]["text"] == "<script>alert(1)</script>"
    assert [f["code"] for f in response.json()["fact"]["flags"]] == []  # a manual fact is not a candidate: no checks run on it


# --- ingesting the staged queue ------------------------------------------------------------------------

def test_ingesting_from_the_page_copies_the_queue_in_and_checks_it(client, config, app_parts):
    stage(config, app_parts[1], ("I adopted a cat named Pixel", "- has a cat named Pixel\n- is a doctor"))
    response = client.post("/api/memory/ingest")
    assert response.status_code == 200
    body = response.json()
    assert body["report"] == {"records": 1, "bad_records": 0, "new": 2, "already": 0, "skipped": 0}
    assert (body["checked"], body["changed"]) == (2, 2)
    assert body["summary"]["counts"]["candidate"] == 2
    facts = client.get("/api/memory").json()["facts"]
    assert [f["text"] for f in facts] == ["has a cat named Pixel", "is a doctor"]
    assert [f["code"] for f in facts[1]["flags"]] == ["ungrounded"]


def test_ingesting_twice_adds_nothing(client, config, app_parts):
    stage(config, app_parts[1], ("I like tea", "- likes tea"))
    client.post("/api/memory/ingest")
    body = client.post("/api/memory/ingest").json()
    assert body["report"]["new"] == 0 and body["report"]["already"] == 1 and body["summary"]["counts"]["candidate"] == 1


def test_no_queue_is_not_an_error(client):
    body = client.post("/api/memory/ingest").json()
    assert body["report"] == {"records": 0, "bad_records": 0, "new": 0, "already": 0, "skipped": 0}


def test_an_unreadable_queue_is_a_500_that_says_so_and_ingests_nothing(client, config, memory):
    import os

    os.mkdir(config.dream_pending_path)
    response = client.post("/api/memory/ingest")
    assert response.status_code == 500 and "could not read the staged queue" in response.json()["detail"]
    assert memory.facts() == []


# --- what a person is shown is safe to show --------------------------------------------------------------

def test_nothing_from_the_database_reaches_the_browser_with_a_hidden_character(client, memory, app_parts, config):
    store = app_parts[1].store
    store.add_message(store.create_thread(), "user", "I like tea " + ESC + "[31m red " + BIDI + "text\nsecond line")
    add_candidate(memory, "likes tea")
    conn = store.connect()
    conn.execute("UPDATE facts SET raw = ?, model = ?, flags = ? WHERE id = 1",
                 ("- likes tea " + ESC + "[2J" + ZWSP + LINE_SEP + "x", "m" + ESC, json.dumps(["ungrounded", "similar:" + ESC + "2", ESC + "odd"])))
    conn.execute("UPDATE fact_events SET detail = ?, actor = ? WHERE id = 1", ("d" + BIDI, "cli"))
    conn.commit()
    conn.close()

    listed = client.get("/api/memory").json()
    detail = client.get("/api/memory/1").json()

    assert no_hidden(listed) and no_hidden(detail)
    backslash = chr(92)
    assert backslash + "u001b" in json.dumps(detail, ensure_ascii=False)  # the escape is visible, as text
    assert detail["sources"][0]["text"].startswith("I like tea " + backslash + "u001b[31m red " + backslash + "u202etext second line")


def test_a_fact_whose_stored_text_was_tampered_with_is_still_shown_escaped(client, memory, app_parts):
    add_candidate(memory, "likes tea")
    conn = app_parts[1].store.connect()
    conn.execute("UPDATE facts SET text = ? WHERE id = 1", ("likes" + ESC + " tea",))
    conn.commit()
    conn.close()
    assert no_hidden(client.get("/api/memory").json())


# --- only GET and POST -------------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("path", ["/api/memory", "/api/memory/1", "/api/memory/1/accept", "/api/memory/add", "/api/memory/ingest"])
def test_no_other_method_exists(client, memory, method, path):
    add_candidate(memory, "likes tea")
    assert client.request(method, path).status_code == 405
    assert memory.get(1)["status"] == "candidate"


def test_a_get_cannot_change_anything(client, memory):
    add_candidate(memory, "likes tea")
    for path in ("/api/memory/1/accept", "/api/memory/add", "/api/memory/ingest"):
        assert client.get(path).status_code in (404, 405, 422)
    assert memory.get(1)["status"] == "candidate"


def test_the_cors_rules_allow_the_page_to_post_and_nothing_stronger(client):
    origin = {"Origin": "https://localhost:3000"}
    ok = client.options("/api/memory/1/accept", headers={**origin, "Access-Control-Request-Method": "POST"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "https://localhost:3000"
    for method in ("DELETE", "PUT", "PATCH"):
        refused = client.options("/api/memory/1", headers={**origin, "Access-Control-Request-Method": method})
        assert refused.status_code == 400, method


# --- the token, the size limit, and being free to build ----------------------------------------------------

def test_without_the_token_nothing_is_read_and_nothing_is_written(tmp_path, config):
    config = dataclasses.replace(config, require_token=True, token_path=str(tmp_path / "token.hash"))
    token = diya_web.ensure_token(config.token_path)
    agent = diya.Agent(config, client=FakeClient())
    client = TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL)
    memory = Memory(agent.store)
    fact_id = add_candidate(memory, "likes tea")

    for method, path, kwargs in [("GET", "/api/memory", {}), ("GET", f"/api/memory/{fact_id}", {}), ("POST", "/api/memory/ingest", {}),
                                 ("POST", "/api/memory/add", {"json": {"text": "x"}}), ("POST", f"/api/memory/{fact_id}/accept", {}),
                                 ("POST", f"/api/memory/{fact_id}/edit", {"json": {"text": "y"}})]:
        assert client.request(method, path, **kwargs).status_code == 401, path
        assert client.request(method, path, headers={"Authorization": "Bearer " + "0" * 43}, **kwargs).status_code == 401, path
    assert (memory.get(fact_id)["status"], memory.get(fact_id)["text"], len(memory.facts())) == ("candidate", "likes tea", 1)
    assert client.post(f"/api/memory/{fact_id}/accept", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_an_oversized_body_is_turned_away_before_anything_is_stored(client, memory, config):
    limit = config.max_body_bytes
    response = client.post("/api/memory/add", content=b'{"text": "' + b"a" * (limit + 10) + b'"}', headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert memory.facts() == []


def test_building_the_app_touches_no_store():
    """create_app must stay free: registering the memory routes cannot need an agent that has a store."""
    import types

    agent = types.SimpleNamespace()  # no .store at all
    config = dataclasses.replace(diya_config.load_config(), require_token=False)
    app = diya_web.create_app(config, agent, object())
    assert "/api/memory" in {route.path for route in app.routes}


# --- end to end: what is accepted here is what the model is told next --------------------------------------

def test_a_fact_accepted_in_the_page_is_told_to_the_model_on_the_very_next_message(client, memory, app_parts):
    _, _, model = app_parts
    fact_id = add_candidate(memory, "plays chess on Sundays")
    client.post("/api/chat", json={"message": "hi"})
    assert model.chat_calls[0]["messages"][0]["role"] == "user"  # a candidate is not told

    client.post(f"/api/memory/{fact_id}/accept")
    client.post("/api/chat", json={"message": "hello again"})
    assert model.chat_calls[1]["messages"][0] == {"role": "system", "content": "What you know about the user so far:\n- plays chess on Sundays"}

    client.post(f"/api/memory/{fact_id}/retire")
    client.post("/api/chat", json={"message": "and again"})
    assert all(m["role"] != "system" for m in model.chat_calls[2]["messages"])
