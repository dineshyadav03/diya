"""Google Tasks, read properly and changed when you approve each change (diya_google_tasks.py; DIYA-097, DIYA-098; docs/GOOGLE_CHANGES.md), added 2026-10-26.

No test here reaches the real Google: a stateful stand-in Tasks service answers, keeps every request, and applies the changes it is sent. What this proves: the list is read across pages with each task's state, due
day and id, a list other than the default can be read by name (and only read), finished tasks are shown when asked, and a long list says it was cut; a change is proposed only when the message names Google Tasks and
asks for that change; the task is found NOW by its name among the open ones and none, or several of the same name, refuses the proposal (nothing is guessed), whatever id the model supplied is replaced by
Google's; each change is done only after approval, only to the default list, only if the task is still as it was proposed (an etag that moved, a task finished or gone since means nothing is done), and is read back
afterwards; deleting says in its own card that it cannot be undone; a model-invented new name or notes are dropped; and none of these changes can be switched to "straight away".
"""
import dataclasses
import json
import types
from datetime import timedelta

import pytest

import diya
import diya_actions
import diya_autoapprove
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_client as client
import diya_google_tasks as gt
from diya_actions import ActionFailed
from fakes import FakeClient, text_reply, tool_reply

BASE = gt.BASE


def resp(status=200, body=None):
    return types.SimpleNamespace(status_code=status, headers={}, json=lambda: body if body is not None else {})


class Tasks:
    """A stand-in Google Tasks: lists, one default list of tasks with etags, and the five requests Diya makes."""

    def __init__(self, titles=("Buy milk", "Call the dentist", "Renew bus pass"), page=100):
        self.tasks = {f"id{n:05d}": {"id": f"id{n:05d}", "title": t, "status": "needsAction", "etag": f'"e{n}"', "updated": "x"} for n, t in enumerate(titles, 1)}
        self.lists = [{"id": "listAAAAA", "title": "My Tasks"}, {"id": "listBBBBB", "title": "Exams"}]
        self.other = {"listBBBBB": [{"id": "ex00001", "title": "Physics revision", "status": "needsAction"}]}
        self.requests, self.page = [], page

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        params, body = kwargs.get("params") or {}, kwargs.get("json")
        self.requests.append((method, url, dict(params), body))
        tail = url[len(BASE):]
        if tail == "/users/@me/lists":
            return resp(200, {"items": self.lists})
        if tail.startswith("/lists/") and tail.endswith("/tasks") and method == "GET":
            list_id = tail.split("/")[2]
            if list_id != "@default":
                return resp(200, {"items": self.other.get(list_id, [])})
            show_done = params.get("showCompleted") == "true"
            rows = [t for t in self.tasks.values() if show_done or t["status"] != "completed"]
            start = int(params.get("pageToken", "0") or 0)
            chunk = rows[start:start + self.page]
            more = start + self.page < len(rows)
            return resp(200, {"items": chunk, **({"nextPageToken": str(start + self.page)} if more else {})})
        parts = tail.split("/")  # '', 'lists', '@default', 'tasks', id[, 'move']
        task = self.tasks.get(parts[4]) if len(parts) > 4 else None
        if method == "GET":
            return resp(200, task) if task else resp(404, {"error": {"message": "not found"}})
        if task is None:
            return resp(404, {"error": {"message": "not found"}})
        if method == "PATCH":
            task.update(body)
            task["etag"] = task["etag"][:-1] + 'x"'
            return resp(200, task)
        if method == "DELETE":
            del self.tasks[parts[4]]
            return resp(204)
        if method == "POST" and parts[-1] == "move":
            parent = params.get("parent")
            task.pop("parent", None)
            if parent:
                task["parent"] = parent
            return resp(200, task)
        return resp(400)


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False)
    diya_connectors.store_token(config, "google_tasks", "refresh")
    return config


@pytest.fixture
def google(monkeypatch):
    service = Tasks()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok" if name == "google_tasks" else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


# ---- reading ---------------------------------------------------------------------------------------------------------------------------------------

def test_the_open_tasks_are_listed_with_state_due_day_and_id(config, google):
    google.tasks["id00001"]["due"] = "2026-10-28T00:00:00.000Z"
    said = gt.read_tasks(config)
    assert said.startswith("Google Tasks, your default list:") and "- Buy milk (open, due 2026-10-28) [id: id00001]" in said and "- Call the dentist (open) [id: id00002]" in said


