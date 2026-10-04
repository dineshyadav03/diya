"""The routes behind the Actions page (diya_actions_api.py, docs/ACTIONS_DESIGN.md D8, unit A3).

What this proves: an approval is an authenticated request for exactly the version the page showed, and it runs the
action once; a rejection or a note about an unknown outcome never runs anything; each refusal is the right HTTP
error with the reason in `detail`; everything a person is shown comes back made safe to show; and listing the actions
closes what has expired and what was cut off, so the page never shows them as live. Every kind here is a fake.
"""
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import diya
import diya_actions
import diya_config
import diya_connectors
import diya_web
from diya_actions import ActionFailed, ActionKind, Actions
from fakes import FakeClient, task_kind

HOST = "https://localhost"
T0 = datetime(2026, 10, 4, 10, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def build(monkeypatch, *kinds):
    monkeypatch.setenv("DIYA_REQUIRE_TOKEN", "0")  # about the routes; the token is test_token.py's
    config = diya_config.load_config()
    agent = diya.Agent(config, client=FakeClient(), action_kinds=kinds)
    clock = Clock()
    agent.actions = Actions(agent.store, config, kinds, clock)
    app = diya_web.create_app(config, agent, transcriber=object())
    return types.SimpleNamespace(client=TestClient(app, base_url=HOST), agent=agent, config=config, clock=clock, app=app)


@pytest.fixture
def world(monkeypatch):
    executed = []
    built = build(monkeypatch, task_kind(executed=executed))
    built.executed = executed
    return built


def propose(world, title="buy milk", **extra):
    return world.agent.actions.propose("add_task", {"title": title}, **extra)


def approve_body(action):
    return {"args_hash": action["args_hash"]}


def cut_off(world, title="buy milk"):
    """An action whose run was cut off: it ends up `unknown`."""
    action = propose(world, title)
    world.agent.actions.approve(action["id"], action["args_hash"], "cli")
    real = world.agent.actions.kinds
    world.agent.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)
    with pytest.raises(KeyboardInterrupt):
        world.agent.actions.run(action["id"])
    world.agent.actions.kinds = real
    world.agent.actions.reconcile(older_than=timedelta(0))
    return action


# ---- GET /api/actions ----------------------------------------------------------------------------

def test_with_nothing_proposed_the_list_is_empty_and_says_what_kinds_there_are(world):
    body = world.client.get("/api/actions").json()
    assert body["pending"] == [] and body["history"] == []
    assert body["counts"] == {status: 0 for status in diya_actions.STATUSES}
    assert body["kinds"] == [{"name": "add_task", "label": "Add a task", "connector": None, "offered": True, "available": True}]


def test_with_no_kinds_at_all_the_page_is_told_there_is_nothing_to_propose(monkeypatch):
    plain = build(monkeypatch)
    body = plain.client.get("/api/actions").json()
    assert body["kinds"] == [] and body["pending"] == []


def test_a_kind_whose_connector_is_not_connected_is_listed_as_not_available(monkeypatch):
    built = build(monkeypatch, task_kind(connector="todoist"), task_kind(name="quiet", tool=False))
    kinds = built.client.get("/api/actions").json()["kinds"]
    assert [(k["name"], k["connector"], k["offered"], k["available"]) for k in kinds] == [
        ("add_task", "todoist", True, False), ("quiet", None, False, True)]
    diya_connectors.store_token(built.config, "todoist", "a-token")
    assert built.client.get("/api/actions").json()["kinds"][0]["available"] is True


def test_a_pending_action_comes_back_with_everything_the_page_shows(world):
    action = propose(world, "buy milk", thread_id=4, message_id=9, taint_sources=["web_search", "search_notion"])
    (shown,) = world.client.get("/api/actions").json()["pending"]
    assert shown == {
        "id": action["id"], "kind": "add_task", "label": "Add a task",
        "summary": "Add the task 'buy milk'", "status": "pending",
        "fields": [{"name": "title", "value": "buy milk"}],
        "args_hash": action["args_hash"], "tainted": True, "taint_sources": ["web_search", "search_notion"],
        "thread_id": 4, "message_id": 9,
        "created_at": "2026-10-04T10:00:00Z", "expires_at": "2026-10-05T10:00:00Z",
        "decided_at": None, "executed_at": None, "result": None,
    }


