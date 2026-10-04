"""The three no-OAuth connectors (docs/CONNECTORS_DESIGN.md, unit C2): diya_connector_tools.py.
Every network call is faked (httpx.get/post is monkeypatched) -- no test here ever reaches a real
Home Assistant instance, Notion workspace or Todoist account, the same discipline
tests/test_connectors.py already holds C1's own plumbing to.

What this proves: each validator accepts a working token and refuses a bad one, a network failure,
or (Home Assistant only) a missing address, with a reason a person can read; each tool refuses
cleanly when its connector isn't connected, without making a network call; a successful call is
parsed into a short, readable answer; and Notion's own nested title format falls back sensibly
rather than crashing on an item with none.
"""
import dataclasses
import json
import types

import pytest

import diya_config
import diya_connector_tools
import diya_connectors
from diya_connector_tools import (
    home_assistant_search,
    home_assistant_validate,
    notion_search,
    notion_validate,
    real_connectors,
    todoist_tasks,
    todoist_validate,
    tool_specs,
)
from diya_connectors import ConnectorError


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        connector_tokens_dir=str(tmp_path / "tokens"),
        connectors_log_path=str(tmp_path / "connectors.log"),
        home_assistant_url="http://ha.local:8123",
    )


def fake_response(status_code=200, body=None):
    return types.SimpleNamespace(status_code=status_code, json=lambda: body if body is not None else {})


def fake_call(monkeypatch, response=None, raises=None, method="get"):
    """Patches diya_connector_tools.httpx.<method> to return `response` (or raise `raises`),
    recording every call's (url, kwargs) so a test can check what was actually sent."""
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(diya_connector_tools.httpx, method, fake)
    return calls


class Boom(Exception):
    """A stand-in for an httpx.HTTPError subclass: what matters is that it's caught, not which one."""


# --- Home Assistant --------------------------------------------------------------------------------

def test_home_assistant_validate_refuses_with_no_address_configured(config):
    config = dataclasses.replace(config, home_assistant_url="")
    with pytest.raises(ConnectorError, match="DIYA_HOME_ASSISTANT_URL"):
        home_assistant_validate(config)("a-token")


def test_home_assistant_validate_accepts_a_working_token(config, monkeypatch):
    calls = fake_call(monkeypatch, fake_response(200))
    home_assistant_validate(config)("a-token")  # does not raise
    (url, kwargs) = calls[0]
    assert url == "http://ha.local:8123/api/"
    assert kwargs["headers"]["Authorization"] == "Bearer a-token"


def test_home_assistant_validate_strips_a_trailing_slash_from_the_address(config, monkeypatch):
    config = dataclasses.replace(config, home_assistant_url="http://ha.local:8123/")
    calls = fake_call(monkeypatch, fake_response(200))
    home_assistant_validate(config)("a-token")
    assert calls[0][0] == "http://ha.local:8123/api/"


def test_home_assistant_validate_refuses_a_401(config, monkeypatch):
    fake_call(monkeypatch, fake_response(401))
    with pytest.raises(ConnectorError, match="rejected"):
        home_assistant_validate(config)("bad-token")


def test_home_assistant_validate_refuses_any_other_bad_status(config, monkeypatch):
    fake_call(monkeypatch, fake_response(500))
    with pytest.raises(ConnectorError, match="500"):
        home_assistant_validate(config)("a-token")


def test_home_assistant_validate_wraps_a_network_error(config, monkeypatch):
    import httpx

    fake_call(monkeypatch, raises=httpx.ConnectError("refused"))
    with pytest.raises(ConnectorError, match="couldn't reach Home Assistant"):
        home_assistant_validate(config)("a-token")


def test_home_assistant_search_says_so_when_not_connected(config):
    assert home_assistant_search(config)("light") == "Home Assistant is not connected."


