"""Keeping Google's access tokens safe and few (diya_google_calendar.access_token; DIYA-064), added 2026-10-25.

Before this, every Google request began with its own trip to Google's token server: one question was one trip, an approved write with its read-back was three. What this proves, with the token server replaced by
a stand-in that counts its visits: a token with time left is reused; one with under a minute left is refreshed before it is used, not after Google refuses it; twelve callers at the same moment cause one
refresh and all get the same token; two connections, or a connection made again, never share a token; a refusal is not remembered and a token that has run out is never handed out after one; a missing or odd
lifetime from Google gets a short one; no connection means no visit at all; and a refresh never rewrites the stored refresh token (so there is no stored state for two jobs to corrupt), even if Google sends one.
It does not prove how the real token server behaves.
"""
import dataclasses
import threading
import time

import pytest

import diya_config
import diya_connectors
import diya_google_calendar as gcal
from diya_connectors import ConnectorError


class TokenServer:
    def __init__(self, monkeypatch, *, lifetime=3600, delay=0.0):
        self.visits, self.lifetime, self.delay, self.refuse, self.extra = 0, lifetime, delay, False, {}
        self.now = 1000.0
        monkeypatch.setattr(gcal, "_exchange", self)
        monkeypatch.setattr(gcal, "_clock", lambda: self.now)

    def __call__(self, data):
        self.visits += 1
        if self.delay:
            time.sleep(self.delay)
        if self.refuse:
            raise ConnectorError("Google answered with HTTP 503")  # a busy Google: not a revoked sign-in (that one is remembered; tests/test_google_signed_out.py)
        answer = {"access_token": f"access-{self.visits}", "token_type": "Bearer"}
        if self.lifetime is not None:
            answer["expires_in"] = self.lifetime
        answer.update(self.extra)
        return answer


@pytest.fixture
def config(tmp_path):
    cfg = dataclasses.replace(diya_config.load_config(), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "log"), google_client_id="id", google_client_secret="secret")
    diya_connectors.store_token(cfg, "google_calendar", "refresh-one")
    diya_connectors.store_token(cfg, "google_tasks", "refresh-two")
    gcal.forget_access_tokens()
    return cfg


def test_a_token_with_time_left_is_reused(config, monkeypatch):
    server = TokenServer(monkeypatch)
    assert gcal.access_token(config, "google_calendar") == "access-1"
    server.now += 3000
    assert gcal.access_token(config, "google_calendar") == "access-1" and server.visits == 1


def test_a_token_with_under_a_minute_left_is_refreshed_before_it_is_used(config, monkeypatch):
    server = TokenServer(monkeypatch, lifetime=600)
    assert gcal.access_token(config, "google_calendar") == "access-1"
    server.now += 600 - gcal.EARLY_SECONDS - 1
    assert gcal.access_token(config, "google_calendar") == "access-1"  # a second more than a minute left
    server.now += 2
    assert gcal.access_token(config, "google_calendar") == "access-2" and server.visits == 2


def test_twelve_callers_at_once_cause_one_refresh_and_all_get_the_same_token(config, monkeypatch):
    server = TokenServer(monkeypatch, delay=0.2)
    got = []
    threads = [threading.Thread(target=lambda: got.append(gcal.access_token(config, "google_calendar"))) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert server.visits == 1 and got == ["access-1"] * 12


def test_two_connections_never_share_a_token(config, monkeypatch):
    server = TokenServer(monkeypatch)
    assert gcal.access_token(config, "google_calendar") == "access-1"
    assert gcal.access_token(config, "google_tasks") == "access-2" and server.visits == 2


def test_a_connection_made_again_is_never_given_the_old_token(config, monkeypatch):
    server = TokenServer(monkeypatch)
    assert gcal.access_token(config, "google_calendar") == "access-1"
    diya_connectors.store_token(config, "google_calendar", "refresh-after-reconnecting")
    assert gcal.access_token(config, "google_calendar") == "access-2" and server.visits == 2


def test_a_refusal_is_not_remembered_and_a_run_out_token_is_not_handed_out_after_one(config, monkeypatch):
    server = TokenServer(monkeypatch, lifetime=300)
    server.refuse = True
    assert gcal.access_token(config, "google_calendar") is None
    server.refuse = False
    assert gcal.access_token(config, "google_calendar") == "access-2"  # it asked again
    server.now += 1000
    server.refuse = True
    assert gcal.access_token(config, "google_calendar") is None  # run out, and Google now refuses: nothing stale is served
    assert server.visits == 3


@pytest.mark.parametrize("odd", [None, 0, -5, True, "3600", 999999, float("nan")])
def test_a_missing_or_odd_lifetime_gets_a_short_one(config, monkeypatch, odd):
    server = TokenServer(monkeypatch, lifetime=odd)
    gcal.access_token(config, "google_calendar")
    server.now += gcal.DEFAULT_LIFETIME - gcal.EARLY_SECONDS + 1
    gcal.access_token(config, "google_calendar")
    assert server.visits == 2


def test_no_connection_means_no_visit(config, monkeypatch):
    server = TokenServer(monkeypatch)
    diya_connectors.disconnect(config, "google_calendar")
    assert gcal.access_token(config, "google_calendar") is None and server.visits == 0


def test_a_refresh_never_rewrites_the_stored_refresh_token_even_if_google_sends_one(config, monkeypatch):
    server = TokenServer(monkeypatch, delay=0.05)
    server.extra = {"refresh_token": "a-different-refresh-token", "scope": "x"}
    threads = [threading.Thread(target=lambda: gcal.access_token(config, "google_tasks")) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert diya_connectors.read_token(config, "google_tasks") == "refresh-two"


def test_an_answer_with_no_token_in_it_is_a_refusal(config, monkeypatch):
    server = TokenServer(monkeypatch)
    server.extra = {"access_token": ""}
    assert gcal.access_token(config, "google_calendar") is None