def test_arguments_are_sent_as_named_fields_in_name_order_each_as_plain_text(monkeypatch):
    kind = ActionKind("rich", "Rich", None, lambda a: None, lambda a: "Do it", lambda c, a: "ok", None)
    built = build(monkeypatch, kind)
    built.agent.actions.propose("rich", {"zeta": "z", "alpha": None, "flag": True, "off": False, "count": 3, "ratio": 1.5})
    (shown,) = built.client.get("/api/actions").json()["pending"]
    assert shown["fields"] == [
        {"name": "alpha", "value": None}, {"name": "count", "value": "3"}, {"name": "flag", "value": "yes"},
        {"name": "off", "value": "no"}, {"name": "ratio", "value": "1.5"}, {"name": "zeta", "value": "z"}]


def test_the_label_falls_back_to_the_kind_s_name_when_the_kind_is_gone(world):
    propose(world)
    world.agent.actions.kinds = ()
    (shown,) = world.client.get("/api/actions").json()["pending"]
    assert shown["label"] == "add_task" and shown["kind"] == "add_task"


def test_whatever_is_shown_is_made_safe_to_show(world):
    action = world.agent.actions.propose("add_task", {"title": "buy milk"}, taint_sources=["web_search"])
    world.agent.actions.approve(action["id"], action["args_hash"], "ui")
    world.executed.clear()
    world.agent.actions.kinds = (task_kind(reply="done\x1b[31m red \u202e backwards"),)
    world.agent.actions.run(action["id"])
    conn = world.agent.store.connect()
    conn.execute("UPDATE actions SET summary = ?, taint_sources = ? WHERE id = ?",
                 ("Add\x1b[2J the task\u202e", '["web\\u001b_search"]', action["id"]))
    conn.commit()
    conn.close()
    (shown,) = world.client.get("/api/actions").json()["history"]
    assert shown["result"] == "done\\u001b[31m red \\u202e backwards"
    assert shown["summary"] == "Add\\u001b[2J the task\\u202e"
    assert shown["taint_sources"] == ["web\\u001b_search"]
    detail = world.client.get(f"/api/actions/{action['id']}").json()
    assert "\x1b" not in str(detail) and "\u202e" not in str(detail)


def test_history_is_what_is_not_pending_newest_first(world):
    first, second, third, still = (propose(world, t) for t in ("a", "b", "c", "d"))
    world.agent.actions.reject(first["id"], "ui")
    world.agent.actions.approve(second["id"], second["args_hash"], "ui")
    world.agent.actions.run(second["id"])
    world.agent.actions.reject(third["id"], "ui")
    body = world.client.get("/api/actions").json()
    assert [a["id"] for a in body["pending"]] == [still["id"]]
    assert [(a["id"], a["status"]) for a in body["history"]] == [
        (third["id"], "rejected"), (second["id"], "succeeded"), (first["id"], "rejected")]
    assert body["counts"]["pending"] == 1 and body["counts"]["rejected"] == 2 and body["counts"]["succeeded"] == 1


def test_history_is_cut_at_the_limit_and_keeps_the_newest(world):
    import diya_actions_api

    ids = []
    for n in range(diya_actions_api.HISTORY_LIMIT + 5):
        action = propose(world, f"task {n}")
        world.agent.actions.reject(action["id"], "ui")
        ids.append(action["id"])
    history = world.client.get("/api/actions").json()["history"]
    assert [a["id"] for a in history] == ids[::-1][: diya_actions_api.HISTORY_LIMIT]
    assert len(history) == 50 and diya_actions_api.HISTORY_LIMIT == 50


def test_listing_closes_what_has_expired_so_it_is_never_shown_as_waiting(world):
    stale = propose(world, "stale")
    world.clock.now += timedelta(hours=12)
    fresh = propose(world, "fresh")  # (proposing closes what has expired by then, so nothing is due yet)
    world.clock.now += timedelta(hours=13)  # now `stale` is over a day old and `fresh` is not; only listing can close it
    body = world.client.get("/api/actions").json()
    assert [a["id"] for a in body["pending"]] == [fresh["id"]]
    assert [(a["id"], a["status"]) for a in body["history"]] == [(stale["id"], "expired")]


