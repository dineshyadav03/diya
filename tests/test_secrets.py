"""Secrets at rest, PKCE and revoking on disconnect (diya_secrets.py, docs/SECRETS_DESIGN.md), added 2026-10-18.

What this proves, with a reversible stand-in for the operating system's encryption so that the answer does not depend on the machine (plus one real Windows round trip that is skipped elsewhere): a
sign-in and Google's client secret are written protected and read back; a file from before (plain text) is still read and is rewritten protected once; a protected file that cannot be decrypted here
means "not connected", never an error; with protection off nothing changes; the sign-in sends Google a PKCE challenge and later the matching verifier; disconnecting a Google card takes the permission
back at Google only when it is the last Google card connected, and never fails to disconnect whatever Google does.
It does not prove that Google accepts the PKCE exchange or the revoke: nobody has signed in through the real one yet.
"""
import base64
import dataclasses
import hashlib
import json
import sys
import urllib.parse

import httpx
import pytest

import diya_config
import diya_connector_tools
import diya_connectors
import diya_google_calendar as gcal
import diya_secrets
from test_google_calendar import clicked_through, fake_post, fake_response  # noqa: F401


class Reversible:
    """Stands in for DPAPI: scrambles bytes reversibly, and refuses what it did not scramble."""

    def protect(self, data):
        return b"SCRAMBLED:" + data[::-1]

    def unprotect(self, data):
        if not data.startswith(b"SCRAMBLED:"):
            raise OSError("not ours")
        return data[len(b"SCRAMBLED:"):][::-1]


@pytest.fixture
def stand_in(monkeypatch):
    monkeypatch.setattr(diya_secrets, "available", lambda: True)
    monkeypatch.setattr(diya_secrets, "_backend", Reversible())


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config({}), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"), google_client_id="", google_client_secret="", protect_secrets=True,
    )


def raw(config, name):
    with open(f"{config.connector_tokens_dir}/{name}.token", encoding="utf-8") as f:
        return f.read().strip()


# ---- the protection itself ---------------------------------------------------------------------------------------------------------------

def test_a_protected_secret_is_marked_unreadable_as_it_is_and_comes_back(stand_in):
    stored = diya_secrets.protect("1//refresh-token-abc")
    assert stored.startswith(diya_secrets.PREFIX) and "refresh-token-abc" not in stored and diya_secrets.is_protected(stored)
    assert diya_secrets.unprotect(stored) == "1//refresh-token-abc"


def test_a_plain_value_is_read_as_it_is_and_nothing_else_is(stand_in):
    assert diya_secrets.unprotect("plain-token") == "plain-token"
    assert diya_secrets.unprotect(None) is None and diya_secrets.unprotect(5) is None


@pytest.mark.parametrize("damaged", ["dpapi1:", "dpapi1:%%%not base64%%%", "dpapi1:" + base64.b64encode(b"not scrambled by us").decode()])
def test_a_protected_value_that_cannot_be_decrypted_here_is_none_not_an_error(stand_in, damaged):
    assert diya_secrets.unprotect(damaged) is None


def test_with_protection_off_or_no_system_support_the_text_is_kept_as_it_was(monkeypatch):
    monkeypatch.setattr(diya_secrets, "available", lambda: True)
    assert diya_secrets.protect("t", enabled=False) == "t"
    monkeypatch.setattr(diya_secrets, "available", lambda: False)
    assert diya_secrets.protect("t") == "t" and diya_secrets.unprotect("dpapi1:AAAA") is None  # a protected value cannot be read where nothing can decrypt it


def test_a_system_that_fails_to_protect_stores_the_secret_as_before_rather_than_losing_it(monkeypatch):
    class Broken(Reversible):
        def protect(self, data):
            raise OSError("no")

    monkeypatch.setattr(diya_secrets, "available", lambda: True)
    monkeypatch.setattr(diya_secrets, "_backend", Broken())
    assert diya_secrets.protect("t") == "t"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI")
def test_the_real_windows_encryption_round_trips_and_differs_from_the_text():
    stored = diya_secrets.protect("1//a-real-looking-refresh-token")
    assert stored.startswith("dpapi1:") and "real-looking" not in stored
    assert diya_secrets.unprotect(stored) == "1//a-real-looking-refresh-token"
    assert diya_secrets.unprotect("dpapi1:AAAA") is None