def test_home_assistant_search_finds_a_matching_entity_by_name_or_id(config, monkeypatch):
    diya_connectors.connect(
        config, dataclasses.replace(real_connectors(config)[0], validate=lambda t: None), "a-token"
    )
    fake_call(monkeypatch, fake_response(200, [
        {"entity_id": "light.living_room", "state": "on", "attributes": {"friendly_name": "Living Room Light"}},
        {"entity_id": "lock.front_door", "state": "locked", "attributes": {"friendly_name": "Front Door"}},
    ]))
    result = home_assistant_search(config)("living room")
    assert result == "Living Room Light (light.living_room): on"


def test_home_assistant_search_shows_at_most_5_matches(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[0], validate=lambda t: None), "a-token")
    entities = [
        {"entity_id": f"light.room{i}", "state": "on", "attributes": {"friendly_name": f"Room {i} light"}}
        for i in range(8)
    ]
    fake_call(monkeypatch, fake_response(200, entities))
    result = home_assistant_search(config)("light")
    assert len(result.splitlines()) == 5


def test_home_assistant_search_says_so_when_nothing_matches(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[0], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, []))
    assert "No entity matching" in home_assistant_search(config)("nothing")


def test_home_assistant_search_reports_a_network_failure_without_crashing(config, monkeypatch):
    import httpx

    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[0], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, raises=httpx.ConnectError("down"))
    assert "Couldn't reach Home Assistant" in home_assistant_search(config)("light")


# --- Notion ----------------------------------------------------------------------------------------

def test_notion_validate_accepts_a_working_token(monkeypatch, config):
    calls = fake_call(monkeypatch, fake_response(200))
    notion_validate("a-token")
    (url, kwargs) = calls[0]
    assert url == "https://api.notion.com/v1/users/me"
    assert kwargs["headers"]["Notion-Version"]
    assert kwargs["headers"]["Authorization"] == "Bearer a-token"


def test_notion_validate_refuses_a_401(monkeypatch):
    fake_call(monkeypatch, fake_response(401))
    with pytest.raises(ConnectorError, match="rejected"):
        notion_validate("bad-token")


def test_notion_validate_refuses_any_other_bad_status(monkeypatch):
    fake_call(monkeypatch, fake_response(503))
    with pytest.raises(ConnectorError, match="503"):
        notion_validate("a-token")


def test_notion_search_says_so_when_not_connected(config):
    assert notion_search(config)("plans") == "Notion is not connected."


def test_notion_search_reads_the_title_from_a_real_shaped_result(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[1], validate=lambda t: None), "a-token")
    fake_call(
        monkeypatch,
        fake_response(200, {"results": [
            {"id": "1", "properties": {"Name": {"type": "title", "title": [{"plain_text": "Trip "}, {"plain_text": "plans"}]}}},
        ]}),
        method="post",
    )
    assert notion_search(config)("trip") == "Trip plans"


def test_notion_search_falls_back_to_the_id_when_there_is_no_title_property(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[1], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, {"results": [{"id": "abc123", "properties": {}}]}), method="post")
    assert notion_search(config)("x") == "abc123"


def test_notion_search_says_so_when_nothing_matches(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[1], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, {"results": []}), method="post")
    assert "No pages or databases" in notion_search(config)("nothing")


def test_notion_search_sends_the_query_and_a_small_page_size(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[1], validate=lambda t: None), "a-token")
    calls = fake_call(monkeypatch, fake_response(200, {"results": []}), method="post")
    notion_search(config)("my search")
    assert calls[0][1]["json"] == {"query": "my search", "page_size": 5}


def test_notion_search_reports_a_network_failure_without_crashing(config, monkeypatch):
    import httpx

    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[1], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, raises=httpx.TimeoutException("slow"), method="post")
    assert "Couldn't reach Notion" in notion_search(config)("x")


# --- Todoist -----------------------------------------------------------------------------------------

def test_todoist_validate_accepts_a_working_token(monkeypatch):
    calls = fake_call(monkeypatch, fake_response(200))
    todoist_validate("a-token")
    (url, kwargs) = calls[0]
    assert url == "https://api.todoist.com/api/v1/projects"  # the current API: the old /rest/v2 answers 410 Gone
    assert kwargs["params"] == {"limit": 1}
    assert kwargs["headers"]["Authorization"] == "Bearer a-token"


