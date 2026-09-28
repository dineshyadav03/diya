"""Google Calendar (docs/CONNECTORS_DESIGN.md, unit C3): diya_google_calendar.py, Diya's first OAuth
connector. No test here ever reaches the real Google, and none opens a real browser: `httpx.post`/
`.get` are faked, and `connect()`'s own `open_browser` parameter is replaced with a stand-in that
plays the part of "the owner clicking through the consent screen" by making a REAL local HTTP request
to the loopback server `connect()` itself started, on the port it was actually given -- everything
downstream of that is the real code, on a real (if tiny) local socket.

What this proves: the loopback server catches exactly one redirect and returns its query, and reports
a plain, readable error rather than hanging forever if nothing ever arrives; the authorization URL
carries the right client id, redirect and scope; a mismatched state, an error from Google, or a
missing code each refuse cleanly and store nothing; a successful exchange stores the refresh token,
under the same per-connector file every other connector uses; and the events tool reads it back fresh
on every call, never once at start-up, and never crashes on a Google failure or a missing connection.
"""
import dataclasses
import threading
import types
import urllib.parse

import httpx
import pytest

import diya_config
import diya_connectors
import diya_google_calendar as gcal
from diya_connectors import ConnectorError


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        connector_tokens_dir=str(tmp_path / "tokens"),
        connectors_log_path=str(tmp_path / "connectors.log"),
        google_client_id="a-client-id",
        google_client_secret="a-client-secret",
    )


def fake_response(status_code=200, body=None):
    return types.SimpleNamespace(status_code=status_code, json=lambda: body if body is not None else {})


def fake_post(monkeypatch, response=None, raises=None):
    calls = []

    def fake(url, data=None, timeout=None):
        calls.append((url, data))
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(gcal.httpx, "post", fake)
    return calls


def clicked_through(query_extra=None, delay=0.0):
    """A stand-in for webbrowser.open: instead of opening a real browser, it reads the redirect_uri
    and state straight out of the URL connect() built, and makes one real HTTP GET to the loopback
    server connect() is -- by the time this runs -- already waiting on, exactly as Google's own
    redirect would. `query_extra` overrides or removes ('code' or 'state' set to None) query params,
    to simulate an error, a missing code, or a mismatched state."""

    def open_browser(url):
        parsed = urllib.parse.urlsplit(url)
        params = dict(urllib.parse.parse_qsl(parsed.query))
        query = {"code": "a-real-looking-code", "state": params["state"]}
        if query_extra:
            query.update(query_extra)
        query = {k: v for k, v in query.items() if v is not None}

        def visit():
            httpx.get(params["redirect_uri"], params=query, timeout=5)

        threading.Timer(delay, visit).start()

    return open_browser


# --- the loopback server itself ---------------------------------------------------------------------

def test_wait_for_redirect_returns_the_query_it_was_sent():
    port, wait = gcal._wait_for_redirect(timeout=5)
    threading.Timer(0, lambda: httpx.get(f"http://127.0.0.1:{port}/", params={"code": "abc", "state": "xyz"})).start()
    assert wait() == {"code": "abc", "state": "xyz"}


def test_wait_for_redirect_times_out_with_a_readable_error_if_nothing_arrives():
    _port, wait = gcal._wait_for_redirect(timeout=0.3)
    with pytest.raises(ConnectorError, match="timed out or was cancelled"):
        wait()


# --- the authorization URL --------------------------------------------------------------------------

def test_authorization_url_carries_the_client_redirect_scope_and_state():
    url = gcal._authorization_url("a-client-id", "http://127.0.0.1:5000", "a-state")
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert params["client_id"] == "a-client-id"
    assert params["redirect_uri"] == "http://127.0.0.1:5000"
    assert params["scope"] == gcal.SCOPE
    assert params["state"] == "a-state"
    assert params["access_type"] == "offline"  # needed to ever get a refresh token at all


# --- connect(): the whole flow -----------------------------------------------------------------------

def test_connect_refuses_with_no_client_credentials_configured(config):
    config = dataclasses.replace(config, google_client_id="", google_client_secret="")
    with pytest.raises(ConnectorError, match="DIYA_GOOGLE_CLIENT_ID"):
        gcal.connect(config, open_browser=lambda url: None)
    assert not diya_connectors.is_connected(config, "google_calendar")


def test_connect_stores_the_refresh_token_on_a_successful_exchange(config, monkeypatch):
    fake_post(monkeypatch, fake_response(200, {"refresh_token": "a-refresh-token", "access_token": "x"}))
    gcal.connect(config, open_browser=clicked_through())
    assert diya_connectors.read_token(config, "google_calendar") == "a-refresh-token"


