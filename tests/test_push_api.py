"""Web Push over HTTP (docs/PUSH_DESIGN.md, unit P2): diya_push_api.py, the settings that switch it on, and the notifier's use of it.

What this proves: with the switch off every route but /status refuses and /status says why; with it on the key route gives the public key, a good subscription is stored and a bad one is
refused with the rule it broke and without echoing the endpoint; no response ever holds an endpoint or a key of the device; unsubscribing removes only that device; the test route sends one
message that says nothing about the person; DIYA_PUSH=1 needs a contact; and one pass of the notifier does the toast first and then the push, each failing without hiding the other.
"""
import dataclasses
import io
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("cryptography")

from push_fakes import Device, FakeService  # noqa: E402

import diya  # noqa: E402
import diya_config  # noqa: E402
import diya_events  # noqa: E402
import diya_notify  # noqa: E402
import diya_push  # noqa: E402
import diya_push_api  # noqa: E402
import diya_time  # noqa: E402
import diya_web  # noqa: E402
from diya_db import Store  # noqa: E402
from fakes import FakeClient  # noqa: E402

NOW = datetime(2026, 10, 12, 10, 0)
SUBJECT = "mailto:owner@example.invalid"


def make_config(tmp_path, **changes):
    settings = dict(db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"),
                    dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), notify_log_path=str(tmp_path / "notify.log"),
                    require_token=False, push=True, push_subject=SUBJECT, push_vapid_path=str(tmp_path / "push_vapid.json"))
    return dataclasses.replace(diya_config.load_config({}), **{**settings, **changes})


@pytest.fixture
def parts(tmp_path):
    def build(post=None, **changes):
        config = make_config(tmp_path, **changes)
        agent = diya.Agent(config, client=FakeClient([]), clock=lambda: NOW)
        if post is None:
            return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), agent, config
        app = FastAPI()
        diya_push_api.register(app, config, agent, post=post)
        return TestClient(app, base_url="https://localhost"), agent, config
    return build


# --- off ---------------------------------------------------------------------------------------------------------------------

def test_with_the_switch_off_every_route_but_status_refuses_and_says_why(parts):
    client, _, _ = parts(push=False)
    status = client.get("/api/push/status").json()
    assert status["enabled"] is False and "DIYA_PUSH=1" in status["problem"] and status["devices"] == []
    device = Device().subscription
    for method, path, body in (("GET", "/api/push/key", None), ("POST", "/api/push/subscribe", device), ("POST", "/api/push/unsubscribe", {"endpoint": device["endpoint"]}),
                               ("POST", "/api/push/test", None)):
        answer = client.request(method, path, json=body)
        assert answer.status_code == 409 and "DIYA_PUSH=1" in answer.json()["detail"], (method, path)
    assert push_rows(parts) == 0


def push_rows(parts):
    client, agent, _ = parts(push=False)
    conn = agent.store.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
    finally:
        conn.close()


def test_without_the_cryptography_package_the_routes_say_how_to_get_it(parts, monkeypatch):
    client, _, _ = parts()
    monkeypatch.setattr(diya_push, "_crypto", lambda: (_ for _ in ()).throw(diya_push.PushError('Web Push needs the cryptography package: run pip install ".[push]"')))
    assert "pip install" in client.get("/api/push/status").json()["problem"] and client.get("/api/push/key").status_code == 409


# --- on ----------------------------------------------------------------------------------------------------------------------

def test_status_with_the_switch_on_is_enabled_with_no_devices(parts):
    client, _, _ = parts()
    assert client.get("/api/push/status").json() == {"enabled": True, "problem": None, "devices": []}


def test_the_key_route_gives_the_public_key_and_the_same_one_every_time(parts, tmp_path):
    client, _, config = parts()
    first = client.get("/api/push/key").json()["key"]
    assert first == client.get("/api/push/key").json()["key"] == diya_push.Vapid.load_or_create(config.push_vapid_path).public_b64u and len(first) == 87
    assert set(client.get("/api/push/key").json()) == {"key"}