# ---- the connector files ------------------------------------------------------------------------------------------------------------------

def test_a_sign_in_is_written_protected_and_read_back(stand_in, config):
    diya_connectors.store_token(config, "demo", "the-token")
    assert diya_secrets.is_protected(raw(config, "demo")) and "the-token" not in raw(config, "demo")
    assert diya_connectors.read_token(config, "demo") == "the-token" and diya_connectors.is_connected(config, "demo")


def test_a_sign_in_from_before_is_still_read_and_is_rewritten_protected_once(stand_in, config):
    diya_connectors.store_token(dataclasses.replace(config, protect_secrets=False), "demo", "old-plain-token")
    assert raw(config, "demo") == "old-plain-token"
    assert diya_connectors.read_token(config, "demo") == "old-plain-token"
    assert diya_secrets.is_protected(raw(config, "demo")) and diya_connectors.read_token(config, "demo") == "old-plain-token"


def test_with_protection_off_the_file_stays_plain_and_is_not_rewritten(stand_in, config):
    off = dataclasses.replace(config, protect_secrets=False)
    diya_connectors.store_token(off, "demo", "t")
    assert raw(off, "demo") == "t" and diya_connectors.read_token(off, "demo") == "t" and raw(off, "demo") == "t"


def test_a_protected_file_that_cannot_be_decrypted_here_counts_as_not_connected(stand_in, config):
    diya_connectors.store_token(config, "demo", "t")
    with open(f"{config.connector_tokens_dir}/demo.token", "w", encoding="utf-8") as f:
        f.write("dpapi1:" + base64.b64encode(b"from another windows user").decode() + "\n")
    assert diya_connectors.read_token(config, "demo") is None and not diya_connectors.is_connected(config, "demo")


def test_a_folder_that_cannot_be_written_still_gives_its_token(stand_in, config, monkeypatch):
    diya_connectors.store_token(dataclasses.replace(config, protect_secrets=False), "demo", "t")
    monkeypatch.setattr(diya_connectors, "_write_token", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only")))
    assert diya_connectors.read_token(config, "demo") == "t"


def test_googles_client_secret_is_protected_too_and_a_plain_file_is_upgraded(stand_in, config):
    client = {"client_id": "123456789012-abcdefghijklmnop.apps.googleusercontent.com", "client_secret": "GOCSPX-abcDEF_123-xyz9876543210"}
    gcal.save_client(config, client)
    path = f"{config.connector_tokens_dir}/google_calendar.client"
    stored = open(path, encoding="utf-8").read().strip()
    assert diya_secrets.is_protected(stored) and client["client_secret"] not in stored
    assert gcal._client_credentials(config) == (client["client_id"], client["client_secret"])
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(client) + "\n")  # as an older version wrote it
    assert gcal._client_credentials(config) == (client["client_id"], client["client_secret"])
    assert diya_secrets.is_protected(open(path, encoding="utf-8").read().strip())
    assert gcal.client_state(config) == "file"


def test_the_flag_is_on_by_default_and_off_with_the_setting():
    assert diya_config.load_config({}).protect_secrets is True
    assert diya_config.load_config({"DIYA_PROTECT_SECRETS": "0"}).protect_secrets is False


# ---- PKCE ---------------------------------------------------------------------------------------------------------------------------------

def test_a_pkce_pair_is_a_verifier_and_its_s256_challenge_and_new_each_time():
    verifier, challenge = gcal.pkce_pair()
    assert 43 <= len(verifier) <= 128 and challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert gcal.pkce_pair()[0] != verifier


def test_the_authorization_url_carries_the_challenge_only_when_given():
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(gcal._authorization_url("c", "http://127.0.0.1:1", "s", gcal.SCOPE, "abc")).query))
    assert params["code_challenge"] == "abc" and params["code_challenge_method"] == "S256"
    assert "code_challenge" not in dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(gcal._authorization_url("c", "http://127.0.0.1:1", "s")).query))


