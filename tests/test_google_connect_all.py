"""One Google sign-in for every Google card ("Connect all Google"; diya_google_calendar.connect_all, POST /api/connections/connect-google; docs/GOOGLE_SETUP.md), added 2026-10-26.

Why: connecting five cards meant five trips to Google's screen. What this proves, with Google's side played by stand-ins (no real Google, no real browser): Google is sent ONE sign-in that asks for exactly the
five permissions the app already had (nothing new); the one refresh token it returns is stored under each card whose permission was granted; a permission the owner unticked on Google's screen leaves its card
alone (not connected, or still connected as it was); no answer about what was granted, or nothing granted, or a failed step stores nothing; every card still disconnects on its own, Google is told to forget
the permission only when the LAST one goes, and a card connected again by itself stops being part of the shared sign-in; the permissions page compares what Google granted with the whole list that sign-in
asked, and flags something outside it; forgetting Google's app disconnects every Google card, Calendar included; and the page's button, its same-origin route and its words exist.
It does not prove how the real Google's screen looks or that it grants all five to an unverified app: that is docs/GOOGLE_LIVE_SMOKE.md.
"""
import dataclasses
import json
import re
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_connector_tools
import diya_connectors
import diya_google_calendar as gcal
import diya_web
from diya_connectors import ConnectorError
from fakes import FakeClient
from test_google_calendar import clicked_through, fake_post, fake_response  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
CAL, MAIL, EDIT, TASKS, DRIVE = "google_calendar", "google_mail", "google_calendar_edit", "google_tasks", "google_drive_files"
FIVE = {
    CAL: "https://www.googleapis.com/auth/calendar.readonly", MAIL: "https://www.googleapis.com/auth/gmail.readonly", EDIT: "https://www.googleapis.com/auth/calendar.events",
    TASKS: "https://www.googleapis.com/auth/tasks", DRIVE: "https://www.googleapis.com/auth/drive.file",
}


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config({}), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"), db_path=str(tmp_path / "g.db"),
        profile_path=str(tmp_path / "p.txt"), google_client_id="a-client-id", google_client_secret="a-client-secret", require_token=False, protect_secrets=False,
    )


def scopes_of_real_cards(config):
    return {c.name: c.scope for c in diya_connector_tools.real_connectors(config) if c.name in gcal.ALL_GOOGLE}


def signs_in(monkeypatch, granted, refresh="shared-refresh"):
    """Google's side of one sign-in: records what was asked, answers with `granted` (a list of scopes, or None for no answer about it)."""
    asked = []

    def stand_in(config, scope, open_browser):
        asked.append(scope)
        return refresh, (" ".join(granted) if granted is not None else None)

    monkeypatch.setattr(gcal, "_sign_in", stand_in)
    return asked


# ---- the sign-in --------------------------------------------------------------------------------------------------------------

def test_the_five_cards_are_these_five_permissions_and_nothing_else(config):
    assert scopes_of_real_cards(config) == FIVE


def test_one_sign_in_asks_google_once_for_exactly_the_five_permissions(config, monkeypatch):
    fake_post(monkeypatch, fake_response(200, {"refresh_token": "rt", "scope": " ".join(FIVE.values())}))
    seen = []
    gcal.connect_all(config, scopes_of_real_cards(config), open_browser=lambda url: (seen.append(url), clicked_through()(url)))
    assert len(seen) == 1  # one trip to Google's screen
    asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(seen[0]).query))["scope"].split()
    assert sorted(asked) == sorted(FIVE.values()) and "code_challenge" in seen[0]  # PKCE as for every sign-in


def test_every_card_whose_permission_was_granted_is_connected_with_the_one_token(config, monkeypatch):
    signs_in(monkeypatch, list(FIVE.values()))
    connected, left_out = gcal.connect_all(config, scopes_of_real_cards(config))
    assert sorted(connected) == sorted(FIVE) and left_out == []
    for name in FIVE:
        assert diya_connectors.read_token(config, name) == "shared-refresh"
        assert diya_connectors.read_granted(config, name) == list(FIVE.values())
        assert diya_connectors.read_together(config, name) == sorted(FIVE.values())


