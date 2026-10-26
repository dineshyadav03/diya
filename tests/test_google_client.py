"""The one careful client for the newer Google cards (diya_google_client.py; DIYA-067, DIYA-069, DIYA-054; docs/GOOGLE_CLIENT.md), added 2026-10-26.

What this proves, with a stand-in Google that counts what it was sent: a request is made only to https addresses on Google's own hosts that the card has been given, with no query string, user or fragment in the address
(refused before a token is fetched); every refusal Google gives becomes one typed GoogleError with a kind and safe words (not signed in, API not switched on, permission not given, not found, changed meanwhile,
busy, server fault, network); a read that is refused for being busy or fails on Google's side is tried again at most twice, waits what Google asked but never more than the cap, and a read that is simply refused is not
tried again; a write is NEVER tried again (a failure on Google's side part way is "may or may not have happened", never "retried"); a list follows the next page at most the limit and says it stopped early; every request
is counted for the day and past the limit nothing more is sent; a write's outcomes (done, refused with nothing done, may or may not have happened) are those of every other action.
"""
import dataclasses
import types

import httpx
import pytest

import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_client as client
from diya_actions import ActionFailed, ActionUncertain

BASE = "https://www.googleapis.com/test/v1/things"
CARD = "google_test_card"
LABEL = "Test card"


@pytest.fixture(autouse=True)
def card_and_no_waiting(monkeypatch):
    monkeypatch.setattr(client, "_sleep", lambda seconds: slept.append(seconds))
    slept.clear()
    saved = list(client._ALLOWED)
    client.allow(CARD, "GET", r"https://www\.googleapis\.com/test/v1/things(?:/[A-Za-z0-9_-]{3,64})?")
    client.allow(CARD, "POST", r"https://www\.googleapis\.com/test/v1/things")
    client.allow(CARD, "PATCH", r"https://www\.googleapis\.com/test/v1/things/[A-Za-z0-9_-]{3,64}")
    yield
    client._ALLOWED[:] = saved


slept = []


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "g.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False)
    diya_connectors.store_token(config, CARD, "refresh-token")
    return config


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "access-token" if name == CARD else None)


def response(status=200, body=None, headers=None):
    return types.SimpleNamespace(status_code=status, headers=headers or {}, json=lambda: body if body is not None else {})