@pytest.mark.parametrize("status", [401, 403])
def test_todoist_validate_refuses_a_token_it_rejects(monkeypatch, status):
    fake_call(monkeypatch, fake_response(status))
    with pytest.raises(ConnectorError, match="Todoist rejected that token"):
        todoist_validate("bad-token")


@pytest.mark.parametrize("status", [400, 404, 410, 429, 500])
def test_todoist_validate_says_what_status_it_got_otherwise(monkeypatch, status):
    fake_call(monkeypatch, fake_response(status))
    with pytest.raises(ConnectorError, match=f"Todoist answered with HTTP {status}"):
        todoist_validate("a-token")


def test_todoist_validate_reports_a_network_failure_without_crashing(monkeypatch):
    import httpx

    fake_call(monkeypatch, raises=httpx.ConnectError("down"))
    with pytest.raises(ConnectorError, match="couldn't reach Todoist: down"):
        todoist_validate("a-token")


def test_todoist_tasks_says_so_when_not_connected(config):
    assert todoist_tasks(config)() == "Todoist is not connected."


def test_todoist_tasks_formats_content_and_due_dates(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_response_body = {"results": [
        {"content": "Buy milk", "due": {"string": "today"}},
        {"content": "Call the dentist", "due": None},
        {"content": "Water plants", "due": {"string": ""}},
    ], "next_cursor": None}
    fake_call(monkeypatch, fake_response(200, fake_response_body))
    assert todoist_tasks(config)() == "Buy milk (due today)\nCall the dentist\nWater plants"


def test_todoist_tasks_says_so_when_there_are_none(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, {"results": [], "next_cursor": None}))
    assert todoist_tasks(config)() == "No matching tasks."


def test_todoist_tasks_uses_the_filter_endpoint_when_a_filter_is_given(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    calls = fake_call(monkeypatch, fake_response(200, {"results": []}))
    todoist_tasks(config)("today")
    assert calls[0][0] == "https://api.todoist.com/api/v1/tasks/filter"
    assert calls[0][1]["params"] == {"query": "today", "limit": 10}
    assert calls[0][1]["headers"]["Authorization"] == "Bearer a-token"


@pytest.mark.parametrize("empty", [None, ""])
def test_todoist_tasks_lists_everything_open_when_no_filter_is_given(config, monkeypatch, empty):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    calls = fake_call(monkeypatch, fake_response(200, {"results": []}))
    todoist_tasks(config)(empty)
    assert calls[0][0] == "https://api.todoist.com/api/v1/tasks"
    assert calls[0][1]["params"] == {"limit": 10}


def test_todoist_tasks_shows_at_most_ten_even_if_the_server_sends_more(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, {"results": [{"content": f"task {n}"} for n in range(12)]}))
    lines = todoist_tasks(config)().splitlines()
    assert lines == [f"task {n}" for n in range(10)]


@pytest.mark.parametrize("status", [401, 403, 410, 500])
def test_todoist_tasks_says_what_status_it_got_when_it_was_not_a_200(config, monkeypatch, status):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(status))
    assert todoist_tasks(config)() == f"Todoist answered with HTTP {status}."


def test_todoist_tasks_copes_with_an_answer_it_cannot_read(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")

    def not_json():
        raise ValueError("no JSON here")

    for body in (types.SimpleNamespace(status_code=200, json=not_json), fake_response(200, ["a", "list"]),
                 fake_response(200, {"results": "oops"}), fake_response(200, {"other": []})):
        fake_call(monkeypatch, body)
        assert todoist_tasks(config)() == "Todoist sent back something this couldn't read."


def test_todoist_tasks_reports_a_network_failure_without_crashing(config, monkeypatch):
    import httpx

    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, raises=httpx.ConnectError("down"))
    assert "Couldn't reach Todoist" in todoist_tasks(config)()


# --- Todoist: adding a task, the first write (docs/ACTIONS_DESIGN.md, D11 and unit A4) -------------------

