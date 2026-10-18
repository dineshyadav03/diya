"""What each connection can do, since when, and when it was last used (diya_permissions_api.py, the Connections page; docs/PERMISSIONS_DESIGN.md), added 2026-10-18 for DIYA-072.

What this proves, with the real connectors, journal and approval system: every connection says in plain sentences what it can do and, in the same breath, what it cannot; a Google connection names the exact
permission it asks Google for, and that is the narrowest one that does the job (read-only for Calendar and Gmail, calendar.events, tasks and drive.file for the adding ones); a connected one says since
when, and when it was last used and for what, taken from the activity journal, and the last approved action run through it; an unconnected one says none of that; nothing that is a credential is in the
answer; and the words match what the code does (a connection said to be unable to write has no write action behind it).
"""
import dataclasses
import json
import os

import pytest
from fastapi.testclient import TestClient

import diya
import diya_catalog
import diya_config
import diya_connector_tools
import diya_connectors
import diya_journal
import diya_web
from fakes import FakeClient


class Quiet:
    def transcribe(self, path):
        return ""


@pytest.fixture
def world(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "p.db"), profile_path=str(tmp_path / "p.txt"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "l"),
        protect_secrets=False, require_token=False,
    )
    agent = diya.Agent(config, client=FakeClient())
    client = TestClient(diya_web.create_app(config, agent, Quiet()), base_url="https://localhost")
    return config, agent, client


def by_name(client):
    return {item["name"]: item for item in client.get("/api/permissions").json()["connectors"]}


def test_every_real_connection_says_what_it_can_do_and_what_it_cannot(world):
    _, _, client = world
    found = by_name(client)
    assert set(found) == {"home_assistant", "notion", "todoist", "google_calendar", "google_mail", "google_calendar_edit", "google_tasks", "google_drive_files"}
    for name, item in found.items():
        assert item["access"] and all(isinstance(line, str) and line.endswith(".") for line in item["access"]), name
        assert any(line.startswith("Cannot") for line in item["access"]), f"{name} must say what it cannot do"