def test_listing_moves_a_run_cut_off_a_while_ago_to_unknown_but_leaves_a_fresh_one_alone(world):
    action = propose(world)
    world.agent.actions.approve(action["id"], action["args_hash"], "cli")
    world.agent.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)
    with pytest.raises(KeyboardInterrupt):
        world.agent.actions.run(action["id"])
    world.clock.now += timedelta(seconds=60)
    assert world.client.get("/api/actions").json()["history"][0]["status"] == "executing"
    world.clock.now += timedelta(seconds=61)
    assert world.client.get("/api/actions").json()["history"][0]["status"] == "unknown"


# ---- GET /api/actions/{id} -------------------------------------------------------------------------

def test_one_action_comes_back_with_its_history_and_the_message_it_answered(world):
    thread = world.agent.store.create_thread()
    message = world.agent.store.add_message(thread, "user", "please add buy milk")
    action = propose(world, "buy milk", thread_id=thread, message_id=message)
    world.agent.actions.approve(action["id"], action["args_hash"], "ui")
    body = world.client.get(f"/api/actions/{action['id']}").json()
    assert body["action"]["id"] == action["id"] and body["action"]["status"] == "approved"
    assert body["source"] == "please add buy milk"
    assert [(e["event"], e["actor"]) for e in body["events"]] == [("proposed", "model"), ("approved", "owner")]
    assert body["events"][0]["detail"] is None and body["events"][1]["detail"] == '{"via": "ui"}'
    assert body["events"][0]["at"] == "2026-10-04T10:00:00Z"


def test_the_source_message_is_cut_short(world):
    thread = world.agent.store.create_thread()
    message = world.agent.store.add_message(thread, "user", "x" * 500)
    action = propose(world, message_id=message)
    source = world.client.get(f"/api/actions/{action['id']}").json()["source"]
    assert source == "x" * 300 + "..."
    exact = world.agent.store.add_message(thread, "user", "y" * 300)  # exactly the limit is not cut
    assert world.client.get(f"/api/actions/{propose(world, 'other', message_id=exact)['id']}").json()["source"] == "y" * 300


def test_an_action_with_no_message_or_a_message_that_is_gone_has_no_source(world):
    assert world.client.get(f"/api/actions/{propose(world, 'a')['id']}").json()["source"] is None
    assert world.client.get(f"/api/actions/{propose(world, 'b', message_id=9999)['id']}").json()["source"] is None


def test_a_long_event_detail_is_cut_short(world):
    action = propose(world)
    conn = world.agent.store.connect()
    conn.execute("UPDATE action_events SET detail = ? WHERE action_id = ?", ("x" * 500, action["id"]))
    conn.commit()
    conn.close()
    detail = world.client.get(f"/api/actions/{action['id']}").json()["events"][0]["detail"]
    assert len(detail) == 203 and detail.endswith("...")


@pytest.mark.parametrize("action_id", [99, 0, -1, 2**63, 2**70])
def test_an_action_that_does_not_exist_is_a_404_on_every_route(world, action_id):
    assert world.client.get(f"/api/actions/{action_id}").status_code == 404
    assert world.client.post(f"/api/actions/{action_id}/approve", json={"args_hash": "x"}).status_code == 404
    assert world.client.post(f"/api/actions/{action_id}/reject").status_code == 404
    assert world.client.post(f"/api/actions/{action_id}/resolve", json={"happened": True}).status_code == 404


def test_the_largest_possible_id_is_looked_up_and_one_above_it_is_not_a_database_error(world):
    assert world.client.get(f"/api/actions/{2**63 - 1}").status_code == 404
    assert world.client.get("/api/actions/abc").status_code == 422


def test_the_404_names_the_action(world):
    assert world.client.get("/api/actions/99").json()["detail"] == "there is no action 99"
    assert world.client.get("/api/actions/0").json()["detail"] == "there is no action 0"


# ---- POST approve -----------------------------------------------------------------------------------

def test_approving_what_was_shown_runs_it_once_and_says_how_it_went(world):
    action = propose(world)
    answer = world.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert answer.status_code == 200
    done = answer.json()["action"]
    assert done["status"] == "succeeded" and done["result"] == "created task 1" and done["decided_at"] == "2026-10-04T10:00:00Z"
    assert world.executed == [{"title": "buy milk"}]
    events = world.client.get(f"/api/actions/{action['id']}").json()["events"]
    assert [(e["event"], e["actor"]) for e in events] == [
        ("proposed", "model"), ("approved", "owner"), ("executing", "system"), ("succeeded", "system")]
    assert events[1]["detail"] == '{"via": "ui"}'  # decided on the page