def test_a_good_subscription_is_stored_and_shown_without_its_endpoint_or_keys(parts):
    client, _, _ = parts()
    device = Device(path="/send/SECRETPATH")
    answer = client.post("/api/push/subscribe", json=device.subscription)
    assert answer.status_code == 201 and answer.json() == {"id": 1}
    status = client.get("/api/push/status").json()
    assert [(d["id"], d["service"], d["failures"], d["last_ok_at"]) for d in status["devices"]] == [(1, "push.example.net", 0, None)]
    text = client.get("/api/push/status").text + answer.text
    assert "SECRETPATH" not in text and device.subscription["keys"]["p256dh"] not in text and device.subscription["keys"]["auth"] not in text


def test_a_browsers_whole_subscription_object_is_accepted_including_the_expiration_time(parts):
    client, _, _ = parts()
    assert client.post("/api/push/subscribe", json={**Device().subscription, "expirationTime": None}).status_code == 201
    assert client.post("/api/push/subscribe", json={**Device(path="/two").subscription, "expirationTime": 1790000000000}).status_code == 201


def test_a_bad_subscription_is_a_422_with_the_rule_and_without_the_endpoint(parts):
    client, _, _ = parts()
    secret = "https://127.0.0.1/send/SECRETPATH"
    answer = client.post("/api/push/subscribe", json={**Device().subscription, "endpoint": secret})
    assert answer.status_code == 422 and "public host name" in answer.json()["detail"] and "SECRETPATH" not in answer.text
    for body in ({}, {"endpoint": "https://push.example.net/x"}, {"endpoint": "https://push.example.net/x", "keys": {"p256dh": "a"}}, {"endpoint": 5, "keys": {"p256dh": "a", "auth": "b"}}):
        assert client.post("/api/push/subscribe", json=body).status_code == 422
    assert client.get("/api/push/status").json()["devices"] == []


def test_the_same_device_subscribing_again_is_the_same_row(parts):
    client, _, _ = parts()
    device = Device()
    assert [client.post("/api/push/subscribe", json=device.subscription).json()["id"] for _ in range(3)] == [1, 1, 1]
    assert len(client.get("/api/push/status").json()["devices"]) == 1


def test_unsubscribing_removes_that_device_and_says_whether_it_was_there(parts):
    client, _, _ = parts()
    first, second = Device(path="/one"), Device(path="/two")
    client.post("/api/push/subscribe", json=first.subscription)
    client.post("/api/push/subscribe", json=second.subscription)
    assert client.post("/api/push/unsubscribe", json={"endpoint": first.endpoint}).json() == {"removed": True}
    assert client.post("/api/push/unsubscribe", json={"endpoint": first.endpoint}).json() == {"removed": False}
    assert [d["id"] for d in client.get("/api/push/status").json()["devices"]] == [2]
    assert client.post("/api/push/unsubscribe", json={}).status_code == 422


def test_the_test_route_sends_one_message_that_says_nothing_about_the_person(parts):
    device = Device()
    service = FakeService([device])
    client, _, _ = parts(post=service)
    client.post("/api/push/subscribe", json=device.subscription)
    assert client.post("/api/push/test").json() == {"accepted": 1, "failed": 0}
    assert service.messages() == [{"title": "Diya", "body": "Notifications work here. This says nothing about you.", "tag": "test"}]


def test_the_test_route_counts_a_device_that_did_not_accept_it(parts):
    device = Device()
    client, _, _ = parts(post=FakeService([device], statuses=(503,)))
    client.post("/api/push/subscribe", json=device.subscription)
    assert client.post("/api/push/test").json() == {"accepted": 0, "failed": 1}


def test_the_test_route_with_no_device_is_zero_and_zero(parts):
    client, _, _ = parts(post=FakeService())
    assert client.post("/api/push/test").json() == {"accepted": 0, "failed": 0}


def test_a_key_file_that_cannot_be_read_is_a_500_that_shows_nothing_of_it(parts, tmp_path):
    client, _, config = parts()
    (tmp_path / "push_vapid.json").write_text("garbage garbage")
    answer = client.get("/api/push/key")
    assert answer.status_code == 500 and "garbage" not in answer.text


# --- the settings ------------------------------------------------------------------------------------------------------------

def test_the_defaults_are_off_hidden_and_without_a_contact():
    config = diya_config.load_config({})
    assert (config.push, config.push_show_text, config.push_quiet, config.push_day_at, config.push_subject, config.push_vapid_path) == (False, False, "22-07", "", "", "push_vapid.json")