import httpx  # noqa: E402

import diya_actions  # noqa: E402
from diya_actions import ActionFailed, ActionUncertain, Actions, InvalidArgs  # noqa: E402
from diya_connector_tools import (  # noqa: E402
    real_action_kinds,
    todoist_add_task_execute,
    todoist_add_task_kind,
    todoist_add_task_render,
    todoist_add_task_validate,
)
from diya_db import Store  # noqa: E402


@pytest.fixture
def connected(config):
    diya_connectors.store_token(config, "todoist", "a-token")
    return config


@pytest.mark.parametrize("args", [
    {"content": "Buy milk"}, {"content": "Buy milk", "due_string": "tomorrow at 5pm"},
    {"content": "x" * 200}, {"content": "x", "due_string": "y" * 60},
])
def test_a_task_with_content_and_perhaps_a_due_phrase_is_valid(args):
    todoist_add_task_validate(args)


@pytest.mark.parametrize("args, why", [
    ({}, "needs its content"), ({"content": ""}, "needs its content"), ({"content": 5}, "needs its content"),
    ({"content": None}, "needs its content"), ({"content": ["a"]}, "needs its content"),
    ({"content": "x" * 201}, "at most 200 characters"),
    ({"content": "x", "due_string": ""}, "must be words"), ({"content": "x", "due_string": 5}, "must be words"),
    ({"content": "x", "due_string": None}, "must be words"),
    ({"content": "x", "due_string": "y" * 61}, "at most 60 characters"),
    ({"content": "x", "project_id": "1"}, "has no project_id"), ({"content": "x", "labels": ["a"], "priority": 1}, "has no labels, priority"),
])
def test_a_task_that_is_not_valid_says_why(args, why):
    with pytest.raises(InvalidArgs, match=why):
        todoist_add_task_validate(args)


def test_the_sentence_the_owner_approves_says_where_it_goes_and_when():
    assert todoist_add_task_render({"content": "Buy milk"}) == "Add to your Todoist Inbox: Buy milk"
    assert todoist_add_task_render({"content": "Buy milk", "due_string": "tomorrow"}) == "Add to your Todoist Inbox: Buy milk (due tomorrow)"


def test_the_longest_task_still_fits_in_the_sentence_the_store_allows(config):
    kind = todoist_add_task_kind()
    diya_connectors.store_token(config, "todoist", "a-token")
    actions = Actions(Store(config.db_path), config, (kind,))
    action = actions.propose("todoist_add_task", {"content": "x" * 200, "due_string": "y" * 60})
    assert len(action["summary"]) <= diya_actions.MAX_SUMMARY_CHARS


def test_the_connections_page_says_todoist_can_add_a_task_only_when_you_approve_it(config):
    descriptions = {c.name: c.description for c in real_connectors(config)}
    assert descriptions["todoist"] == "List your open tasks, and add one when you approve it."


def test_the_real_registry_is_exactly_the_todoist_task_and_its_tool_proposes_only():
    kinds = real_action_kinds()
    assert [(k.name, k.connector, k.tool_name, k.label) for k in kinds] == [
        ("todoist_add_task", "todoist", "propose_todoist_task", "Add a Todoist task")]
    function = kinds[0].tool["function"]
    assert "only PROPOSES" in function["description"] and "approves it on the Actions page" in function["description"]
    assert function["parameters"]["required"] == ["content"]
    assert set(function["parameters"]["properties"]) == {"content", "due_string"}
    assert not any(hasattr(diya_connector_tools, name) for name in ("KINDS",))