def test_approving_something_other_than_what_was_shown_is_a_409_and_nothing_runs(world):
    action = propose(world)
    answer = world.client.post(f"/api/actions/{action['id']}/approve", json={"args_hash": "0" * 64})
    assert answer.status_code == 409 and "not what was shown" in answer.json()["detail"]
    assert world.executed == [] and world.agent.actions.get(action["id"])["status"] == "pending"


def test_approving_without_saying_what_was_shown_is_refused_before_anything_is_looked_at(world):
    action = propose(world)
    assert world.client.post(f"/api/actions/{action['id']}/approve").status_code == 422
    assert world.client.post(f"/api/actions/{action['id']}/approve", json={}).status_code == 422
    assert world.client.post(f"/api/actions/{action['id']}/approve", json={"args_hash": 5}).status_code == 422
    assert world.executed == [] and world.agent.actions.get(action["id"])["status"] == "pending"


def test_an_action_can_be_approved_once(world):
    action = propose(world)
    assert world.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action)).status_code == 200
    again = world.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert again.status_code == 409 and "only a pending action can be approved" in again.json()["detail"]
    assert len(world.executed) == 1


def test_a_turned_down_action_cannot_then_be_approved(world):
    action = propose(world)
    world.client.post(f"/api/actions/{action['id']}/reject")
    assert world.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action)).status_code == 409
    assert world.executed == []


def test_an_expired_action_cannot_be_approved(world):
    action = propose(world)
    world.clock.now += timedelta(hours=24)
    answer = world.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert answer.status_code == 409 and "is expired" in answer.json()["detail"]
    assert world.executed == []


def test_an_action_whose_effect_fails_is_still_a_200_with_the_failure_in_it(monkeypatch):
    executed = []
    built = build(monkeypatch, task_kind(executed=executed, raises=ActionFailed("Todoist said no")))
    action = built.agent.actions.propose("add_task", {"title": "x"})
    answer = built.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert answer.status_code == 200
    assert answer.json()["action"]["status"] == "failed" and answer.json()["action"]["result"] == "Todoist said no"
    assert executed == [{"title": "x"}]


def test_an_action_whose_effect_cannot_tell_whether_it_happened_is_a_200_that_says_unknown(monkeypatch):
    executed = []
    built = build(monkeypatch, task_kind(executed=executed, raises=diya_actions.ActionUncertain("Sent, but no answer came back")))
    action = built.agent.actions.propose("add_task", {"title": "x"})
    answer = built.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert answer.status_code == 200
    assert answer.json()["action"]["status"] == "unknown" and answer.json()["action"]["result"] == "Sent, but no answer came back"
    listing = built.client.get("/api/actions").json()
    assert [a["status"] for a in listing["history"]] == ["unknown"] and listing["counts"]["unknown"] == 1
    again = built.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert again.status_code == 409 and executed == [{"title": "x"}]  # never tried a second time
    resolved = built.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": True, "note": "it is there"})
    assert resolved.status_code == 200 and resolved.json()["action"]["status"] == "succeeded"
    assert executed == [{"title": "x"}]


def test_an_action_whose_connector_was_disconnected_after_it_was_proposed_is_not_run(monkeypatch):
    executed = []
    built = build(monkeypatch, task_kind(connector="todoist", executed=executed))
    diya_connectors.store_token(built.config, "todoist", "a-token")
    action = built.agent.actions.propose("add_task", {"title": "x"})
    diya_connectors.disconnect(built.config, "todoist")
    answer = built.client.post(f"/api/actions/{action['id']}/approve", json=approve_body(action))
    assert answer.status_code == 200
    assert answer.json()["action"]["status"] == "failed" and answer.json()["action"]["result"] == "Not run: todoist is no longer connected"
    assert executed == []


# ---- POST reject --------------------------------------------------------------------------------------

def test_turning_an_action_down_means_it_is_never_run(world):
    action = propose(world)
    answer = world.client.post(f"/api/actions/{action['id']}/reject")
    assert answer.status_code == 200
    done = answer.json()["action"]
    assert done["status"] == "rejected" and done["decided_at"] == "2026-10-04T10:00:00Z"
    assert world.executed == []
    events = world.client.get(f"/api/actions/{action['id']}").json()["events"]
    assert [(e["event"], e["actor"], e["detail"]) for e in events] == [("proposed", "model", None), ("rejected", "owner", '{"via": "ui"}')]


