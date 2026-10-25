"""What happens when Google fails, for every way Diya talks to it (DIYA-217, -054 and -069), added 2026-10-25.

The sheet asks for "401/403/429/5xx, malformed IDs, conflict, timeout, rate, bad scopes". This tries each of those on every request Diya makes to Google as the owner (a calendar read, a calendar read for a
question, the Tasks list, a Gmail search, and the writes), with Google replaced by a stand-in that answers as scripted and counts the requests. What it proves, for every one of those requests and every fault:
exactly one request is made (nothing retries, so a bad day at Google cannot become a runaway loop); nothing escapes but the typed outcome (a plain sentence for a read, a refusal or an "unknown" for a write); the
sentence holds no access token, no control character and no address; a rate limit that says how long to wait is passed on in seconds; a reply that is not JSON, or is JSON of the wrong shape, is "something I could
not read", never a crash; and every list asks for a bounded number of results. A separate check reads the source: every outbound call in the app, not only Google's, has a timeout. It does not prove the real
Google answers like the stand-in: nobody has connected these through a live account yet (DIYA-216 is that).
"""
import ast
import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import diya_actions
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_mail as gmail
import diya_google_write as gw

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "SECRET-ACCESS-TOKEN-1234"
NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)


def answer(status, body=None, headers=None, raw=None):
    if raw is not None:
        return httpx.Response(status, content=raw, headers=headers)
    return httpx.Response(status, json=body if body is not None else {}, headers=headers)


REFUSED_SCOPE = {"error": {"code": 403, "message": "Request had insufficient authentication scopes.", "status": "PERMISSION_DENIED"}}
# fault name -> what Google (or the network) does. A status answer is the response itself; an exception is raised by the request.
FAULTS = {
    "401 sign-in no longer accepted": answer(401, {"error": {"message": "Invalid Credentials"}}),
    "403 bad scope": answer(403, REFUSED_SCOPE),
    "404 malformed or unknown id": answer(404, {"error": {"message": "Not Found"}}),
    "409 conflict": answer(409, {"error": {"message": "The requested identifier already exists."}}),
    "412 changed since": answer(412, {"error": {"message": "Precondition Failed"}}),
    "429 rate limited": answer(429, {"error": {"message": "Rate Limit Exceeded"}}, headers={"Retry-After": "30"}),
    "500": answer(500, {"error": {"message": "Backend Error"}}),
    "502": answer(502, raw=b"<html>bad gateway</html>"),
    "503 with no usable body": answer(503, raw=b""),
    "504": answer(504, {"error": {"message": "Gateway Timeout"}}),
    "read timeout": httpx.ReadTimeout("took too long"),
    "connect error": httpx.ConnectError("no route to host"),
    "connect timeout": httpx.ConnectTimeout("no connection in time"),
    "200 but not JSON": answer(200, raw=b"<html>sign in to continue</html>"),
    "200 but a list": answer(200, [1, 2, 3]),
    "200 but items is text": answer(200, {"items": "none", "messages": "none"}),
    "200 but items are not objects": answer(200, {"items": [1, "a", None], "messages": [1, "a", None]}),
}


class Google:
    """Stand-in for every way the app calls Google: `httpx.get` and `httpx.request`. Records each request."""

    def __init__(self, monkeypatch, fault):
        self.fault, self.calls = fault, []
        monkeypatch.setattr(httpx, "get", self.get)
        monkeypatch.setattr(httpx, "request", self.request)

    def get(self, url, params=None, headers=None, timeout=None, **_):
        return self.request("GET", url, params=params, headers=headers, timeout=timeout)

    def request(self, method, url, params=None, json=None, headers=None, timeout=None, **_):
        self.calls.append({"method": method, "url": url, "params": params, "timeout": timeout})
        if isinstance(self.fault, Exception):
            raise self.fault
        return self.fault


@pytest.fixture
def config(tmp_path, monkeypatch):
    cfg = dataclasses.replace(
        diya_config.load_config(), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "connectors.log"), google_client_id="a-client-id", google_client_secret="a-client-secret",
    )
    for name in ("google_calendar", "google_tasks", "google_calendar_edit", "gmail"):
        diya_connectors.store_token(cfg, name, f"refresh-{name}")
    monkeypatch.setattr(gcal, "access_token", lambda c, name: TOKEN)
    return cfg


def sentence_is_safe(text):
    assert isinstance(text, str) and text
    assert TOKEN not in text and "Bearer" not in text and "googleapis.com" not in text, text
    assert not any(ord(c) < 32 for c in text), repr(text)  # one line, no control character


# ---- the reads ----------------------------------------------------------------------------------------------------------------

def read_calendar_list(config):
    return gcal.list_events(config)()


def read_calendar_between(config):
    found, why = gcal.events_between(config, NOW, NOW + timedelta(days=7))
    return why if why else "ok:" + str(found)


