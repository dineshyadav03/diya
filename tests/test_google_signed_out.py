"""When Google itself signs Diya out (DIYA-065), added 2026-10-25.

You can remove Diya at myaccount.google.com/permissions, or a sign-in can run out; Google then answers every refresh with invalid_grant. Before this, every job kept asking Google and every tool said only
"not connected". What this proves, with the token server replaced by a stand-in: an invalid_grant answer marks the connection signed out and returns no token; after that nothing asks Google again (the stand-in
is not visited) until the person connects again; any other failure (a network fault, a busy Google, an HTTP 500) is not taken for a sign-out; a connection made again, or disconnected and made again, is
usable at once; the mark holds a fingerprint and a time and never the token; every Google reader says in words that Google signed Diya out and where to put it right, while a connection that was never made still
says "is not connected"; the permissions answer carries the state; and the Connections page shows it and offers "Connect again". It does not prove how the real Google words it.
"""
import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_mail as gmail
import diya_google_write as gw
import diya_web
from diya_connectors import ConnectorError
from fakes import FakeClient

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("google_calendar", "google_tasks", "google_mail")


class TokenServer:
    def __init__(self, monkeypatch):
        self.visits, self.failure = 0, None
        monkeypatch.setattr(gcal, "_exchange", self)

    def __call__(self, data):
        self.visits += 1
        if self.failure:
            raise ConnectorError(self.failure)
        return {"access_token": f"access-{self.visits}", "expires_in": 3600}


@pytest.fixture
def config(tmp_path):
    cfg = dataclasses.replace(
        diya_config.load_config(), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "log"), google_client_id="id", google_client_secret="secret", protect_secrets=False,
    )
    for name in NAMES:
        diya_connectors.store_token(cfg, name, f"refresh-{name}")
    gcal.forget_access_tokens()
    return cfg


REVOKED = "Google answered with HTTP 400 (invalid_grant: Token has been expired or revoked.)"


def test_an_invalid_grant_marks_the_connection_signed_out_and_nothing_asks_google_again(config, monkeypatch):
    server = TokenServer(monkeypatch)
    server.failure = REVOKED
    assert gcal.access_token(config, "google_calendar") is None and diya_connectors.signed_out(config, "google_calendar")
    server.failure = None
    for _ in range(5):
        assert gcal.access_token(config, "google_calendar") is None
    assert server.visits == 1  # the five later calls did not go to Google
    assert not diya_connectors.signed_out(config, "google_tasks")  # another connection is not touched


@pytest.mark.parametrize("failure", ["couldn't reach Google: timed out", "Google answered with HTTP 500", "Google answered with HTTP 429", "Google answered with HTTP 400 (invalid_client: Unauthorized)"])
def test_any_other_failure_is_not_taken_for_a_sign_out(config, monkeypatch, failure):
    server = TokenServer(monkeypatch)
    server.failure = failure
    assert gcal.access_token(config, "google_calendar") is None
    assert not diya_connectors.signed_out(config, "google_calendar")
    server.failure = None
    assert gcal.access_token(config, "google_calendar") == "access-2"  # asked again, and it worked


def test_a_connection_made_again_or_disconnected_and_made_again_is_usable_at_once(config, monkeypatch):
    server = TokenServer(monkeypatch)
    server.failure = REVOKED
    gcal.access_token(config, "google_calendar")
    server.failure = None
    diya_connectors.store_token(config, "google_calendar", "a-brand-new-refresh-token")  # connecting again gives another token
    assert not diya_connectors.signed_out(config, "google_calendar") and gcal.access_token(config, "google_calendar") == "access-2"
    server.failure = REVOKED
    gcal.forget_access_tokens()
    server.visits = 0
    diya_connectors.store_token(config, "google_tasks", "same-token")
    assert gcal.access_token(config, "google_tasks") is None and diya_connectors.signed_out(config, "google_tasks")
    diya_connectors.disconnect(config, "google_tasks")
    diya_connectors.store_token(config, "google_tasks", "same-token")  # even the very same words, after a disconnect, are a fresh start
    assert not diya_connectors.signed_out(config, "google_tasks")


def test_the_mark_holds_a_fingerprint_and_a_time_and_never_the_token(config, monkeypatch):
    server = TokenServer(monkeypatch)
    server.failure = REVOKED
    gcal.access_token(config, "google_calendar")
    marker = Path(diya_connectors._signed_out_path(config, "google_calendar"))
    text = marker.read_text(encoding="utf-8")
    assert "refresh-google_calendar" not in text and len(text.splitlines()) == 2 and len(text.splitlines()[0]) == 16


def test_every_reader_says_that_google_signed_diya_out_and_where_to_put_it_right(config, monkeypatch):
    server = TokenServer(monkeypatch)
    server.failure = REVOKED
    for name in NAMES:
        gcal.access_token(config, name)
    sentences = [
        gcal.list_events(config)(), gcal.events_between(config, gcal.datetime.now(gcal.timezone.utc), gcal.datetime.now(gcal.timezone.utc))[1], gw.google_tasks_list(config)(),
    ]
    try:
        gmail.read_mail(config, "mail from bob")
    except gmail.MailError as exc:
        sentences.append(str(exc))
    for sentence in sentences:
        assert "signed Diya out" in sentence and "Connections page" in sentence, sentence
    assert "not connected" not in " ".join(sentences)


def test_a_connection_that_was_never_made_still_says_it_is_not_connected(tmp_path, monkeypatch):
    cfg = dataclasses.replace(diya_config.load_config(), connector_tokens_dir=str(tmp_path / "none"), connectors_log_path=str(tmp_path / "log"))
    TokenServer(monkeypatch)
    assert gcal.list_events(cfg)() == "Google Calendar is not connected." and gw.google_tasks_list(cfg)() == "Google Tasks is not connected."


def test_the_permissions_answer_carries_the_state_and_the_page_shows_it_with_a_way_back(config, tmp_path, monkeypatch):
    server = TokenServer(monkeypatch)
    cfg = dataclasses.replace(config, db_path=str(tmp_path / "p.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)

    class Quiet:
        def transcribe(self, path):
            return ""

    client = TestClient(diya_web.create_app(cfg, diya.Agent(cfg, client=FakeClient()), Quiet()), base_url="https://localhost")
    found = {c["name"]: c for c in client.get("/api/permissions").json()["connectors"]}
    assert found["google_calendar"]["signed_out"] is False and found["home_assistant"]["signed_out"] is False
    server.failure = REVOKED
    gcal.access_token(cfg, "google_calendar")
    found = {c["name"]: c for c in client.get("/api/permissions").json()["connectors"]}
    assert found["google_calendar"]["signed_out"] is True and found["google_tasks"]["signed_out"] is False
    page = (ROOT / "frontend" / "app" / "connections" / "page.js").read_text(encoding="utf-8")
    assert "Signed out by Google" in page and "Connect again" in page and "permissions[connector.name].signed_out" in page and "connectOAuth(connector)" in page