def test_finished_tasks_are_shown_only_when_asked(config, google):
    google.tasks["id00002"]["status"] = "completed"
    assert "Call the dentist" not in gt.read_tasks(config)
    shown = gt.read_tasks(config, show_done=True)
    assert "- Call the dentist (done) [id: id00002]" in shown and google.requests[-1][2]["showCompleted"] == "true"


def test_a_long_list_is_followed_across_pages_and_says_when_it_stopped(config, monkeypatch):
    service = Tasks(titles=[f"Task {n}" for n in range(1, 61)], page=10)
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok")
    monkeypatch.setattr(client.httpx, "get", service)
    said = gt.read_tasks(config)
    assert "Task 30" in said and "Task 31" not in said and "Only the first 30 are shown" in said  # three pages of ten were read (the limit), and it says there are more


def test_another_list_is_read_by_name_and_an_unknown_one_lists_the_names(config, google):
    assert "Physics revision" in gt.read_tasks(config, "exams")
    said = gt.read_tasks(config, "holidays")
    assert "could not tell which Google Tasks list" in said and "Exams" in said and "My Tasks" in said


def test_not_connected_and_a_refusal_are_said_in_words(config, google, monkeypatch):
    monkeypatch.setattr(client.httpx, "get", lambda *a, **k: resp(403, {"error": {"errors": [{"reason": "accessNotConfigured"}], "message": "Tasks API has not been used"}}))
    assert "not switched on in your Google project" in gt.read_tasks(config)
    diya_connectors.disconnect(config, "google_tasks")
    assert gt.read_tool_specs(config)[0][2]() == "Google Tasks is not connected."


def test_the_read_tool_is_offered_with_its_two_optional_arguments(config):
    (name, spec, function), = gt.read_tool_specs(config)
    assert name == "google_tasks" and spec["function"]["name"] == "list_google_tasks" and set(spec["function"]["parameters"]["properties"]) == {"list_name", "show_done"} and spec["function"]["parameters"]["required"] == []


# ---- finding the one task -----------------------------------------------------------------------------------------------------------------------

def test_the_task_is_found_by_its_name_whatever_capitals_and_punctuation(config, google):
    assert gt.find_open_task(config, "buy milk!")["id"] == "id00001" and gt.find_open_task(config, "  CALL the dentist ")["id"] == "id00002"


def test_none_and_several_refuse_the_change_and_say_why(config, google):
    with pytest.raises(diya_actions.InvalidArgs, match="there is no open task called 'Water plants'"):
        gt.find_open_task(config, "Water plants")
    google.tasks["id00009"] = {"id": "id00009", "title": "buy milk", "status": "needsAction", "etag": '"e9"'}
    with pytest.raises(diya_actions.InvalidArgs, match="2 open tasks .* are called 'Buy milk'"):
        gt.find_open_task(config, "Buy milk")
    with pytest.raises(diya_actions.InvalidArgs, match="say which task"):
        gt.find_open_task(config, "  ")


def test_the_reference_comes_from_google_never_from_what_the_model_gave(config, google):
    resolved = gt._resolve(config, {"title": "buy milk", "task_id": "evilidxxx", "etag": "fake"})
    assert resolved == {"title": "Buy milk", "task_id": "id00001", "etag": '"e1"'}  # the name as Google has it, its id, its version


# ---- the changes, through the agent -----------------------------------------------------------------------------------------------------------

def agent_for(config, replies):
    return diya.Agent(config, client=FakeClient(list(replies)), action_kinds=list(gt.action_kinds()))


def propose(config, google, message, tool, args):
    agent = agent_for(config, [tool_reply(tool, json.dumps(args)), text_reply("ok")])
    agent.ask([{"role": "user", "content": message}])
    return agent


def run_approved(agent):
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    return agent.actions.run(action["id"])