def test_push_needs_a_contact_that_is_a_mailto_or_https_address():
    for subject in (None, "", "owner@example.invalid", "mailto:", "mailto:nobody", "http://example.invalid", "https://", "tel:123"):
        env = {"DIYA_PUSH": "1"} if subject is None else {"DIYA_PUSH": "1", "DIYA_PUSH_SUBJECT": subject}
        with pytest.raises(diya_config.ConfigError, match="DIYA_PUSH_SUBJECT"):
            diya_config.load_config(env)
    for subject in ("mailto:me@example.invalid", "https://example.invalid/contact"):
        assert diya_config.load_config({"DIYA_PUSH": "1", "DIYA_PUSH_SUBJECT": subject}).push_subject == subject


def test_a_contact_without_the_switch_is_just_a_setting():
    assert diya_config.load_config({"DIYA_PUSH_SUBJECT": "whatever"}).push is False


def test_the_times_are_checked_when_the_settings_are_read():
    assert diya_config.load_config({"DIYA_PUSH_QUIET": "off", "DIYA_PUSH_DAY_AT": "08:30"}).push_day_at == "08:30"
    for name, value in (("DIYA_PUSH_QUIET", "25-3"), ("DIYA_PUSH_DAY_AT", "8am"), ("DIYA_PUSH_DAY_AT", "24:00"), ("DIYA_PUSH_DAY_AT", "08:60")):
        with pytest.raises(diya_config.ConfigError, match=name):
            diya_config.load_config({name: value})


def test_the_show_text_flag_and_the_switch_take_the_usual_words():
    assert diya_config.load_config({"DIYA_PUSH_SHOW_TEXT": "yes"}).push_show_text is True
    with pytest.raises(diya_config.ConfigError, match="DIYA_PUSH_SHOW_TEXT"):
        diya_config.load_config({"DIYA_PUSH_SHOW_TEXT": "maybe"})


def test_the_key_file_follows_the_data_folder(tmp_path):
    assert diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path / "d")}).push_vapid_path == str(tmp_path / "d" / "push_vapid.json")


# --- one pass of the notifier ------------------------------------------------------------------------------------------------

class Screen:
    def __init__(self, failing=False):
        self.shown, self.failing = [], failing

    def __call__(self, title, body):
        if self.failing:
            raise diya_notify.NotifyError("no screen")
        self.shown.append((title, body))


def notifier_pass(config, screen, post, now=NOW, extra=()):
    out = io.StringIO()
    return diya_notify.main(list(extra), config=config, out=out, notify=screen, now=now), out.getvalue()