def test_the_sign_in_sends_google_the_challenge_first_and_the_matching_verifier_with_the_code(config, monkeypatch):
    config = dataclasses.replace(config, google_client_id="a-client-id", google_client_secret="a-client-secret", protect_secrets=False)
    seen = []
    inner = clicked_through()

    def browser(url):
        seen.append(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)))
        return inner(url)

    calls = fake_post(monkeypatch, fake_response(200, {"refresh_token": "rt"}))
    gcal.connect(config, open_browser=browser)
    challenge = seen[0]["code_challenge"]
    (_, data) = calls[0]
    assert seen[0]["code_challenge_method"] == "S256" and data["code_verifier"]
    assert base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode() == challenge


# ---- revoking at Google on disconnect ----------------------------------------------------------------------------------------------------

def connector(config, name):
    return diya_connectors.by_name(diya_connector_tools.real_connectors(config), name)


def revoke_stand_in(monkeypatch, status=200, raises=None):
    sent = []

    def post(url, data=None, timeout=None):
        sent.append((url, data))
        if raises is not None:
            raise raises
        return fake_response(status, {})

    monkeypatch.setattr(gcal.httpx, "post", post)
    return sent


def test_disconnecting_the_last_google_card_tells_google_to_forget_the_permission(config, monkeypatch):
    sent = revoke_stand_in(monkeypatch)
    diya_connectors.store_token(config, "google_tasks", "rt-tasks")
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "google_tasks")) is True
    assert sent == [(gcal.REVOKE_URL, {"token": "rt-tasks"})] and not diya_connectors.is_connected(config, "google_tasks")


def test_while_another_google_card_is_connected_nothing_is_revoked_so_it_is_not_signed_out(config, monkeypatch):
    sent = revoke_stand_in(monkeypatch)
    diya_connectors.store_token(config, "google_tasks", "rt-tasks")
    diya_connectors.store_token(config, "google_mail", "rt-mail")
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "google_tasks")) is None
    assert sent == [] and not diya_connectors.is_connected(config, "google_tasks") and diya_connectors.is_connected(config, "google_mail")
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "google_mail")) is True and len(sent) == 1  # the last one does


@pytest.mark.parametrize("status", [400, 401, 500])
def test_google_not_agreeing_is_reported_and_the_sign_in_is_removed_anyway(config, monkeypatch, status):
    revoke_stand_in(monkeypatch, status)
    diya_connectors.store_token(config, "google_calendar", "rt")
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "google_calendar")) is False
    assert not diya_connectors.is_connected(config, "google_calendar")


@pytest.mark.parametrize("error", [httpx.ConnectError("down"), httpx.ReadTimeout("slow"), RuntimeError("anything")])
def test_google_being_unreachable_never_stops_the_disconnect(config, monkeypatch, error):
    revoke_stand_in(monkeypatch, raises=error)
    diya_connectors.store_token(config, "google_drive_files", "rt")
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "google_drive_files")) is False
    assert not diya_connectors.is_connected(config, "google_drive_files")


def test_a_connector_with_no_revoke_step_just_disconnects(config, monkeypatch):
    sent = revoke_stand_in(monkeypatch)
    diya_connectors.store_token(config, "todoist", "t")
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "todoist")) is None
    assert sent == [] and not diya_connectors.is_connected(config, "todoist")


def test_disconnecting_something_never_connected_is_fine(config, monkeypatch):
    sent = revoke_stand_in(monkeypatch)
    assert diya_connectors.revoke_and_disconnect(config, connector(config, "google_tasks")) is None and sent == []


def test_the_disconnect_route_says_what_happened_at_google(config, monkeypatch):
    from fastapi.testclient import TestClient

    import diya
    import diya_web
    from fakes import FakeClient

    config = dataclasses.replace(config, db_path=config.connector_tokens_dir + "-x.db", profile_path=config.connector_tokens_dir + "-p.txt", require_token=False)
    client = TestClient(diya_web.create_app(config, diya.Agent(config, client=FakeClient()), object()), base_url="https://localhost")
    sent = revoke_stand_in(monkeypatch)
    diya_connectors.store_token(config, "google_tasks", "rt")
    body = client.post("/api/connections/google_tasks/disconnect").json()
    assert body["revoked"] is True and len(sent) == 1
    assert client.post("/api/connections/google_tasks/disconnect").json()["revoked"] is None  # again: nothing connected, nothing to do