@pytest.mark.parametrize("phrase, text, said", [
    ("tomorrow", "add a task to call mum tomorrow", True),
    ("Tomorrow", "add it for tomorrow.", True),
    ("tomorrow at 5pm", "Add a task called prepare slides, due tomorrow at 5pm", True),
    ("tomorrow  at   5pm", "due TOMORROW AT 5PM please", True),
    ("friday", "send the invoice by Friday?", True),
    ("Friday.", "by friday", True),
    ("friday!", "by friday", True),
    ("next week", "do it next week, thanks", True),
    ("day", "call mum on Monday", False),
    ("friday 5pm", "send the invoice by Friday", False),
    ("next friday", "send the invoice by Friday", False),
    ("tomorrow at 5pm", "add task call mum", False),
    ("in 2 days", "New task: pay the electricity bill", False),
    ("", "anything", False),
    ("   ", "anything", False),
    (".", "anything.", False),
    ("5pm", "add a task at 5pm", True),
    ("a.m", "start at 9 a.m.", True),
    ("tomorrow", None, False),
    ("tomorrow", 42, False),
    ("3.30pm", "at 3x30pm", False),  # a full stop in the phrase is a full stop, not "any character"
    ("3.30pm", "at 3.30pm", True),
    ("a+b", "a+b", True),
    ("a+b", "aab", False),
    ("(soon)", "do it (soon)", True),
    ("tomorrow", "yesterday and tomorrow", True),  # anywhere in the message
    ("tomorrow", "tomorrows", False),  # but whole words
    ("morrow", "tomorrow", False),
])
def test_a_due_phrase_counts_as_said_only_when_it_is_the_persons_own_whole_words(phrase, text, said):
    assert diya_connector_tools._said(phrase, text) is said


def test_a_due_phrase_the_person_did_not_say_is_left_out_and_the_model_is_told():
    args, notes = diya_connector_tools.todoist_add_task_prepare({"content": "Call mum", "due_string": "tomorrow at 5pm"}, "add task call mum")
    assert args == {"content": "Call mum"}
    assert notes == ["It has no due date: 'tomorrow at 5pm' was left out, because the user did not say when."]


def test_a_due_phrase_the_person_did_say_is_kept_untouched():
    given = {"content": "Call mum", "due_string": "tomorrow"}
    args, notes = diya_connector_tools.todoist_add_task_prepare(given, "add a task to call mum tomorrow")
    assert args == given and notes == []


def test_a_task_with_no_due_phrase_is_left_alone():
    args, notes = diya_connector_tools.todoist_add_task_prepare({"content": "Call mum"}, "add task call mum")
    assert args == {"content": "Call mum"} and notes == []


def test_the_original_arguments_are_not_changed_by_leaving_something_out():
    given = {"content": "Call mum", "due_string": "next week"}
    diya_connector_tools.todoist_add_task_prepare(given, "add task call mum")
    assert given == {"content": "Call mum", "due_string": "next week"}


def test_the_real_kind_uses_the_task_request_guard_and_the_due_phrase_check():
    import diya_intent

    (kind,) = real_action_kinds()
    assert kind.asked is diya_intent.is_task_request
    assert kind.prepare is diya_connector_tools.todoist_add_task_prepare