def test_only_a_pending_action_can_be_turned_down(world):
    action = propose(world)
    world.client.post(f"/api/actions/{action['id']}/reject")
    again = world.client.post(f"/api/actions/{action['id']}/reject")
    assert again.status_code == 409 and "only a pending action can be rejected" in again.json()["detail"]
    approved = propose(world, "other")
    world.client.post(f"/api/actions/{approved['id']}/approve", json=approve_body(approved))
    assert world.client.post(f"/api/actions/{approved['id']}/reject").status_code == 409


# ---- POST resolve ---------------------------------------------------------------------------------------

def test_the_owner_records_that_a_cut_off_action_did_happen(world):
    action = cut_off(world)
    answer = world.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": True, "note": "  it is in my  list "})
    assert answer.status_code == 200
    done = answer.json()["action"]
    assert done["status"] == "succeeded" and done["result"] == "Recorded by the owner: it happened. it is in my list"
    events = world.client.get(f"/api/actions/{action['id']}").json()["events"]
    assert events[-1]["event"] == "resolved_succeeded" and events[-1]["actor"] == "owner"
    assert events[-1]["detail"] == '{"via": "ui", "note": "it is in my list"}'
    assert world.executed == []  # finding out never runs it


def test_the_owner_records_that_a_cut_off_action_did_not_happen(world):
    action = cut_off(world)
    done = world.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": False}).json()["action"]
    assert done["status"] == "failed" and done["result"] == "Recorded by the owner: it did not happen."


@pytest.mark.parametrize("note", [None, "", "   "])
def test_a_blank_note_is_no_note(world, note):
    action = cut_off(world)
    done = world.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": True, "note": note}).json()["action"]
    assert done["result"] == "Recorded by the owner: it happened."
    assert world.client.get(f"/api/actions/{action['id']}").json()["events"][-1]["detail"] == '{"via": "ui"}'


@pytest.mark.parametrize("payload", [None, {}, {"happened": "yes"}, {"happened": 1}, {"happened": None}, {"note": "x"}])
def test_resolving_needs_a_real_yes_or_no(world, payload):
    action = cut_off(world)
    answer = world.client.post(f"/api/actions/{action['id']}/resolve", **({} if payload is None else {"json": payload}))
    assert answer.status_code == 422
    assert world.agent.actions.get(action["id"])["status"] == "unknown"


def test_a_note_that_may_not_be_stored_is_a_422_and_changes_nothing(world):
    action = cut_off(world)
    for note in ("x" * (diya_actions.MAX_NOTE_CHARS + 1), "bad\x1b[31m note"):
        answer = world.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": True, "note": note})
        assert answer.status_code == 422
    assert world.agent.actions.get(action["id"])["status"] == "unknown"
    world.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": True, "note": "x" * diya_actions.MAX_NOTE_CHARS})


def test_only_an_unknown_action_can_be_resolved(world):
    action = propose(world)
    answer = world.client.post(f"/api/actions/{action['id']}/resolve", json={"happened": True})
    assert answer.status_code == 409 and "only an unknown action can be resolved" in answer.json()["detail"]
    resolved = cut_off(world, "other")
    assert world.client.post(f"/api/actions/{resolved['id']}/resolve", json={"happened": True}).status_code == 200
    assert world.client.post(f"/api/actions/{resolved['id']}/resolve", json={"happened": True}).status_code == 409


# ---- the routes themselves --------------------------------------------------------------------------------

def test_the_actions_routes_are_get_and_post_only(world):
    action = propose(world)
    for method in ("PUT", "PATCH", "DELETE"):
        for path in ("/api/actions", f"/api/actions/{action['id']}", f"/api/actions/{action['id']}/approve",
                     f"/api/actions/{action['id']}/reject", f"/api/actions/{action['id']}/resolve"):
            assert world.client.request(method, path).status_code == 405, (method, path)
    assert world.client.get(f"/api/actions/{action['id']}/approve").status_code == 405
    assert world.client.post("/api/actions").status_code == 405
    assert world.agent.actions.get(action["id"])["status"] == "pending"


def test_every_actions_route_the_app_has_is_listed_here(world):
    paths = {route.path for route in world.app.routes if route.path.startswith("/api/actions")}
    assert paths == {"/api/actions", "/api/actions/{action_id}", "/api/actions/{action_id}/approve",
                     "/api/actions/{action_id}/reject", "/api/actions/{action_id}/resolve"}
