"""The to-do list over HTTP (docs/TASKS_DESIGN.md, D7 and unit T2): diya_tasks_api.py.

What this proves: the list gives the open tasks oldest first and the most recently finished ones, with counts, and says
against the agent's own clock which open tasks are overdue (a task due on a day is not late until the day is over); a task
the person types has its "when" read by the same reader the model's goes through and words it cannot read are kept as words
rather than refused; the same words twice, a full list and text that cannot be stored are refusals that save nothing, each
with its own status; done and put-back apply once and a repeat or an unknown id is refused; everything a person is shown
reaches the browser with control, invisible and direction-changing characters as visible escapes; only GET and POST exist;
building the app touches no store; and what the model adds in the chat is what the page lists next.

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_memory
import diya_tasks
import diya_tasks_api
import diya_time
import diya_web
from fakes import FakeClient, text_reply, tool_reply

LOCAL = "https://localhost"
NOW = datetime(2026, 9, 23, 10, 15)  # a Wednesday, 10:15 local
ESC, BIDI, ZWSP = chr(27), chr(0x202E), chr(0x200B)


def ts(local):
    return diya_time.iso_of_local(local)


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "tasks.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"),
        connector_tokens_dir=str(data / "tokens"),
        connectors_log_path=str(data / "connectors.log"),
        require_token=False,
    )


@pytest.fixture
def clock():
    return {"now": NOW}


@pytest.fixture
def parts(config, clock):
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 10), clock=lambda: clock["now"])
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL), agent


@pytest.fixture
def client(parts):
    return parts[0]


@pytest.fixture
def tasks(parts):
    return parts[1].tasks


def no_hidden(value):
    if isinstance(value, str):
        return all(not diya_memory._unwanted(ch) for ch in value)
    if isinstance(value, dict):
        return all(no_hidden(k) and no_hidden(v) for k, v in value.items())
    if isinstance(value, list):
        return all(no_hidden(v) for v in value)
    return True


# --- listing ----------------------------------------------------------------------------------------------

def test_an_empty_list_says_so_with_zero_counts(client):
    assert client.get("/api/tasks").json() == {"tasks": [], "done": [], "counts": {"open": 0, "done": 0, "overdue": 0}}


def test_open_tasks_come_oldest_first_and_done_ones_are_listed_apart_newest_finished_first(client, tasks):
    for name in ("a", "b", "c", "d"):
        tasks.add(name)
    tasks.complete(3)
    tasks.complete(1)
    body = client.get("/api/tasks").json()
    assert [t["content"] for t in body["tasks"]] == ["b", "d"]
    assert [t["content"] for t in body["done"]] == ["c", "a"]  # finished in the same moment: the newer first
    assert body["counts"] == {"open": 2, "done": 2, "overdue": 0}
    assert all(t["done"] is False for t in body["tasks"]) and all(t["done"] is True for t in body["done"])


def test_only_the_most_recent_finished_tasks_are_sent(client, tasks, monkeypatch):
    monkeypatch.setattr(diya_tasks_api, "DONE_SHOWN", 2)
    for task_id in [tasks.add(name)["id"] for name in ("a", "b", "c")]:
        tasks.complete(task_id)
    body = client.get("/api/tasks").json()
    assert [t["content"] for t in body["done"]] == ["c", "b"] and body["counts"]["done"] == 3  # the count is of all of them


def test_the_page_is_sent_at_most_fifty_finished_tasks_by_default():
    assert diya_tasks_api.DONE_SHOWN == 50


def test_a_task_is_shown_with_the_time_in_words_and_the_persons_own_words(client, tasks):
    timed = tasks.add("Prepare slides", "Friday 5pm", thread_id=1)
    day = tasks.add("Send the invoice", "Friday")
    words = tasks.add("Water the plants", "when I'm back")
    plain = tasks.add("Buy milk", source="page")
    by_id = {t["id"]: t for t in client.get("/api/tasks").json()["tasks"]}
    assert by_id[timed["id"]] == {
        "id": timed["id"], "content": "Prepare slides", "said": "Friday 5pm", "due": ts(datetime(2026, 9, 25, 17, 0)),
        "due_text": "Friday 25 Sep 2026, 17:00", "overdue": False, "done": False, "completed": None, "from_chat": True,
    }
    assert by_id[day["id"]]["due_text"] == "Friday 25 Sep 2026" and by_id[day["id"]]["said"] == "Friday"  # a day, not nine o'clock
    assert (by_id[words["id"]]["due"], by_id[words["id"]]["due_text"], by_id[words["id"]]["said"]) == (None, None, "when I'm back")
    assert (by_id[plain["id"]]["said"], by_id[plain["id"]]["due"], by_id[plain["id"]]["from_chat"]) == (None, None, False)


def test_a_finished_task_says_when_it_was_finished(client, tasks):
    task = tasks.add("a")
    tasks.complete(task["id"])
    (item,) = client.get("/api/tasks").json()["done"]
    assert item["done"] is True and item["completed"] == ts(NOW) and item["overdue"] is False


def test_a_task_due_at_a_time_is_overdue_once_that_moment_has_passed(client, tasks, clock):
    tasks.add("Call mum", "today at 5pm")
    assert client.get("/api/tasks").json()["tasks"][0]["overdue"] is False
    clock["now"] = datetime(2026, 9, 23, 17, 0)
    assert client.get("/api/tasks").json()["tasks"][0]["overdue"] is False  # exactly then is not yet late
    clock["now"] = datetime(2026, 9, 23, 17, 1)
    body = client.get("/api/tasks").json()
    assert body["tasks"][0]["overdue"] is True and body["counts"]["overdue"] == 1


def test_a_task_due_on_a_day_is_not_overdue_until_the_day_is_over(client, tasks, clock):
    tasks.add("Send the invoice", "Friday")
    for moment, late in ((datetime(2026, 9, 25, 8, 0), False), (datetime(2026, 9, 25, 9, 1), False), (datetime(2026, 9, 25, 23, 59), False),
                         (datetime(2026, 9, 26, 0, 1), True)):
        clock["now"] = moment
        assert client.get("/api/tasks").json()["tasks"][0]["overdue"] is late, moment


def test_a_done_task_and_one_with_no_readable_date_are_never_overdue(client, tasks, clock):
    first = tasks.add("Old", "tomorrow at 5pm")
    tasks.add("Words", "when I'm back")
    tasks.complete(first["id"])
    clock["now"] = NOW + timedelta(days=30)
    body = client.get("/api/tasks").json()
    assert body["counts"]["overdue"] == 0 and all(t["overdue"] is False for t in body["tasks"] + body["done"])


def test_the_overdue_count_counts_only_open_overdue_tasks(client, tasks, clock):
    tasks.add("a", "today at 11am")
    tasks.add("b", "today at 12pm")
    tasks.add("c", "today at 11pm")
    clock["now"] = datetime(2026, 9, 23, 12, 30)
    assert client.get("/api/tasks").json()["counts"] == {"open": 3, "done": 0, "overdue": 2}


# --- adding one --------------------------------------------------------------------------------------------

def test_a_task_typed_by_the_person_is_saved_with_its_time_read_and_the_list_comes_back(client, tasks):
    response = client.post("/api/tasks", json={"text": "  call   mum ", "when": "tomorrow at 5pm"})
    assert response.status_code == 201
    body = response.json()
    assert body["task"]["content"] == "call mum" and body["task"]["due_text"] == "Thursday 24 Sep 2026, 17:00"
    assert body["task"]["from_chat"] is False and body["counts"] == {"open": 1, "done": 0, "overdue": 0}
    assert [t["id"] for t in body["tasks"]] == [body["task"]["id"]]
    (row,) = tasks.tasks("all")
    assert (row["content"], row["due_at"], row["due_ts"], row["source"]) == (
        "call mum", "tomorrow at 5pm", ts(datetime(2026, 9, 24, 17, 0)), "page")


def test_a_task_with_no_when_is_saved_with_no_date(client, tasks):
    for n, blank in enumerate((None, "", "   ")):
        response = client.post("/api/tasks", json={"text": f"water plants {n}", **({} if blank is None else {"when": blank})})
        assert response.status_code == 201 and response.json()["task"]["due"] is None and response.json()["task"]["said"] is None
    assert all(t["due_at"] is None and t["due_ts"] is None for t in tasks.tasks("all"))


@pytest.mark.parametrize("words", ["when I'm back", "next Friday", "yesterday", "soonish", "3/4"])
def test_a_when_that_cannot_be_read_is_kept_as_words_and_is_not_a_refusal(client, tasks, words):
    response = client.post("/api/tasks", json={"text": "call mum", "when": words})
    assert response.status_code == 201
    task = response.json()["task"]
    assert task["said"] == words and task["due"] is None and task["due_text"] is None
    assert tasks.tasks("all")[0]["due_ts"] is None


def test_the_same_words_twice_is_a_conflict_and_saves_nothing(client, tasks):
    first = client.post("/api/tasks", json={"text": "Buy oat milk"}).json()["task"]
    response = client.post("/api/tasks", json={"text": "buy OAT   milk", "when": "Friday"})
    assert response.status_code == 409 and response.json()["detail"] == "that task is already on the list"  # no number: they never see one
    assert len(tasks.tasks("all")) == 1


def test_a_full_list_is_a_conflict_that_saves_nothing(client, tasks, monkeypatch):
    monkeypatch.setattr(diya_tasks, "MAX_OPEN", 1)
    client.post("/api/tasks", json={"text": "a"})
    response = client.post("/api/tasks", json={"text": "b"})
    assert response.status_code == 409 and "1 open tasks" in response.json()["detail"]
    assert [t["content"] for t in tasks.tasks("all")] == ["a"]


@pytest.mark.parametrize("text, part", [
    ("", "needs words"), ("  \n ", "needs words"), ("x" * (diya_tasks.MAX_TASK_CHARS + 1), "at most 200 characters"),
    ("call" + ESC + "[2J mum", "cannot contain the character"), ("mum" + BIDI + "evil", "cannot contain"), ("a" + ZWSP + "b", "cannot contain"),
])
def test_text_that_cannot_be_used_is_refused_and_saves_nothing(client, tasks, text, part):
    response = client.post("/api/tasks", json={"text": text})
    assert response.status_code == 422 and part in response.json()["detail"], (text, response.json())
    assert no_hidden(response.json()) and tasks.tasks("all") == []


def test_text_of_exactly_the_limit_is_saved(client):
    assert client.post("/api/tasks", json={"text": "x" * diya_tasks.MAX_TASK_CHARS}).status_code == 201


def test_a_when_that_is_too_long_or_has_hidden_characters_is_refused_and_never_comes_back_hidden(client, tasks):
    for words in ("x" * 61, "fri" + ESC + "day 5pm", "soon" + BIDI + "ish", "at" + ZWSP + " 5", chr(0) + "x"):
        response = client.post("/api/tasks", json={"text": "call mum", "when": words})
        assert response.status_code == 422 and no_hidden(response.json()), (words, response.json())
    assert tasks.tasks("all") == []


@pytest.mark.parametrize("body", [{}, {"when": "friday 5pm"}, {"text": 5}, {"text": ["x"]}, {"text": "x", "when": 5}, {"text": None}])
def test_a_body_of_the_wrong_shape_is_refused_and_saves_nothing(client, tasks, body):
    assert client.post("/api/tasks", json=body).status_code == 422
    assert tasks.tasks("all") == []


def test_a_task_that_is_marked_as_html_is_saved_and_sent_as_text(client):
    client.post("/api/tasks", json={"text": "<img src=x onerror=alert(1)> <b>call</b>"})
    (item,) = client.get("/api/tasks").json()["tasks"]
    assert item["content"] == "<img src=x onerror=alert(1)> <b>call</b>"  # the page renders it as text; nothing here strips it


# --- done and back ---------------------------------------------------------------------------------------------

def test_marking_done_applies_once_and_the_task_moves_to_the_done_list(client, tasks):
    a, b = tasks.add("a")["id"], tasks.add("b")["id"]
    response = client.post(f"/api/tasks/{a}/done")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == a and [t["id"] for t in body["tasks"]] == [b] and [t["id"] for t in body["done"]] == [a]
    assert body["counts"] == {"open": 1, "done": 1, "overdue": 0}
    again = client.post(f"/api/tasks/{a}/done")
    assert again.status_code == 409 and "already done" in again.json()["detail"]


def test_putting_a_task_back_applies_once_and_it_returns_to_the_open_list(client, tasks):
    a = tasks.add("a")["id"]
    tasks.complete(a)
    response = client.post(f"/api/tasks/{a}/reopen")
    assert response.status_code == 200 and [t["id"] for t in response.json()["tasks"]] == [a] and response.json()["done"] == []
    again = client.post(f"/api/tasks/{a}/reopen")
    assert again.status_code == 409 and "already open" in again.json()["detail"]


def test_a_task_cannot_be_put_back_while_the_same_words_are_open_or_into_a_full_list(client, tasks, monkeypatch):
    old = tasks.add("Buy milk")["id"]
    tasks.complete(old)
    new = tasks.add("buy MILK")["id"]
    clash = client.post(f"/api/tasks/{old}/reopen")
    assert clash.status_code == 409 and clash.json()["detail"] == "the same task is already open" and f"#{new}" not in clash.text
    tasks.complete(new)
    monkeypatch.setattr(diya_tasks, "MAX_OPEN", 1)
    tasks.add("other")
    full = client.post(f"/api/tasks/{old}/reopen")
    assert full.status_code == 409 and "open tasks" in full.json()["detail"]
    assert tasks.get(old)["done"] is True


@pytest.mark.parametrize("action", ["done", "reopen"])
@pytest.mark.parametrize("path_id, status", [
    ("99", 404), ("0", 404), ("-5", 404), ("9223372036854775808", 404), ("9223372036854775807", 404), ("abc", 422), ("1.5", 422),
])
def test_an_unknown_task_or_id_is_refused_and_never_an_error(client, action, path_id, status):
    response = client.post(f"/api/tasks/{path_id}/{action}")
    assert response.status_code == status, response.text


def test_an_action_the_list_does_not_have_is_not_found(client, tasks):
    task = tasks.add("a")
    for action in ("undo", "delete", "edit", "complete"):
        assert client.post(f"/api/tasks/{task['id']}/{action}").status_code == 404
    assert tasks.tasks("all") == [task]


def test_marking_one_done_touches_no_other(client, tasks):
    ids = [tasks.add(name)["id"] for name in "abc"]
    client.post(f"/api/tasks/{ids[1]}/done")
    assert [t["id"] for t in client.get("/api/tasks").json()["tasks"]] == [ids[0], ids[2]]


# --- what reaches the browser ------------------------------------------------------------------------------------

def test_nothing_from_the_database_reaches_the_browser_with_a_hidden_character(client, parts):
    store = parts[1].store
    conn = store.connect()
    conn.execute(
        "INSERT INTO tasks (content, content_key, due_at, due_ts, done, source, created_at) VALUES (?, 'k', ?, ?, 0, 'chat', 't')",
        ("call" + ESC + "[2J mum" + BIDI + "evil", "fri" + ZWSP + "day 5pm", ts(datetime(2026, 9, 25, 17, 0))),
    )
    conn.commit()
    conn.close()
    body = client.get("/api/tasks").json()
    assert no_hidden(body)
    (item,) = body["tasks"]
    assert chr(92) + "u001b" in item["content"] and chr(92) + "u202e" in item["content"] and chr(92) + "u200b" in item["said"]


def test_only_get_and_post_exist_on_these_routes(client):
    for method in ("PUT", "DELETE", "PATCH"):
        assert client.request(method, "/api/tasks").status_code == 405
        assert client.request(method, "/api/tasks/1/done").status_code == 405
        assert client.request(method, "/api/tasks/1/reopen").status_code == 405
    assert client.get("/api/tasks/1/done").status_code == 405


def test_building_the_app_touches_no_store():
    """create_app must stay free: registering the task routes cannot need an agent that has a list."""
    import types

    agent = types.SimpleNamespace()  # no .tasks and no .now at all
    config = dataclasses.replace(diya_config.load_config(), require_token=False)
    app = diya_web.create_app(config, agent, object())
    assert {"/api/tasks", "/api/tasks/{task_id}/done", "/api/tasks/{task_id}/reopen"} <= {route.path for route in app.routes}


# --- end to end: what the model adds in the chat is what the page lists ---------------------------------------------

def chat_with(config, clock, *replies):
    agent = diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: clock["now"])
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL)


def test_a_task_the_model_adds_in_the_chat_is_listed_with_its_date_and_where_it_came_from(config, clock):
    client = chat_with(config, clock, tool_reply("add_task", '{"content": "Prepare slides", "due": "tomorrow at 5pm"}', call_id="c1"),
                       text_reply("Added."))
    answer = client.post("/api/chat", json={"message": "Add a task: prepare slides, due tomorrow at 5pm"}).json()
    assert answer["tools_called"] == ["add_task"]
    (item,) = client.get("/api/tasks").json()["tasks"]
    assert (item["content"], item["said"], item["due_text"], item["from_chat"]) == (
        "Prepare slides", "tomorrow at 5pm", "Thursday 24 Sep 2026, 17:00", True)


def test_the_message_a_task_came_from_is_recorded_with_it(config, clock):
    client = chat_with(config, clock, tool_reply("add_task", '{"content": "Buy milk"}', call_id="c1"), text_reply("Added."))
    thread = client.post("/api/chat", json={"message": "Add a task to buy milk"}).json()["thread_id"]
    row = diya.Agent(config, client=FakeClient()).tasks.tasks("all")[0]
    assert row["thread_id"] == thread and isinstance(row["message_id"], int)


def test_a_task_the_model_adds_unasked_is_refused_and_the_page_lists_nothing(config, clock):
    client = chat_with(config, clock, tool_reply("add_task", '{"content": "buy milk"}', call_id="c1"), text_reply("Noted."))
    client.post("/api/chat", json={"message": "I need to buy milk"})
    assert client.get("/api/tasks").json()["tasks"] == []


def test_a_task_the_model_adds_for_todoist_is_refused_and_the_page_lists_nothing(config, clock):
    client = chat_with(config, clock, tool_reply("add_task", '{"content": "buy milk"}', call_id="c1"), text_reply("Connect Todoist first."))
    client.post("/api/chat", json={"message": "Add a task to Todoist to buy milk"})
    assert client.get("/api/tasks").json()["tasks"] == []


def test_what_the_page_adds_the_model_then_reads(config, clock):
    client = chat_with(config, clock, tool_reply("list_tasks", "{}", call_id="c1"), text_reply("You have one."))
    client.post("/api/tasks", json={"text": "Buy oat milk"})
    answer = client.post("/api/chat", json={"message": "What's on my to-do list?"}).json()
    assert answer["tools_called"] == ["list_tasks"] and answer["answer"] == "You have one."