def run_through_the_agent(config, message, arguments):
    """The real Agent and the real kind, with a scripted model that proposes `arguments` whatever it is asked, and Todoist
    'connected'. Returns (the agent, what the model was told back by the tool)."""
    from fakes import FakeClient, text_reply, tool_reply

    import diya

    diya_connectors.store_token(config, "todoist", "a-token")
    agent = diya.Agent(config, client=FakeClient([tool_reply("propose_todoist_task", json.dumps(arguments)), text_reply("ok")]))
    agent.ask([{"role": "user", "content": message}])
    told = [m["content"] for m in agent.client.chat_calls[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"][-1]
    return agent, told


def test_a_message_that_asks_for_a_task_gets_one_proposed_and_nothing_is_sent(monkeypatch, config):
    calls = post_ok(monkeypatch, {"id": "1"})
    agent, told = run_through_the_agent(config, "Add a task to buy oat milk", {"content": "Buy oat milk"})
    assert [a["summary"] for a in agent.actions.actions()] == ["Add to your Todoist Inbox: Buy oat milk"]
    assert told.startswith("Proposed as action #1: Add to your Todoist Inbox: Buy oat milk. Nothing has happened yet")
    assert calls == []


@pytest.mark.parametrize("message", ["I need to buy milk", "I'm running low on printer ink", "Make a note to call the plumber",
                                     "What's on my to-do list?", "Don't add a task for that", "How do I add a task in Todoist?"])
def test_a_message_that_does_not_ask_for_a_task_gets_none_proposed(monkeypatch, config, message):
    calls = post_ok(monkeypatch, {"id": "1"})
    agent, told = run_through_the_agent(config, message, {"content": "Buy milk"})
    assert agent.actions.actions() == [] and calls == []
    assert told == diya_actions.NOT_ASKED_TEXT


def test_a_due_date_the_model_made_up_is_left_off_the_card_and_the_model_is_told(monkeypatch, config):
    post_ok(monkeypatch, {"id": "1"})
    agent, told = run_through_the_agent(config, "add task call mum", {"content": "Call mum", "due_string": "tomorrow at 5pm"})
    (action,) = agent.actions.actions()
    assert action["args"] == {"content": "Call mum"} and action["summary"] == "Add to your Todoist Inbox: Call mum"
    assert "It has no due date: 'tomorrow at 5pm' was left out, because the user did not say when." in told


def test_a_due_date_the_person_gave_is_on_the_card(monkeypatch, config):
    post_ok(monkeypatch, {"id": "1"})
    agent, told = run_through_the_agent(config, "Add a task called prepare slides, due tomorrow at 5pm",
                                        {"content": "Prepare slides", "due_string": "tomorrow at 5pm"})
    assert agent.actions.actions()[0]["summary"] == "Add to your Todoist Inbox: Prepare slides (due tomorrow at 5pm)"
    assert "left out" not in told


def test_an_empty_due_date_is_no_due_date_and_does_not_bounce(monkeypatch, config):
    post_ok(monkeypatch, {"id": "1"})
    agent, told = run_through_the_agent(config, "Add a task to buy oat milk", {"content": "Buy oat milk", "due_string": ""})
    assert agent.actions.actions()[0]["args"] == {"content": "Buy oat milk"} and told.startswith("Proposed as action #1")


def test_a_due_date_in_the_persons_words_with_other_capitals_and_a_full_stop_is_kept(monkeypatch, config):
    post_ok(monkeypatch, {"id": "1"})
    agent, _ = run_through_the_agent(config, "Add a task to call the bank. Make it due Friday.", {"content": "Call the bank", "due_string": "friday"})
    assert agent.actions.actions()[0]["args"] == {"content": "Call the bank", "due_string": "friday"}


def post_ok(monkeypatch, body=None, status=200):
    return fake_call(monkeypatch, fake_response(status, body), method="post")


def test_adding_a_task_posts_it_to_the_inbox_with_the_token(monkeypatch, connected):
    calls = post_ok(monkeypatch, {"id": "6XGgmFVcrG5RRjVr"})
    said = todoist_add_task_execute(connected, {"content": "Buy milk"})
    assert said == "Added to your Todoist Inbox (task 6XGgmFVcrG5RRjVr)."
    ((url, kwargs),) = calls
    assert url == "https://api.todoist.com/api/v1/tasks"
    assert kwargs["json"] == {"content": "Buy milk"}  # no project: Todoist puts it in the Inbox
    assert kwargs["headers"] == {"Authorization": "Bearer a-token"}
    assert kwargs["timeout"] == 5.0


def test_only_the_content_and_the_due_phrase_are_ever_sent_whatever_else_is_in_the_arguments(monkeypatch, connected):
    # The checks upstream already refuse anything else, but what is sent is a short list of its own, not "whatever was approved".
    calls = post_ok(monkeypatch, {"id": "1"})
    todoist_add_task_execute(connected, {"content": "Buy milk", "due_string": "tomorrow", "project_id": "123", "labels": ["a"], "priority": 4})
    todoist_add_task_execute(connected, {"content": "Buy bread", "due_string": "", "assignee_id": "9"})
    todoist_add_task_execute(connected, {"content": "Buy tea", "due_string": None})
    assert [kwargs["json"] for _url, kwargs in calls] == [
        {"content": "Buy milk", "due_string": "tomorrow"}, {"content": "Buy bread"}, {"content": "Buy tea"}]


def test_a_due_phrase_is_sent_only_when_there_is_one(monkeypatch, connected):
    calls = post_ok(monkeypatch, {"id": "1"})
    todoist_add_task_execute(connected, {"content": "Buy milk", "due_string": "tomorrow at 5pm"})
    assert calls[0][1]["json"] == {"content": "Buy milk", "due_string": "tomorrow at 5pm"}


@pytest.mark.parametrize("status", [200, 201])
def test_either_success_status_counts(monkeypatch, connected, status):
    post_ok(monkeypatch, {"id": "7"}, status)
    assert todoist_add_task_execute(connected, {"content": "x"}) == "Added to your Todoist Inbox (task 7)."


def test_a_success_with_no_readable_id_is_still_a_success(monkeypatch, connected):
    def not_json():
        raise ValueError("no JSON")

    for response in (types.SimpleNamespace(status_code=200, json=not_json), fake_response(200, ["a list"]), fake_response(200, {"no": "id"})):
        fake_call(monkeypatch, response, method="post")
        assert todoist_add_task_execute(connected, {"content": "x"}) == "Added to your Todoist Inbox."


def test_with_no_token_stored_nothing_is_sent(monkeypatch, config):
    calls = post_ok(monkeypatch, {"id": "1"})
    with pytest.raises(ActionFailed, match="not connected, so nothing was added"):
        todoist_add_task_execute(config, {"content": "x"})
    assert calls == []


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_is_a_failure_that_says_to_reconnect(monkeypatch, connected, status):
    post_ok(monkeypatch, status=status)
    with pytest.raises(ActionFailed, match="refused the token, so nothing was added. Reconnect Todoist on the Connections page"):
        todoist_add_task_execute(connected, {"content": "x"})


def test_being_rate_limited_is_a_failure_that_says_to_propose_it_again(monkeypatch, connected):
    post_ok(monkeypatch, status=429)
    with pytest.raises(ActionFailed, match="limiting requests right now, so nothing was added. Propose it again in a minute"):
        todoist_add_task_execute(connected, {"content": "x"})


@pytest.mark.parametrize("status", [400, 404, 410, 418, 302])
def test_any_other_refusal_is_a_failure_that_names_the_status(monkeypatch, connected, status):
    post_ok(monkeypatch, status=status)
    with pytest.raises(ActionFailed, match=f"Todoist answered with HTTP {status}, so nothing was added"):
        todoist_add_task_execute(connected, {"content": "x"})


@pytest.mark.parametrize("status", [500, 502, 503, 599])
def test_a_failure_on_todoists_side_leaves_it_unknown_whether_the_task_exists(monkeypatch, connected, status):
    post_ok(monkeypatch, status=status)
    with pytest.raises(ActionUncertain, match=f"HTTP {status}.*may or may not have been added.*record what you found"):
        todoist_add_task_execute(connected, {"content": "x"})


@pytest.mark.parametrize("boundary", [499, 600])
def test_the_edges_of_the_server_error_range_are_not_server_errors(monkeypatch, connected, boundary):
    post_ok(monkeypatch, status=boundary)
    with pytest.raises(ActionFailed):
        todoist_add_task_execute(connected, {"content": "x"})


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.PoolTimeout("busy"),
                                   httpx.UnsupportedProtocol("odd")])
