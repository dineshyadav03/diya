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
    assert url == "https://api.todoist.com/rest/v2/projects"
    assert kwargs["headers"]["Authorization"] == "Bearer a-token"


def test_todoist_validate_refuses_a_401(monkeypatch):
    fake_call(monkeypatch, fake_response(401))
    with pytest.raises(ConnectorError, match="rejected"):
        todoist_validate("bad-token")


def test_todoist_tasks_says_so_when_not_connected(config):
    assert todoist_tasks(config)() == "Todoist is not connected."


def test_todoist_tasks_formats_content_and_due_dates(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, [
        {"content": "Buy milk", "due": {"string": "today"}},
        {"content": "Call the dentist", "due": None},
    ]))
    assert todoist_tasks(config)() == "Buy milk (due today)\nCall the dentist"


def test_todoist_tasks_says_so_when_there_are_none(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, fake_response(200, []))
    assert todoist_tasks(config)() == "No matching tasks."


def test_todoist_tasks_passes_a_filter_through_when_given(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    calls = fake_call(monkeypatch, fake_response(200, []))
    todoist_tasks(config)("today")
    assert calls[0][1]["params"] == {"filter": "today"}


def test_todoist_tasks_sends_no_filter_param_when_none_is_given(config, monkeypatch):
    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    calls = fake_call(monkeypatch, fake_response(200, []))
    todoist_tasks(config)()
    assert calls[0][1]["params"] == {}


def test_todoist_tasks_reports_a_network_failure_without_crashing(config, monkeypatch):
    import httpx

    diya_connectors.connect(config, dataclasses.replace(real_connectors(config)[2], validate=lambda t: None), "a-token")
    fake_call(monkeypatch, raises=httpx.ConnectError("down"))
    assert "Couldn't reach Todoist" in todoist_tasks(config)()


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