def test_marking_a_task_done_is_proposed_found_approved_run_and_read_back(config, google):
    agent = propose(config, google, "mark buy milk as done in my google tasks", "propose_complete_google_task", {"title": "buy milk"})
    (action,) = agent.actions.actions()
    assert action["status"] == "pending" and action["summary"] == "Mark done in your Google Tasks: Buy milk" and action["args"]["task_id"] == "id00001"
    assert not [r for r in google.requests if r[0] in ("PATCH", "DELETE", "POST")]  # proposing changed nothing
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "Marked done in your Google Tasks and read back to check: Buy milk." in done["result"]
    assert google.tasks["id00001"]["status"] == "completed" and [r[0] for r in google.requests if r[0] != "GET"] == ["PATCH"]


def test_a_new_name_notes_or_day_that_are_not_the_persons_words_are_left_out(config, google):
    agent = propose(config, google, "rename buy milk to buy oat milk in my google tasks", "propose_update_google_task",
                    {"title": "buy milk", "new_title": "Buy oat milk", "new_notes": "A quick check that I am working", "due": "next century"})
    (action,) = agent.actions.actions()
    assert action["args"]["new_title"] == "Buy oat milk" and "new_notes" not in action["args"] and "due" not in action["args"]
    done = run_approved(agent)
    assert done["status"] == "succeeded" and google.tasks["id00001"]["title"] == "Buy oat milk" and "notes" not in google.tasks["id00001"]


def test_a_change_that_changes_nothing_is_refused_when_proposed(config, google):
    agent = propose(config, google, "change buy milk in my google tasks", "propose_update_google_task", {"title": "buy milk", "new_title": "something the user never said"})
    assert agent.actions.actions() == []


def test_moving_to_the_top_and_under_another_task(config, google):
    agent = propose(config, google, "move call the dentist to the top of my google tasks", "propose_move_google_task", {"title": "call the dentist"})
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "to the top of the list" in done["result"] and [r[2] for r in google.requests if r[0] == "POST"] == [None or {}]
    other = agent_for(config, [tool_reply("propose_move_google_task", json.dumps({"title": "renew bus pass", "under": "buy milk"})), text_reply("ok")])
    other.ask([{"role": "user", "content": "move renew bus pass under buy milk in my google tasks"}])
    done = run_approved(other)
    assert done["status"] == "succeeded" and google.tasks["id00003"].get("parent") == "id00001" and "under 'Buy milk'" in done["result"]


def test_deleting_says_it_cannot_be_undone_and_is_read_back(config, google):
    agent = propose(config, google, "delete renew bus pass from my google tasks", "propose_delete_google_task", {"title": "renew bus pass"})
    (action,) = agent.actions.actions()
    assert action["summary"] == "Delete from your Google Tasks: Renew bus pass (Diya cannot bring it back)"
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "id00003" not in google.tasks and "Deleted from your Google Tasks: Renew bus pass." in done["result"]


@pytest.mark.parametrize("message, tool, args", [
    ("mark buy milk as done", "propose_complete_google_task", {"title": "buy milk"}),  # does not name Google Tasks
    ("how do i delete a task in my google tasks", "propose_delete_google_task", {"title": "buy milk"}),  # a question about how
    ("don't delete buy milk from my google tasks", "propose_delete_google_task", {"title": "buy milk"}),  # a refusal
    ("add buy eggs to my google tasks", "propose_complete_google_task", {"title": "buy milk"}),  # a different request
    ("what is on my google tasks", "propose_move_google_task", {"title": "buy milk"}),
])
def test_a_message_that_did_not_ask_for_exactly_that_change_proposes_nothing(config, google, message, tool, args):
    agent = propose(config, google, message, tool, args)
    assert agent.actions.actions() == [] and not [r for r in google.requests if r[0] != "GET"]


def test_an_unknown_or_ambiguous_task_proposes_nothing_and_the_model_is_told_why(config, google):
    google.tasks["id00009"] = {"id": "id00009", "title": "Buy milk", "status": "needsAction", "etag": '"e9"'}
    agent = propose(config, google, "mark buy milk done in my google tasks", "propose_complete_google_task", {"title": "buy milk"})
    assert agent.actions.actions() == []
    told = [m["content"] for call in agent.client.chat_calls for m in call["messages"] if isinstance(m, dict) and m.get("role") == "tool"]
    assert any("2 open tasks" in text and "ask the user which one" in text for text in told)


# ---- what has to be true when it is run -------------------------------------------------------------------------------------------------------

