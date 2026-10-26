"""Reading the Google Tasks list (diya_google_write.google_tasks_list; DIYA-097 in part), added 2026-10-26.

What this proves: the list is one request for the open tasks only, asking for a bounded page (25); each task is shown with its due day when it has one; and when Google says there are more (a next-page token) the
answer says so in words, so a long list is never taken for the whole list, and a short one has no such line. It does not read the next page: one look is one request. Task ids are not shown (nothing the person or
the model does with the list needs one), so the row's "ids" and the other lists of the account remain open.
"""
import dataclasses
import types

import pytest

import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_write as gw


def reply(body):
    return types.SimpleNamespace(status_code=200, json=lambda: body, headers={})


@pytest.fixture
def config(tmp_path, monkeypatch):
    cfg = dataclasses.replace(diya_config.load_config(), connector_tokens_dir=str(tmp_path / "t"), connectors_log_path=str(tmp_path / "l"), google_client_id="id", google_client_secret="s")
    diya_connectors.store_token(cfg, "google_tasks", "refresh")
    monkeypatch.setattr(gcal, "access_token", lambda c, n: "tok")
    return cfg


def test_it_asks_once_for_the_open_tasks_and_a_bounded_page(config, monkeypatch):
    calls = []
    monkeypatch.setattr(gw.httpx, "get", lambda url, params=None, headers=None, timeout=None: calls.append((url, params)) or reply({"items": [{"title": "Renew pass", "due": "2026-10-23T00:00:00.000Z"}, {"title": "Plain"}]}))
    assert gw.google_tasks_list(config)() == "Renew pass (due 2026-10-23)\nPlain"
    assert calls == [(gw.TASKS_API, {"showCompleted": "false", "maxResults": gw.TASKS_PAGE})] and gw.TASKS_PAGE == 25


def test_a_longer_list_says_it_is_longer_and_a_complete_one_does_not(config, monkeypatch):
    items = [{"title": f"Task {n}"} for n in range(25)]
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: reply({"items": items, "nextPageToken": "abc"}))
    said = gw.google_tasks_list(config)()
    assert said.splitlines()[-1] == "(There are more open tasks than these 25; only the first 25 are shown.)" and said.count("\n") == 25
    monkeypatch.setattr(gw.httpx, "get", lambda *a, **k: reply({"items": items[:3]}))
    assert "more open tasks" not in gw.google_tasks_list(config)()