def test_a_pass_shows_the_toast_and_then_pushes_and_each_says_the_same_thing(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.db_path)
    store.add_reminder("call the bank", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    device = Device()
    diya_push.Subscriptions(store).add(device.endpoint, device.subscription["keys"]["p256dh"], device.subscription["keys"]["auth"], diya_events.utc_of_local(NOW))
    service = FakeService([device])
    original = diya_push.deliver
    monkeypatch.setattr(diya_push, "deliver", lambda *a, **k: original(*a, post=service, **k))
    screen = Screen()
    code, text = notifier_pass(dataclasses.replace(config, notify_show_text=False), screen, service)
    assert code == 0 and screen.shown == [("Diya", "A reminder is due")] and service.messages() == [{"title": "Diya", "body": "A reminder is due", "tag": "reminder:1"}]
    assert "1 pushed" in text and "1 told" in text


def test_a_push_that_fails_does_not_hide_the_toast_and_exits_one(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.db_path)
    store.add_reminder("x", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    device = Device()
    diya_push.Subscriptions(store).add(device.endpoint, device.subscription["keys"]["p256dh"], device.subscription["keys"]["auth"], diya_events.utc_of_local(NOW))
    original = diya_push.deliver
    monkeypatch.setattr(diya_push, "deliver", lambda *a, **k: original(*a, post=FakeService([device], statuses=(503,)), **k))
    screen = Screen()
    code, text = notifier_pass(config, screen, None)
    assert code == 1 and len(screen.shown) == 1 and "could not push to device 1" in text
    log = open(config.notify_log_path, encoding="utf-8").read()
    assert "push: 0 sent, 1 failed, 0 removed" in log and "SECRET" not in log and device.endpoint not in log


def test_a_toast_that_fails_does_not_stop_the_push(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    store = Store(config.db_path)
    store.add_reminder("x", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    device = Device()
    diya_push.Subscriptions(store).add(device.endpoint, device.subscription["keys"]["p256dh"], device.subscription["keys"]["auth"], diya_events.utc_of_local(NOW))
    service = FakeService([device])
    original = diya_push.deliver
    monkeypatch.setattr(diya_push, "deliver", lambda *a, **k: original(*a, post=service, **k))
    code, text = notifier_pass(config, Screen(failing=True), None)
    assert code == 1 and len(service.requests) == 1


def test_without_the_switch_the_pass_never_looks_at_push(tmp_path, monkeypatch):
    config = make_config(tmp_path, push=False)
    Store(config.db_path).add_reminder("x", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    monkeypatch.setattr(diya_push, "deliver", lambda *a, **k: pytest.fail("push was asked for"))
    code, text = notifier_pass(config, Screen(), None)
    assert code == 0 and "pushed" not in text


def test_a_push_error_is_one_line_with_no_traceback_and_the_toast_still_shows(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    Store(config.db_path).add_reminder("x", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    monkeypatch.setattr(diya_push, "deliver", lambda *a, **k: (_ for _ in ()).throw(diya_push.PushError("Web Push needs the cryptography package")))
    screen = Screen()
    code, text = notifier_pass(config, screen, None)
    assert code == 1 and len(screen.shown) == 1 and "could not push: Web Push needs the cryptography package" in text and "Traceback" not in text


def test_any_other_push_failure_names_only_its_kind(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    Store(config.db_path).add_reminder("x", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    monkeypatch.setattr(diya_push, "deliver", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("SECRETKEY")))
    code, text = notifier_pass(config, Screen(), None)
    assert code == 1 and "could not push: RuntimeError" in text and "SECRETKEY" not in text


def test_a_dry_run_pass_says_what_it_would_push_and_changes_nothing(tmp_path):
    config = make_config(tmp_path, push_show_text=True)
    store = Store(config.db_path)
    store.add_reminder("call the bank", "when", diya_time.iso_of_local(NOW - timedelta(minutes=5)))
    device = Device()
    diya_push.Subscriptions(store).add(device.endpoint, device.subscription["keys"]["p256dh"], device.subscription["keys"]["auth"], diya_events.utc_of_local(NOW))
    screen = Screen()
    code, text = notifier_pass(config, screen, None, extra=("--dry-run",))
    assert code == 0 and screen.shown == [] and "would push: Diya: " in text and "call the bank" in text and diya_events.Deliveries(store, "push").told() == set()


# --- the edges that mutation found --------------------------------------------------------------------------------------------------

def test_when_it_is_switched_off_the_status_lists_no_devices_even_if_some_were_subscribed_before(parts):
    on, _, _ = parts()
    on.post("/api/push/subscribe", json=Device().subscription)
    off, _, _ = parts(push=False)
    assert off.get("/api/push/status").json()["devices"] == [] and len(on.get("/api/push/status").json()["devices"]) == 1


def test_a_device_is_stamped_with_the_agents_clock_in_utc(parts):
    client, _, _ = parts()
    client.post("/api/push/subscribe", json=Device().subscription)
    assert client.get("/api/push/status").json()["devices"][0]["created_at"] == diya_events.utc_of_local(NOW).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_key_file_that_cannot_be_read_makes_the_test_route_a_500_that_shows_nothing_of_it(parts, tmp_path):
    device = Device()
    client, _, _ = parts(post=FakeService([device]))
    client.post("/api/push/subscribe", json=device.subscription)
    (tmp_path / "push_vapid.json").write_text("garbage garbage")
    answer = client.post("/api/push/test")
    assert answer.status_code == 500 and "garbage" not in answer.text


def test_the_key_file_setting_is_read_and_wins_over_the_data_folder(tmp_path):
    assert diya_config.load_config({"DIYA_PUSH_VAPID_PATH": "somewhere/else.json"}).push_vapid_path == "somewhere/else.json"
    assert diya_config.load_config({"DIYA_DATA_DIR": str(tmp_path), "DIYA_PUSH_VAPID_PATH": "own.json"}).push_vapid_path == "own.json"