def test_a_permission_unticked_on_googles_screen_leaves_its_card_alone(config, monkeypatch):
    diya_connectors.store_token(config, MAIL, "mail-on-its-own")  # was connected before, by its own card
    diya_connectors.store_granted(config, MAIL, FIVE[MAIL])
    signs_in(monkeypatch, [FIVE[CAL], FIVE[TASKS], FIVE[DRIVE]])  # Gmail and add-events unticked
    connected, left_out = gcal.connect_all(config, scopes_of_real_cards(config))
    assert sorted(connected) == sorted([CAL, TASKS, DRIVE]) and sorted(left_out) == sorted([MAIL, EDIT])
    assert not diya_connectors.is_connected(config, EDIT)  # never connected: still not
    assert diya_connectors.read_token(config, MAIL) == "mail-on-its-own" and diya_connectors.read_granted(config, MAIL) == [FIVE[MAIL]] and diya_connectors.read_together(config, MAIL) is None  # untouched
    assert diya_connectors.read_token(config, CAL) == "shared-refresh"


@pytest.mark.parametrize("granted, why", [
    (None, "did not say which permissions"), ([], "did not say which permissions"), (["https://www.googleapis.com/auth/userinfo.email"], "not allowed to give Diya any"),
])
def test_no_answer_about_what_was_granted_or_nothing_granted_stores_nothing(config, monkeypatch, granted, why):
    signs_in(monkeypatch, granted)
    with pytest.raises(ConnectorError, match=why):
        gcal.connect_all(config, scopes_of_real_cards(config))
    assert not any(diya_connectors.is_connected(config, name) for name in FIVE)


def test_a_failed_step_stores_nothing(config, monkeypatch):
    fake_post(monkeypatch, fake_response(400, {"error": "invalid_grant"}))
    with pytest.raises(ConnectorError):
        gcal.connect_all(config, scopes_of_real_cards(config), open_browser=clicked_through())
    fake_post(monkeypatch, fake_response(200, {"scope": " ".join(FIVE.values())}))  # no refresh token
    with pytest.raises(ConnectorError, match="refresh token"):
        gcal.connect_all(config, scopes_of_real_cards(config), open_browser=clicked_through())
    with pytest.raises(ConnectorError):
        gcal.connect_all(config, scopes_of_real_cards(config), open_browser=clicked_through({"error": "access_denied", "code": None}))
    assert not any(diya_connectors.is_connected(config, name) for name in FIVE)


def test_only_googles_own_cards_count_and_an_empty_list_is_refused(config, monkeypatch):
    asked = signs_in(monkeypatch, [FIVE[TASKS]])
    connected, _ = gcal.connect_all(config, {TASKS: FIVE[TASKS], "todoist": "x", "google_unknown": "y", MAIL: ""})
    assert connected == [TASKS] and asked == [FIVE[TASKS]]
    with pytest.raises(ConnectorError, match="no Google card"):
        gcal.connect_all(config, {"todoist": "x"})


# ---- after it: each card on its own ---------------------------------------------------------------------------------------------

def test_a_card_disconnects_on_its_own_and_google_is_told_only_when_the_last_one_goes(config, monkeypatch):
    signs_in(monkeypatch, list(FIVE.values()))
    gcal.connect_all(config, scopes_of_real_cards(config))
    calls = fake_post(monkeypatch, fake_response(200, {}))
    cards = {c.name: c for c in diya_connector_tools.real_connectors(config)}
    names = list(FIVE)
    for name in names[:-1]:
        assert diya_connectors.revoke_and_disconnect(config, cards[name]) is None  # others are still connected: Google is not told
        assert not diya_connectors.is_connected(config, name) and diya_connectors.read_together(config, name) is None and diya_connectors.read_granted(config, name) is None
    assert calls == [] and all(diya_connectors.is_connected(config, name) for name in names[-1:])
    assert diya_connectors.revoke_and_disconnect(config, cards[names[-1]]) is True  # the last one: Google is told, once
    assert [url for url, _ in calls] == [gcal.REVOKE_URL] and calls[0][1] == {"token": "shared-refresh"}


def test_connecting_a_card_by_itself_afterwards_makes_it_its_own_sign_in(config, monkeypatch):
    signs_in(monkeypatch, list(FIVE.values()))
    gcal.connect_all(config, scopes_of_real_cards(config))
    signs_in(monkeypatch, [FIVE[TASKS]], refresh="tasks-alone")
    gcal.connect_to(config, FIVE[TASKS], TASKS)
    assert diya_connectors.read_token(config, TASKS) == "tasks-alone" and diya_connectors.read_granted(config, TASKS) == [FIVE[TASKS]] and diya_connectors.read_together(config, TASKS) is None
    assert diya_connectors.read_together(config, CAL) == sorted(FIVE.values())  # the others still are