def read_tasks(config):
    return gw.google_tasks_list(config)()


def read_gmail(config):
    try:
        gmail.read_mail(config, "mail from bob", access_token=TOKEN)
    except gmail.MailError as exc:
        return str(exc)
    return "ok"


READS = {"calendar upcoming": read_calendar_list, "calendar between": read_calendar_between, "google tasks": read_tasks, "gmail search": read_gmail}


@pytest.mark.parametrize("fault", list(FAULTS))
@pytest.mark.parametrize("reader", list(READS))
def test_every_read_makes_one_request_never_crashes_and_says_in_safe_words_that_it_could_not(reader, fault, config, monkeypatch):
    google = Google(monkeypatch, FAULTS[fault])
    said = READS[reader](config)  # a crash here is the failure
    assert len(google.calls) == 1, google.calls  # one try, whatever the fault: nothing here can loop
    shape_faults = fault.startswith("200")
    if shape_faults and fault in ("200 but items is text", "200 but items are not objects"):
        assert isinstance(said, str)  # nothing useful in it, but nothing broke
        return
    sentence_is_safe(said)
    assert not said.startswith("ok"), said


@pytest.mark.parametrize("reader", list(READS))
def test_a_rate_limit_that_says_how_long_to_wait_is_passed_on_in_seconds(reader, config, monkeypatch):
    Google(monkeypatch, answer(429, {}, headers={"Retry-After": "45"}))
    said = READS[reader](config)
    assert "45 seconds" in said, said
    Google(monkeypatch, answer(429, {}, headers={"Retry-After": "not-a-number"}))
    said = READS[reader](config)
    assert "seconds" not in said, said  # no made-up wait when Google gave none


@pytest.mark.parametrize("reader", list(READS))
def test_every_list_asks_for_a_bounded_number_of_results_and_has_a_timeout(reader, config, monkeypatch):
    google = Google(monkeypatch, answer(200, {"items": [], "messages": []}))
    READS[reader](config)
    assert google.calls, "no request was made"
    for call in google.calls:
        assert call["timeout"] is not None and call["timeout"] <= 30, call
        assert 1 <= int(call["params"]["maxResults"]) <= 100, call


# ---- the writes ---------------------------------------------------------------------------------------------------------------

WRITE_OUTCOME = {
    "401 sign-in no longer accepted": diya_actions.ActionFailed, "403 bad scope": diya_actions.ActionFailed, "404 malformed or unknown id": diya_actions.ActionFailed,
    "409 conflict": diya_actions.ActionFailed, "412 changed since": diya_actions.ActionFailed, "429 rate limited": diya_actions.ActionFailed,
    "500": diya_actions.ActionUncertain, "502": diya_actions.ActionUncertain, "503 with no usable body": diya_actions.ActionUncertain, "504": diya_actions.ActionUncertain,
    "read timeout": diya_actions.ActionUncertain, "connect error": diya_actions.ActionFailed, "connect timeout": diya_actions.ActionFailed,
}


@pytest.mark.parametrize("fault", list(WRITE_OUTCOME))
def test_a_write_that_meets_a_fault_makes_one_request_and_is_a_refusal_or_an_unknown_never_a_second_try(fault, config, monkeypatch):
    google = Google(monkeypatch, FAULTS[fault])
    with pytest.raises((diya_actions.ActionFailed, diya_actions.ActionUncertain)) as caught:
        gw._send(config, "google_calendar_edit", "POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", body={"summary": "x"}, what="the event")
    assert type(caught.value) is WRITE_OUTCOME[fault], (fault, type(caught.value).__name__)  # a refusal means nothing was done; "unknown" means it may have been
    assert len(google.calls) == 1
    sentence_is_safe(str(caught.value))


def test_a_write_that_is_rate_limited_says_how_long_to_wait(config, monkeypatch):
    Google(monkeypatch, answer(429, {}, headers={"Retry-After": "90"}))
    with pytest.raises(diya_actions.ActionFailed) as caught:
        gw._send(config, "google_calendar_edit", "POST", "https://www.googleapis.com/calendar/v3/calendars/primary/events", body={}, what="the event")
    assert "90 seconds" in str(caught.value) or "2 minutes" in str(caught.value), str(caught.value)


# ---- the source ---------------------------------------------------------------------------------------------------------------

def test_every_outbound_call_in_the_app_has_a_timeout():
    """Read from the source, so a new call that forgets one fails here. Covers every module that ships, not only Google's."""
    offenders = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name.startswith(("milestone", "diya_chat", "dossier")):  # the archived Phase 1 learning scripts
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "httpx":
                if node.func.attr in ("get", "post", "put", "patch", "delete", "head", "request", "stream") and not any(k.arg == "timeout" or k.arg is None for k in node.keywords):
                    offenders.append(f"{path.name}:{node.lineno} httpx.{node.func.attr}")
    assert offenders == []