def test_a_request_that_was_never_sent_is_a_failure_that_says_nothing_was_added(monkeypatch, connected, error):
    fake_call(monkeypatch, raises=error, method="post")
    with pytest.raises(ActionFailed, match="Couldn't reach Todoist .*, so nothing was added"):
        todoist_add_task_execute(connected, {"content": "x"})


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.WriteTimeout("slow"), httpx.ReadError("cut"),
                                   httpx.WriteError("cut"), httpx.RemoteProtocolError("hung up"), httpx.DecodingError("garbled"),
                                   httpx.TooManyRedirects("loop")])
def test_a_request_that_may_have_reached_todoist_leaves_it_unknown(monkeypatch, connected, error):
    fake_call(monkeypatch, raises=error, method="post")
    with pytest.raises(ActionUncertain, match="sent to Todoist but no answer came back.*may or may not have been added"):
        todoist_add_task_execute(connected, {"content": "x"})


def test_a_timeout_after_sending_names_the_timeout(monkeypatch, connected):
    fake_call(monkeypatch, raises=httpx.ReadTimeout(""), method="post")
    with pytest.raises(ActionUncertain, match="the request timed out"):
        todoist_add_task_execute(connected, {"content": "x"})


def test_the_whole_flow_proposed_approved_and_run_posts_exactly_once(monkeypatch, connected):
    calls = post_ok(monkeypatch, {"id": "abc"})
    actions = Actions(Store(connected.db_path), connected, real_action_kinds())
    action = actions.propose("todoist_add_task", {"content": "Buy milk", "due_string": "tomorrow"})
    assert calls == []  # proposing sends nothing
    actions.approve(action["id"], action["args_hash"], "ui")
    assert calls == []  # nor does approving: only run does
    done = actions.run(action["id"])
    assert done["status"] == "succeeded" and done["result"] == "Added to your Todoist Inbox (task abc)."
    assert len(calls) == 1
    assert actions.verify_integrity() == []