def test_a_google_connection_names_the_exact_and_narrowest_permission_it_asks_for(world):
    _, _, client = world
    found = by_name(client)
    assert found["google_calendar"]["scope"] == "https://www.googleapis.com/auth/calendar.readonly"
    assert found["google_mail"]["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert found["google_calendar_edit"]["scope"] == "https://www.googleapis.com/auth/calendar.events"
    assert found["google_tasks"]["scope"] == "https://www.googleapis.com/auth/tasks"
    assert found["google_drive_files"]["scope"] == "https://www.googleapis.com/auth/drive.file"  # only files Diya made, never the rest of the Drive
    assert all(found[name]["scope"] == "" for name in ("home_assistant", "notion", "todoist"))  # a pasted token has no scope to name
    assert not any("mail.google.com" in item["scope"] or item["scope"].endswith("/auth/drive") for item in found.values())  # the broad ones are not asked for


def test_the_words_match_the_code_a_connection_that_cannot_write_has_no_write_action_behind_it(world):
    _, _, client = world
    found = by_name(client)
    writers = {kind.connector for kind in diya_connector_tools.real_action_kinds()}
    for name, item in found.items():
        says_it_adds = any("only when you approve" in line for line in item["access"])
        assert says_it_adds == (name in writers), name
    assert {name for name, item in found.items() if any(line.startswith("Cannot send") for line in item["access"])} == {"google_mail"}


def test_an_unconnected_connection_has_no_since_no_last_use_and_no_last_action(world):
    _, _, client = world
    item = by_name(client)["google_tasks"]
    assert item["connected"] is False and item["since"] is None and item["last_used"] is None and item["last_action"] is None


def test_a_connected_one_says_since_when_and_when_it_was_last_used_and_for_what(world):
    config, agent, client = world
    diya_connectors.store_token(config, "google_tasks", "refresh")
    diya_connectors.store_token(config, "google_calendar", "refresh")
    diya_journal.record(agent.store, "list_google_tasks", {}, "ok")
    diya_journal.record(agent.store, "list_google_tasks", {}, "error", note="timeout")
    diya_journal.record(agent.store, "list_calendar_events", {}, "ok")
    found = by_name(client)
    tasks = found["google_tasks"]
    assert tasks["connected"] is True and tasks["since"] and tasks["last_used"]["ok"] is False and tasks["last_used"]["what"] == "lists open Google Tasks"  # the newest one: it did not work
    assert found["google_calendar"]["last_used"] == {"at": found["google_calendar"]["last_used"]["at"], "what": "lists the next events on the person's Google Calendar", "ok": True}
    assert found["notion"]["last_used"] is None


def test_the_last_approved_action_run_through_a_connection_is_shown(world):
    config, agent, client = world
    diya_connectors.store_token(config, "google_tasks", "refresh")
    action = agent.actions.propose("google_tasks_add", {"title": "Renew the bus pass"})
    assert by_name(client)["google_tasks"]["last_action"] is None  # proposed, not run
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    agent.actions.run(action["id"])  # no network in a test: it fails before sending, which is still an approved action that was run
    last = by_name(client)["google_tasks"]["last_action"]
    assert last["summary"] == "Add to your Google Tasks: Renew the bus pass" and last["status"] in ("failed", "unknown", "succeeded") and last["at"]


def test_no_credential_is_ever_in_the_answer(world):
    config, _, client = world
    diya_connectors.store_token(config, "todoist", "SECRET-TOKEN-VALUE-1234")
    diya_connectors.store_token(config, "google_mail", "1//refresh-SECRET-5678")
    text = client.get("/api/permissions").text
    assert "SECRET" not in text and "refresh" not in text.replace("refresh token", "")
    assert set(json.loads(text)["connectors"][0]) == {"name", "label", "connected", "access", "scope", "granted", "granted_matches", "since", "last_used", "last_action"}


def test_every_catalog_entry_that_names_a_connection_names_a_real_one(world):
    config, _, _ = world
    real = {c.name for c in diya_connector_tools.real_connectors(config)}
    named = {entry.connector for entry in diya_catalog.CATALOG.values() if entry.connector}
    assert named <= real
    assert {e.connector for e in diya_catalog.CATALOG.values() if e.type in ("proposal",)} <= real and all(e.connector for e in diya_catalog.CATALOG.values() if e.type == "proposal")


def test_the_since_time_is_when_the_sign_in_was_stored(world):
    config, _, client = world
    diya_connectors.store_token(config, "notion", "t")
    stamp = os.path.getmtime(diya_connectors._token_path(config, "notion"))
    from datetime import datetime, timezone

    assert abs(datetime.fromisoformat(by_name(client)["notion"]["since"]).timestamp() - stamp) < 1


# ---- what Google said it granted ---------------------------------------------------------------------------------------------------------------

def test_what_google_says_it_granted_is_kept_when_signing_in_and_shown(world, monkeypatch):
    import diya_google_calendar as gcal
    from test_google_calendar import clicked_through, fake_post, fake_response

    config, _, client = world
    config = dataclasses.replace(config, google_client_id="a-client-id", google_client_secret="a-client-secret")
    fake_post(monkeypatch, fake_response(200, {"refresh_token": "rt", "scope": "https://www.googleapis.com/auth/calendar.readonly"}))
    gcal.connect(config, open_browser=clicked_through())
    item = by_name(client)["google_calendar"]
    assert item["granted"] == ["https://www.googleapis.com/auth/calendar.readonly"] and item["granted_matches"] is True


def test_a_grant_that_differs_from_what_was_asked_is_flagged_and_a_missing_answer_is_said_to_be_missing(world):
    config, _, client = world
    diya_connectors.store_token(config, "google_tasks", "rt")
    diya_connectors.store_granted(config, "google_tasks", "https://www.googleapis.com/auth/tasks https://www.googleapis.com/auth/drive")
    item = by_name(client)["google_tasks"]
    assert item["granted_matches"] is False and len(item["granted"]) == 2
    diya_connectors.store_token(config, "google_mail", "rt")  # a sign-in with no record of what was granted (from before this was kept, or Google did not say)
    mail = by_name(client)["google_mail"]
    assert mail["granted"] is None and mail["granted_matches"] is None


def test_disconnecting_forgets_what_was_granted(world):
    config, _, client = world
    diya_connectors.store_token(config, "google_tasks", "rt")
    diya_connectors.store_granted(config, "google_tasks", "https://www.googleapis.com/auth/tasks")
    assert diya_connectors.read_granted(config, "google_tasks")
    client.post("/api/connections/google_tasks/disconnect")
    assert diya_connectors.read_granted(config, "google_tasks") is None
    diya_connectors.store_granted(config, "google_tasks", "")  # nothing said, nothing stored
    assert diya_connectors.read_granted(config, "google_tasks") is None