def test_connect_sends_the_code_and_redirect_uri_it_actually_used(config, monkeypatch):
    calls = fake_post(monkeypatch, fake_response(200, {"refresh_token": "rt"}))
    gcal.connect(config, open_browser=clicked_through())
    (_url, data) = calls[0]
    assert data["code"] == "a-real-looking-code"
    assert data["redirect_uri"].startswith("http://127.0.0.1:")
    assert data["grant_type"] == "authorization_code"


def test_connect_refuses_a_mismatched_state_and_stores_nothing(config, monkeypatch):
    fake_post(monkeypatch, fake_response(200, {"refresh_token": "rt"}))
    with pytest.raises(ConnectorError, match="wasn't for this request"):
        gcal.connect(config, open_browser=clicked_through(query_extra={"state": "the-wrong-state"}))
    assert not diya_connectors.is_connected(config, "google_calendar")


def test_connect_reports_an_error_google_sends_back(config, monkeypatch):
    with pytest.raises(ConnectorError, match="access_denied"):
        gcal.connect(config, open_browser=clicked_through(query_extra={"error": "access_denied", "code": None}))
    assert not diya_connectors.is_connected(config, "google_calendar")


def test_connect_refuses_a_redirect_with_no_code(config, monkeypatch):
    with pytest.raises(ConnectorError, match="no authorization code"):
        gcal.connect(config, open_browser=clicked_through(query_extra={"code": None}))
    assert not diya_connectors.is_connected(config, "google_calendar")


def test_connect_refuses_if_google_never_issues_a_refresh_token(config, monkeypatch):
    fake_post(monkeypatch, fake_response(200, {"access_token": "x"}))  # no refresh_token
    with pytest.raises(ConnectorError, match="did not return a refresh token"):
        gcal.connect(config, open_browser=clicked_through())
    assert not diya_connectors.is_connected(config, "google_calendar")


def test_connect_reports_google_refusing_the_exchange(config, monkeypatch):
    fake_post(monkeypatch, fake_response(400))
    with pytest.raises(ConnectorError, match="400"):
        gcal.connect(config, open_browser=clicked_through())
    assert not diya_connectors.is_connected(config, "google_calendar")


def test_connect_times_out_if_the_owner_never_finishes(config, monkeypatch):
    monkeypatch.setattr(gcal, "CALLBACK_TIMEOUT", 0.3)
    with pytest.raises(ConnectorError, match="timed out or was cancelled"):
        gcal.connect(config, open_browser=lambda url: None)  # "opens" nothing; nobody ever visits
    assert not diya_connectors.is_connected(config, "google_calendar")


# --- list_events: reading it back --------------------------------------------------------------------

def test_list_events_says_so_when_not_connected(config):
    assert gcal.list_events(config)() == "Google Calendar is not connected."


def test_list_events_refreshes_the_token_then_lists(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    post_calls = fake_post(monkeypatch, fake_response(200, {"access_token": "fresh-access-token"}))

    def fake_get(url, headers=None, params=None, timeout=None):
        assert headers["Authorization"] == "Bearer fresh-access-token"
        return fake_response(200, {"items": [
            {"summary": "Dentist", "start": {"dateTime": "2026-10-01T15:00:00Z"}},
            {"summary": "All-day thing", "start": {"date": "2026-10-02"}},
        ]})

    monkeypatch.setattr(gcal.httpx, "get", fake_get)
    result = gcal.list_events(config)()
    assert result == "Dentist (2026-10-01T15:00:00Z)\nAll-day thing (2026-10-02)"
    assert post_calls[0][1]["grant_type"] == "refresh_token"
    assert post_calls[0][1]["refresh_token"] == "a-refresh-token"


def test_list_events_says_so_when_there_are_none(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    fake_post(monkeypatch, fake_response(200, {"access_token": "x"}))
    monkeypatch.setattr(gcal.httpx, "get", lambda *a, **k: fake_response(200, {"items": []}))
    assert gcal.list_events(config)() == "No upcoming events."


def test_list_events_treats_a_refresh_failure_as_not_connected(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-stale-refresh-token")
    fake_post(monkeypatch, fake_response(401))
    assert gcal.list_events(config)() == "Google Calendar is not connected."


def test_list_events_reports_a_network_failure_on_the_events_call_without_crashing(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    fake_post(monkeypatch, fake_response(200, {"access_token": "x"}))

    def raise_it(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(gcal.httpx, "get", raise_it)
    assert "Couldn't reach Google Calendar" in gcal.list_events(config)()


def test_list_events_reports_a_bad_status_from_the_events_call(config, monkeypatch):
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    fake_post(monkeypatch, fake_response(200, {"access_token": "x"}))
    monkeypatch.setattr(gcal.httpx, "get", lambda *a, **k: fake_response(500))
    assert "HTTP 500" in gcal.list_events(config)()