class Google:
    """A stand-in: answers from a script, in order, and keeps every request."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        self.asked.append((method, url, kwargs.get("params"), kwargs.get("headers", {}).get("Authorization")))
        answer = self.answers.pop(0) if self.answers else response(200, {})
        if isinstance(answer, Exception):
            raise answer
        return answer


def serve(monkeypatch, *answers):
    google = Google(*answers)
    monkeypatch.setattr(client.httpx, "get", google)
    monkeypatch.setattr(client.httpx, "request", google)
    return google


# ---- the allowlist ------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method, url, expected", [
    ("GET", BASE, True), ("GET", BASE + "/abc123", True), ("get", BASE, True), ("POST", BASE, True), ("PATCH", BASE + "/abc123", True),
    ("DELETE", BASE + "/abc123", False), ("POST", BASE + "/abc123", False), ("GET", BASE + "/../secret", False), ("GET", BASE + "?access_token=x", False), ("GET", BASE + "#x", False),
    ("GET", "http://www.googleapis.com/test/v1/things", False), ("GET", "https://evil.example/test/v1/things", False), ("GET", "https://www.googleapis.com.evil.example/test/v1/things", False),
    ("GET", "https://user:pw@www.googleapis.com/test/v1/things", False), ("GET", None, False), ("GET", 5, False),
])
def test_only_https_google_addresses_the_card_was_given_are_allowed(method, url, expected):
    assert client.permitted(CARD, method, url) is expected


def test_another_card_has_none_of_it_and_a_request_not_allowed_is_refused_before_a_token_is_asked_for(config, monkeypatch):
    assert not client.permitted("google_other", "GET", BASE)
    asked = []
    monkeypatch.setattr(gcal, "access_token", lambda config, name: asked.append(name) or "t")
    google = serve(monkeypatch)
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE + "/../x")
    assert caught.value.kind == "bad_request" and asked == [] and google.asked == []
    with pytest.raises(ActionFailed):
        client.send(config, CARD, LABEL, "DELETE", BASE + "/abc123")
    assert asked == [] and google.asked == []


# ---- reads and the kinds of failure ------------------------------------------------------------------------------------------------------------------

def test_a_read_returns_what_google_said_with_the_token_and_the_params(config, monkeypatch):
    google = serve(monkeypatch, response(200, {"items": [{"id": "a"}]}))
    assert client.read(config, CARD, LABEL, BASE, {"maxResults": 5}) == {"items": [{"id": "a"}]}
    assert google.asked == [("GET", BASE, {"maxResults": 5}, "Bearer access-token")]


@pytest.mark.parametrize("status, body, kind", [
    (401, {}, "signed_out"),
    (403, {"error": {"status": "PERMISSION_DENIED", "message": "Gmail API has not been used in project 1 before or it is disabled.", "errors": [{"reason": "accessNotConfigured"}]}}, "api_disabled"),
    (403, {"error": {"message": "Request had insufficient authentication scopes.", "errors": [{"reason": "insufficientPermissions"}]}}, "scope"),
    (403, {"error": {"message": "nope"}}, "scope"),
    (404, {}, "not_found"), (409, {}, "conflict"), (412, {}, "conflict"), (400, {"error": {"message": "bad"}}, "bad_request"), (418, {}, "bad_request"),
])
def test_a_refusal_is_one_typed_error_and_is_not_tried_again(config, monkeypatch, status, body, kind):
    google = serve(monkeypatch, response(status, body))
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE)
    assert caught.value.kind == kind and caught.value.status == status and len(google.asked) == 1 and slept == []
    assert "Bearer" not in str(caught.value) and "access-token" not in str(caught.value)


def test_not_connected_and_signed_out_say_so_without_asking_google(config, monkeypatch):
    google = serve(monkeypatch)
    diya_connectors.disconnect(config, CARD)
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE)
    assert caught.value.kind == "not_connected" and "Connections page" in str(caught.value)
    diya_connectors.store_token(config, CARD, "again")
    monkeypatch.setattr(gcal, "access_token", lambda config, name: None)
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE)
    assert caught.value.kind == "signed_out" and google.asked == []


def test_a_busy_google_is_asked_again_at_most_twice_waiting_what_it_said_but_never_more_than_the_cap(config, monkeypatch):
    google = serve(monkeypatch, response(429, {}, {"Retry-After": "2"}), response(429, {}, {"Retry-After": "600"}), response(200, {"ok": True}))
    assert client.read(config, CARD, LABEL, BASE) == {"ok": True}
    assert len(google.asked) == 3 and slept == [2.0, client.MAX_WAIT_SECONDS]
    google = serve(monkeypatch, response(503), response(500), response(502))
    slept.clear()
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE)
    assert caught.value.kind == "server" and len(google.asked) == 3 and slept == [1, 2]  # three tries in all, then it says so


def test_a_rate_limit_that_google_sends_as_a_403_is_treated_like_a_429(config, monkeypatch):
    google = serve(monkeypatch, response(403, {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}), response(200, {"ok": 1}))
    assert client.read(config, CARD, LABEL, BASE) == {"ok": 1} and len(google.asked) == 2 and slept == [1]


def test_a_network_failure_is_tried_again_and_then_said_without_leaking_the_error(config, monkeypatch):
    google = serve(monkeypatch, httpx.ConnectError("secret 10.0.0.1"), httpx.ConnectError("secret 10.0.0.1"), httpx.ConnectError("secret 10.0.0.1"))
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE)
    assert caught.value.kind == "network" and "10.0.0.1" not in str(caught.value) and len(google.asked) == 3


def test_an_answer_that_is_not_an_object_is_an_empty_one(config, monkeypatch):
    serve(monkeypatch, types.SimpleNamespace(status_code=200, headers={}, json=lambda: [1, 2]))
    assert client.read(config, CARD, LABEL, BASE) == {}


# ---- paging -------------------------------------------------------------------------------------------------------------------------------------------

def test_a_list_follows_the_next_page_and_says_when_it_stopped_early(config, monkeypatch):
    google = serve(monkeypatch, response(200, {"items": [{"id": "a"}], "nextPageToken": "p2"}), response(200, {"items": [{"id": "b"}, "junk", 5]}))
    items, more = client.pages(config, CARD, LABEL, BASE, {"pageSize": 1}, "items")
    assert items == [{"id": "a"}, {"id": "b"}] and more is False and google.asked[1][2] == {"pageSize": 1, "pageToken": "p2"}
    serve(monkeypatch, *[response(200, {"items": [{"id": str(n)}], "nextPageToken": f"p{n + 1}"}) for n in range(10)])
    items, more = client.pages(config, CARD, LABEL, BASE, {}, "items", max_pages=3)
    assert len(items) == 3 and more is True


# ---- the daily count ---------------------------------------------------------------------------------------------------------------------------

def test_every_request_is_counted_and_past_the_limit_nothing_more_is_sent(config, monkeypatch):
    config = dataclasses.replace(config, google_daily_requests=3)
    google = serve(monkeypatch)
    for _ in range(3):
        client.read(config, CARD, LABEL, BASE)
    assert client.requests_today(config) == 3
    with pytest.raises(client.GoogleError) as caught:
        client.read(config, CARD, LABEL, BASE)
    assert caught.value.kind == "limit" and "DIYA_GOOGLE_DAILY_REQUESTS" in str(caught.value) and len(google.asked) == 3
    with pytest.raises(ActionFailed, match="as many requests"):
        client.send(config, CARD, LABEL, "POST", BASE, body={})
    assert len(google.asked) == 3


def test_a_limit_of_zero_is_no_limit(config, monkeypatch):
    config = dataclasses.replace(config, google_daily_requests=0)
    serve(monkeypatch)
    for _ in range(8):
        client.read(config, CARD, LABEL, BASE)
    assert client.requests_today(config) == 0  # nothing is counted when nothing is limited


# ---- writes -------------------------------------------------------------------------------------------------------------------------------------

def test_a_write_that_worked_returns_the_answer_and_carries_the_headers_it_was_given(config, monkeypatch):
    google = serve(monkeypatch, response(200, {"id": "abc123"}))
    answer = client.send(config, CARD, LABEL, "PATCH", BASE + "/abc123", body={"a": 1}, headers={"If-Match": '"etag"'})
    assert client.as_json(answer) == {"id": "abc123"} and google.asked[0][0] == "PATCH"


def test_a_refused_write_says_nothing_was_done_and_a_busy_one_is_not_tried_again(config, monkeypatch):
    google = serve(monkeypatch, response(403, {"error": {"message": "Request had insufficient authentication scopes."}}))
    with pytest.raises(ActionFailed, match="Nothing was done"):
        client.send(config, CARD, LABEL, "POST", BASE, body={})
    google = serve(monkeypatch, response(429, {}, {"Retry-After": "5"}))
    with pytest.raises(ActionFailed, match="limiting requests"):
        client.send(config, CARD, LABEL, "POST", BASE, body={})
    assert len(google.asked) == 1 and slept == []


def test_a_fault_on_googles_side_or_no_answer_is_may_or_may_not_have_happened_and_never_retried(config, monkeypatch):
    google = serve(monkeypatch, response(503))
    with pytest.raises(ActionUncertain, match="may or may not have been done"):
        client.send(config, CARD, LABEL, "POST", BASE, body={}, doing="the thing")
    assert len(google.asked) == 1
    google = serve(monkeypatch, httpx.ReadTimeout("no answer"))
    with pytest.raises(ActionUncertain, match="no answer came back"):
        client.send(config, CARD, LABEL, "POST", BASE, body={})
    google = serve(monkeypatch, httpx.ConnectError("down"))
    with pytest.raises(ActionFailed, match="Couldn't reach Google"):
        client.send(config, CARD, LABEL, "POST", BASE, body={})  # it never left: nothing was done
    assert slept == []


def test_a_change_made_meanwhile_is_refused_and_says_to_look_again(config, monkeypatch):
    serve(monkeypatch, response(412, {}))
    with pytest.raises(ActionFailed, match="changed in the meantime"):
        client.send(config, CARD, LABEL, "PATCH", BASE + "/abc123", body={}, headers={"If-Match": '"old"'})


def test_a_card_that_is_not_connected_does_nothing(config, monkeypatch):
    google = serve(monkeypatch)
    diya_connectors.disconnect(config, CARD)
    with pytest.raises(ActionFailed, match="not connected"):
        client.send(config, CARD, LABEL, "POST", BASE, body={})
    assert google.asked == []