def test_a_task_whose_post_may_have_gone_through_is_unknown_and_is_never_posted_again(monkeypatch, connected):
    calls = fake_call(monkeypatch, raises=httpx.ReadTimeout(""), method="post")
    actions = Actions(Store(connected.db_path), connected, real_action_kinds())
    action = actions.propose("todoist_add_task", {"content": "Buy milk"})
    actions.approve(action["id"], action["args_hash"], "cli")
    done = actions.run(action["id"])
    assert done["status"] == "unknown" and "may or may not have been added" in done["result"]
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(action["id"])
    assert len(calls) == 1
    assert actions.resolve(action["id"], True, "cli", note="it is in my Inbox")["status"] == "succeeded"
    assert len(calls) == 1  # finding out never posts again


def test_disconnecting_between_proposing_and_approving_stops_it_before_anything_is_sent(monkeypatch, connected):
    calls = post_ok(monkeypatch, {"id": "abc"})
    actions = Actions(Store(connected.db_path), connected, real_action_kinds())
    action = actions.propose("todoist_add_task", {"content": "Buy milk"})
    actions.approve(action["id"], action["args_hash"], "ui")
    diya_connectors.disconnect(connected, "todoist")
    done = actions.run(action["id"])
    assert done["status"] == "failed" and done["result"] == "Not run: todoist is no longer connected"
    assert calls == []


def test_it_cannot_be_proposed_at_all_while_todoist_is_not_connected(config):
    actions = Actions(Store(config.db_path), config, real_action_kinds())
    with pytest.raises(diya_actions.NotConnected):
        actions.propose("todoist_add_task", {"content": "Buy milk"})


# --- the registry and tool specs --------------------------------------------------------------------

def test_real_connectors_are_all_implemented(config):
    connectors = real_connectors(config)
    assert {c.name for c in connectors} == {"home_assistant", "notion", "todoist", "google_calendar"}
    assert all(c.implemented for c in connectors)
    token_ones = [c for c in connectors if c.name != "google_calendar"]
    assert all(c.auth_kind == "token" and c.validate is not None for c in token_ones)
    google = diya_connectors.by_name(connectors, "google_calendar")
    assert google.auth_kind == "oauth" and google.oauth_connect is not None


def test_tool_specs_match_the_real_connector_names(config):
    names = {name for name, _spec, _func in tool_specs(config)}
    assert names == {"home_assistant", "notion", "todoist", "google_calendar"}


def test_every_tool_spec_names_a_real_function_that_is_callable(config):
    for _name, spec, func in tool_specs(config):
        assert spec["type"] == "function"
        assert callable(func)
        assert spec["function"]["name"]