def test_forgetting_googles_app_disconnects_every_google_card_calendar_too(config, monkeypatch):
    signs_in(monkeypatch, list(FIVE.values()))
    gcal.connect_all(config, scopes_of_real_cards(config))
    config = dataclasses.replace(config, google_client_id="", google_client_secret="")
    gcal.save_client(config, {"client_id": "1234567890-abc.apps.googleusercontent.com", "client_secret": "secret-1234"})
    assert gcal.clear_client(config) is True
    assert not any(diya_connectors.is_connected(config, name) for name in FIVE)


# ---- the permissions page and the route ---------------------------------------------------------------------------------------------

@pytest.fixture
def client(config):
    agent = diya.Agent(config, client=FakeClient())
    return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")


def permissions(client):
    return {item["name"]: item for item in client.get("/api/permissions").json()["connectors"]}


def test_the_route_connects_the_cards_and_says_which_were_left_out(client, config, monkeypatch):
    signs_in(monkeypatch, [FIVE[CAL], FIVE[MAIL], FIVE[TASKS]])
    answer = client.post("/api/connections/connect-google")
    body = answer.json()
    assert answer.status_code == 200 and sorted(body["connected"]) == ["Gmail", "Google Calendar", "Google Tasks"]
    assert sorted(body["left_out"]) == ["Google Calendar (add events)", "Google Drive and Docs (new things)"]
    state = {c["name"]: c["connected"] for c in body["connectors"]}
    assert state[CAL] and state[MAIL] and state[TASKS] and not state[EDIT] and not state[DRIVE]
    assert "shared-refresh" not in answer.text  # a token is never sent back


def test_the_route_refuses_with_the_reason_and_stores_nothing(client, config, monkeypatch):
    def refuse(config, scope, open_browser):
        raise ConnectorError("Google reported: access_denied")

    monkeypatch.setattr(gcal, "_sign_in", refuse)
    answer = client.post("/api/connections/connect-google")
    assert answer.status_code == 422 and "access_denied" in answer.json()["detail"]
    assert not any(diya_connectors.is_connected(config, name) for name in FIVE)
    assert client.get("/api/connections/connect-google").status_code == 405


def test_without_google_set_up_the_route_says_so(tmp_path, config):
    config = dataclasses.replace(config, google_client_id="", google_client_secret="")
    agent = diya.Agent(config, client=FakeClient())
    answer = TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost").post("/api/connections/connect-google")
    assert answer.status_code == 422 and "not set up yet" in answer.json()["detail"]


def test_the_permissions_page_compares_what_google_granted_with_the_whole_sign_in_not_one_card(client, config, monkeypatch):
    signs_in(monkeypatch, list(FIVE.values()))
    client.post("/api/connections/connect-google")
    item = permissions(client)[TASKS]
    assert item["together"] is True and item["granted_matches"] is True and sorted(item["granted"]) == sorted(FIVE.values())
    assert set(item) >= {"together", "granted", "granted_matches"} and "shared-refresh" not in json.dumps(item)
    # Google granting something the sign-in never asked for is still flagged
    diya_connectors.store_granted(config, TASKS, " ".join(FIVE.values()) + " https://www.googleapis.com/auth/drive")
    assert permissions(client)[TASKS]["granted_matches"] is False
    # a card connected on its own is compared with its own permission, as before
    diya_connectors.disconnect(config, EDIT)
    diya_connectors.store_token(config, EDIT, "alone")
    diya_connectors.store_granted(config, EDIT, FIVE[EDIT])
    alone = permissions(client)[EDIT]
    assert alone["together"] is False and alone["granted_matches"] is True


# ---- the page ---------------------------------------------------------------------------------------------------------------------

def test_the_button_its_same_origin_route_and_its_words_exist():
    page = (ROOT / "frontend" / "app" / "connections" / "page.js").read_text(encoding="utf-8")
    route = ROOT / "frontend" / "app" / "api" / "connections" / "connect-google" / "route.js"
    assert route.exists() and "'/api/connections/connect-google'" in route.read_text(encoding="utf-8") and "force-dynamic" in route.read_text(encoding="utf-8")
    assert "/api/connections/connect-google" in page and "Connect all Google" in page and "Waiting for your browser" in page
    names = set(re.findall(r"'(google_[a-z_]+)'", page.split("GOOGLE_CARDS", 1)[1].split("]", 1)[0]))
    assert names == set(FIVE)  # the page's list of Google's cards is the registry's