def test_a_task_changed_in_google_after_the_proposal_is_not_touched(config, google):
    agent = propose(config, google, "mark buy milk as done in my google tasks", "propose_complete_google_task", {"title": "buy milk"})
    google.tasks["id00001"]["etag"] = '"someone-else-edited-it"'
    done = run_approved(agent)
    assert done["status"] == "failed" and "changed in Google Tasks after it was proposed" in done["result"] and google.tasks["id00001"]["status"] == "needsAction"
    assert not [r for r in google.requests if r[0] in ("PATCH", "DELETE", "POST")]


@pytest.mark.parametrize("change, words", [(lambda tasks: tasks.pop("id00001"), "not in your Google Tasks any more"), (lambda tasks: tasks["id00001"].update(status="completed"), "already done")])
def test_a_task_that_is_gone_or_already_done_is_not_touched(config, google, change, words):
    agent = propose(config, google, "delete buy milk from my google tasks", "propose_delete_google_task", {"title": "buy milk"})
    change(google.tasks)
    done = run_approved(agent)
    assert done["status"] == "failed" and words in done["result"] and not [r for r in google.requests if r[0] in ("PATCH", "DELETE", "POST")]


def test_a_change_google_says_it_made_but_reading_it_back_shows_it_did_not_is_not_confirmed(config, google, monkeypatch):
    agent = propose(config, google, "mark buy milk as done in my google tasks", "propose_complete_google_task", {"title": "buy milk"})
    real = google.__call__

    def lying(*args, **kwargs):
        answer = real(*args, **kwargs)
        if args and args[0] == "PATCH":
            google.tasks["id00001"]["status"] = "needsAction"  # Google said yes and did not keep it
        return answer

    monkeypatch.setattr(client.httpx, "request", lying)
    monkeypatch.setattr(client.httpx, "get", lying)
    done = run_approved(agent)
    assert done["status"] == "unknown" and "not confirmed" in done["result"]


def test_every_write_goes_to_the_default_list_and_a_task_in_another_list_is_refused(config, google):
    for method, url in (("PATCH", f"{BASE}/lists/listBBBBB/tasks/ex00001"), ("DELETE", f"{BASE}/lists/listBBBBB/tasks/ex00001"), ("POST", f"{BASE}/lists/listBBBBB/tasks/ex00001/move")):
        with pytest.raises(ActionFailed):
            client.send(config, "google_tasks", "Google Tasks", method, url, body={})
    assert not [r for r in google.requests if r[0] != "GET"]


# ---- never straight away --------------------------------------------------------------------------------------------------------------------------

def test_none_of_these_can_be_switched_to_straight_away_and_the_riskiest_is_level_three(config):
    for kind in gt.action_kinds():
        assert kind.name not in diya_autoapprove.AUTO_KINDS and kind.auto_ok is None
        with pytest.raises(ValueError):
            diya_autoapprove.set_enabled(diya_db_store(config), kind.name, True)
    import diya_catalog

    assert {n: diya_catalog.CATALOG[n].tier for n in ("propose_complete_google_task", "propose_update_google_task", "propose_move_google_task", "propose_delete_google_task")} == {
        "propose_complete_google_task": 2, "propose_update_google_task": 2, "propose_move_google_task": 2, "propose_delete_google_task": 3}


def diya_db_store(config):
    import diya_db

    return diya_db.Store(config.db_path)


def test_every_one_is_a_google_tasks_proposal_with_the_one_tool_name_the_catalog_lists():
    import diya_catalog

    names = {kind.tool_name for kind in gt.action_kinds()}
    assert names == {"propose_complete_google_task", "propose_update_google_task", "propose_move_google_task", "propose_delete_google_task"} and names <= set(diya_catalog.CATALOG)
    assert all(kind.connector == "google_tasks" and kind.resolve is not None and kind.asked is not None for kind in gt.action_kinds())


def test_the_connection_says_what_it_can_do_and_that_changes_wait_for_approval():
    import diya_connector_tools

    real = {c.name: c for c in diya_connector_tools.real_connectors(diya_config.load_config({}))}
    lines = " ".join(real["google_tasks"].access)
    assert "always waits for your approval" in lines and "Cannot complete" not in lines
