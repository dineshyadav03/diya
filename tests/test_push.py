"""Telling the phone by Web Push (docs/PUSH_DESIGN.md, unit P2): diya_push.py.

What this proves: a message is encrypted so that an independent receiver (tests/push_fakes.py, written from RFC 8291 and RFC 8188 with the cryptography package's own HKDF) can read
it, and nothing else can (a changed byte, a wrong auth secret or a wrong key fails); every message has a fresh salt and key; the VAPID token verifies with the public key and says what RFC
8292 wants; every way a subscription can be wrong is refused before it is stored; each answer of a push service has the consequence the design gives it; a message is recorded as told only
after a device accepted it; the caps hold; nothing that is logged, shown or returned holds an endpoint, a key or a message; and importing the module does nothing.
"""
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("cryptography")

import dataclasses  # noqa: E402

from cryptography.exceptions import InvalidTag  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from push_fakes import Device, FakeService, b64u, hkdf, point, unb64u, verify_vapid  # noqa: E402

import diya_config  # noqa: E402
import diya_events  # noqa: E402
import diya_push as push  # noqa: E402
import diya_time  # noqa: E402
from diya_db import Store  # noqa: E402

NOW = datetime(2026, 10, 12, 10, 0)  # local
SUBJECT = "mailto:owner@example.invalid"


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "p.db"))


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.Config(), push=True, push_subject=SUBJECT, push_vapid_path=str(tmp_path / "push_vapid.json"), push_quiet="22-07", push_day_at="")


@pytest.fixture
def vapid(tmp_path):
    return push.Vapid.load_or_create(str(tmp_path / "v.json"))


def subscribe(store, device=None, **kwargs):
    device = device or Device(**kwargs)
    sub = device.subscription
    push.Subscriptions(store).add(sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc))
    return device


def remind(store, text, local):
    return store.add_reminder(text, "when", diya_time.iso_of_local(local))


# ---- the small pieces ------------------------------------------------------------------------------------------------------------

def test_url_safe_base64_round_trips_with_or_without_padding():
    for data in (b"", b"a", b"ab", b"abc", bytes(range(256)), os.urandom(65)):
        text = push.b64u(data)
        assert "=" not in text and "+" not in text and "/" not in text and push.b64u(data) == b64u(data)
        if data:
            assert push.unb64u(text) == data and push.unb64u(text + "=" * (-len(text) % 4)) == data


@pytest.mark.parametrize("text", ["", "a+b", "a/b", "a b", "a\n", "é", "=" * 3 + "a", None, 5, "a" * 5000])
def test_base64_that_is_not_url_safe_is_refused(text):
    with pytest.raises(ValueError):
        push.unb64u(text)


def test_hkdf_agrees_with_the_cryptography_packages_own():
    for length in (1, 12, 16, 32):
        salt, ikm, info = os.urandom(16), os.urandom(32), os.urandom(20)
        assert push.hkdf_expand(push.hkdf_extract(salt, ikm), info, length) == hkdf(salt, info, length, ikm)


def test_hkdf_expand_makes_at_most_one_block():
    for length in (0, 33, -1):
        with pytest.raises(ValueError):
            push.hkdf_expand(b"k" * 32, b"i", length)


# ---- the message -----------------------------------------------------------------------------------------------------------------

def test_what_is_encrypted_can_be_read_by_the_device_and_has_the_header_the_rfc_gives():
    device = Device()
    payload = json.dumps({"title": "Diya", "body": "A reminder is due"}).encode()
    body = push.encrypt(payload, device.public, device.auth)
    assert device.decrypt(body) == payload
    assert len(body[:16]) == 16 and body[16:20] == (4096).to_bytes(4, "big") and body[20] == 65 and body[21] == 4
    assert len(body) == 16 + 4 + 1 + 65 + len(payload) + 1 + 16


def test_every_message_has_a_fresh_salt_and_a_fresh_key_and_so_a_fresh_ciphertext():
    device = Device()
    first, second = push.encrypt(b"same", device.public, device.auth), push.encrypt(b"same", device.public, device.auth)
    assert first[:16] != second[:16] and first[21:86] != second[21:86] and first[86:] != second[86:]
    assert device.decrypt(first) == device.decrypt(second) == b"same"


def test_with_a_given_salt_and_key_the_output_is_exactly_reproducible():
    device = Device()
    key = ec.generate_private_key(ec.SECP256R1())
    assert push.encrypt(b"x", device.public, device.auth, salt=b"s" * 16, as_private=key) == push.encrypt(b"x", device.public, device.auth, salt=b"s" * 16, as_private=key)
    assert push.encrypt(b"x", device.public, device.auth, salt=b"s" * 16, as_private=key)[:16] == b"s" * 16


def test_a_changed_byte_a_wrong_auth_secret_and_a_wrong_device_all_fail_to_decrypt():
    device = Device()
    body = push.encrypt(b"secret words", device.public, device.auth)
    for index in (86, len(body) - 1):
        tampered = bytearray(body)
        tampered[index] ^= 1
        with pytest.raises(InvalidTag):
            device.decrypt(bytes(tampered))
    other_auth = Device()
    other_auth.private, other_auth.public = device.private, device.public
    other_auth.auth = b"another-secret!!"
    with pytest.raises(InvalidTag):
        other_auth.decrypt(body)
    with pytest.raises(InvalidTag):
        Device(auth=device.auth).decrypt(body)  # a different key pair, the same auth secret


def test_the_payload_is_not_visible_in_what_is_sent():
    device = Device()
    assert b"private words" not in push.encrypt(b"private words in a notification", device.public, device.auth)


def test_the_largest_payload_fits_the_four_thousand_ninety_six_bytes_a_push_service_must_take():
    device = Device()
    body = push.encrypt(b"x" * push.MAX_PAYLOAD_BYTES, device.public, device.auth)
    assert len(body) == 4096 and device.decrypt(body) == b"x" * push.MAX_PAYLOAD_BYTES


def test_a_payload_that_is_too_big_or_not_bytes_is_refused():
    device = Device()
    for payload in (b"x" * (push.MAX_PAYLOAD_BYTES + 1), "text", None):
        with pytest.raises(push.PushError):
            push.encrypt(payload, device.public, device.auth)


def test_a_key_or_secret_of_the_wrong_size_or_off_the_curve_is_refused():
    device = Device()
    for key, auth in ((device.public[:-1], device.auth), (device.public, device.auth[:-1]), (device.public + b"x", device.auth), (b"\x04" + b"\x01" * 64, device.auth)):
        with pytest.raises(push.PushError):
            push.encrypt(b"x", key, auth)
    with pytest.raises(push.PushError):
        push.encrypt(b"x", device.public, device.auth, salt=b"short")


# ---- the identity ----------------------------------------------------------------------------------------------------------------

def test_a_key_pair_is_made_once_kept_in_one_file_and_found_again(tmp_path):
    path = tmp_path / "data" / "push_vapid.json"
    first = push.Vapid.load_or_create(str(path))
    assert path.exists() and len(unb64u(first.public_b64u)) == 65 and first.public == unb64u(first.public_b64u)
    again = push.Vapid.load_or_create(str(path))
    assert again.public_b64u == first.public_b64u
    stored = json.loads(path.read_text())
    assert set(stored) == {"private", "public", "made"} and stored["public"] == first.public_b64u and len(unb64u(stored["private"])) == 32


@pytest.mark.skipif(os.name == "nt", reason="file modes mean little on Windows")
def test_the_key_file_is_readable_by_its_owner_only(tmp_path):
    path = tmp_path / "v.json"
    push.Vapid.load_or_create(str(path))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_key_that_is_there_is_never_overwritten_and_a_broken_one_is_an_error_that_shows_nothing_of_it(tmp_path):
    path = tmp_path / "v.json"
    first = push.Vapid.load_or_create(str(path))
    for broken in ("not json", "{}", json.dumps({"private": "AAAA", "public": first.public_b64u}), json.dumps({"private": json.loads(path.read_text())["private"], "public": "AAAA"}), "[1]"):
        path.write_text(broken)
        with pytest.raises(push.PushError) as caught:
            push.Vapid.load_or_create(str(path))
        assert broken not in str(caught.value) and path.read_text() == broken


def test_the_key_cannot_be_saved_where_there_is_no_folder_to_make(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    with pytest.raises(push.PushError):
        push.Vapid.load_or_create(str(blocker / "inside" / "v.json"))


def test_the_token_verifies_and_says_what_the_rfc_wants(vapid):
    now = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    token = vapid.token("https://push.example.net/send/abc", SUBJECT, now)
    claims = verify_vapid(f"vapid t={token}, k={vapid.public_b64u}", vapid.public_b64u, "push.example.net", SUBJECT, now.timestamp())
    assert claims["exp"] == int((now + timedelta(hours=12)).timestamp()) and set(claims) == {"aud", "exp", "sub"}


def test_the_audience_is_the_push_services_origin_whatever_the_path_or_the_default_port(vapid):
    now = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    for endpoint, host in (("https://fcm.example.org/fcm/send/xyz", "fcm.example.org"), ("https://fcm.example.org:443/a/b?c=d", "fcm.example.org")):
        claims = verify_vapid(f"vapid t={vapid.token(endpoint, SUBJECT, now)}, k={vapid.public_b64u}", vapid.public_b64u, host, SUBJECT, now.timestamp())
        assert claims["aud"] == f"https://{host}"


def test_the_token_also_verifies_in_an_independent_jwt_library(vapid):
    jwt = pytest.importorskip("jwt")  # PyJWT: not a dependency of this project, so this check runs only where it happens to be installed
    now = datetime.now(timezone.utc)
    token = vapid.token("https://push.example.net/send/abc", SUBJECT, now)
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(vapid.public_b64u))
    claims = jwt.decode(token, key=public, algorithms=["ES256"], audience="https://push.example.net")
    assert claims["sub"] == SUBJECT and claims["aud"] == "https://push.example.net"
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(token, key=public, algorithms=["ES256"], audience="https://other.example.net")


def test_a_token_from_another_key_does_not_verify(vapid, tmp_path):
    other = push.Vapid.load_or_create(str(tmp_path / "other.json"))
    now = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    with pytest.raises(Exception):
        verify_vapid(f"vapid t={other.token('https://push.example.net/x', SUBJECT, now)}, k={vapid.public_b64u}", vapid.public_b64u, "push.example.net", SUBJECT, now.timestamp())


# ---- subscriptions: what is refused -----------------------------------------------------------------------------------------------

def good(**changes):
    device = Device()
    values = {"endpoint": device.endpoint, "p256dh": b64u(device.public), "auth": b64u(device.auth)}
    values.update(changes)
    return values


def test_a_good_subscription_is_normalised_and_kept_as_given():
    values = good()
    assert push.validate_subscription(**values) == (values["endpoint"], values["p256dh"], values["auth"])
    padded = good(p256dh=b64u(Device().public) + "=")
    assert push.validate_subscription(**padded)[1] == padded["p256dh"].rstrip("=")


@pytest.mark.parametrize("endpoint", [
    "http://push.example.net/send/abc", "ftp://push.example.net/x", "https:///path", "https://127.0.0.1/send", "https://[::1]/send", "https://192.0.2.5/send", "https://localhost/send",
    "https://intranet/send", "https://printer.local/send", "https://nas.lan/send", "https://host.internal/send", "https://user:pw@push.example.net/send", "https://user@push.example.net/send",
    "https://push.example.net/send#frag", "https://push.example.net:8443/send", "https://push.example.net:80/send", "https://push.example.net/ send", "https://push.example.net/é",
    "https://push.example.net/" + "a" * 2100, "", "https://push.example.net:99999/x", "https://[2001:db8::1]/x", "https://0x7f.1/x",
])
def test_an_endpoint_that_is_not_a_public_https_host_name_is_refused(endpoint):
    with pytest.raises(push.InvalidSubscription):
        push.validate_subscription(**good(endpoint=endpoint))


@pytest.mark.parametrize("endpoint", ["https://PUSH.Example.NET/send", "https://push.example.net:443/send", "https://updates.push.services.example.org/wpush/v2/abc?x=y"])
def test_an_endpoint_that_is_a_public_https_host_name_is_accepted(endpoint):
    assert push.validate_subscription(**good(endpoint=endpoint))[0] == endpoint


def test_a_non_string_endpoint_is_refused():
    for endpoint in (None, 5, ["https://push.example.net/x"], b"https://push.example.net/x"):
        with pytest.raises(push.InvalidSubscription):
            push.validate_subscription(**good(endpoint=endpoint))


def test_keys_of_the_wrong_kind_are_refused():
    device = Device()
    bad_point = b"\x04" + b"\x01" * 64
    cases = [
        {"p256dh": ""}, {"p256dh": "a+b/"}, {"p256dh": b64u(device.public[:-1])}, {"p256dh": b64u(b"\x03" + device.public[1:])}, {"p256dh": b64u(bad_point)}, {"p256dh": None},
        {"auth": ""}, {"auth": b64u(b"short")}, {"auth": b64u(b"x" * 17)}, {"auth": "a+b/"}, {"auth": 5},
    ]
    for changes in cases:
        with pytest.raises(push.InvalidSubscription):
            push.validate_subscription(**good(**changes))


# ---- subscriptions: the table ----------------------------------------------------------------------------------------------------

def test_a_subscription_is_added_updated_listed_without_its_endpoint_and_removed(store):
    subscriptions = push.Subscriptions(store)
    device = subscribe(store)
    (listed,) = subscriptions.public()
    assert listed == {"id": 1, "service": "push.example.net", "created_at": "2026-10-12T04:00:00Z", "last_ok_at": None, "failures": 0}
    assert "send" not in json.dumps(listed) and device.endpoint not in json.dumps(listed)
    sub = device.subscription
    assert subscriptions.add(sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], datetime(2026, 10, 13, tzinfo=timezone.utc)) == 1  # the same device again: the same row
    assert len(subscriptions.all()) == 1 and subscriptions.all()[0]["created_at"] == "2026-10-12T04:00:00Z"
    assert subscriptions.remove_endpoint(device.endpoint) is True and subscriptions.remove_endpoint(device.endpoint) is False and subscriptions.public() == []


def test_subscribing_again_gives_the_new_keys_and_clears_the_refusals(store):
    subscriptions = push.Subscriptions(store)
    device = subscribe(store)
    subscriptions.mark_failed(1)
    renewed = Device(path="/send/abc123")
    sub = renewed.subscription
    subscriptions.add(sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], datetime(2026, 10, 13, tzinfo=timezone.utc))
    (row,) = subscriptions.all()
    assert row["failures"] == 0 and row["p256dh"] == b64u(renewed.public) and device.endpoint == row["endpoint"]


def test_at_most_ten_devices_and_the_eleventh_is_refused_with_a_reason(store):
    for n in range(push.MAX_SUBSCRIPTIONS):
        subscribe(store, path=f"/send/{n}")
    with pytest.raises(push.InvalidSubscription, match="at most 10"):
        subscribe(store, path="/send/eleven")
    subscribe(store, path="/send/3")  # one that is already there is still a renewal, not a new device
    assert len(push.Subscriptions(store).all()) == 10


def test_refusals_are_counted_and_never_remove_a_device(store):
    subscriptions = push.Subscriptions(store)
    subscribe(store)
    assert [subscriptions.mark_failed(1) for _ in range(7)] == [1, 2, 3, 4, 5, 6, 7] and subscriptions.all()[0]["failures"] == 7
    assert subscriptions.mark_failed(99) == 0


def test_a_success_clears_the_refusals_and_notes_the_time(store):
    subscriptions = push.Subscriptions(store)
    subscribe(store)
    for _ in range(3):
        subscriptions.mark_failed(1)
    subscriptions.mark_ok(1, datetime(2026, 10, 12, 9, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))))
    (row,) = subscriptions.all()
    assert (row["failures"], row["last_ok_at"]) == (0, "2026-10-12T04:00:00Z")


def test_removing_by_id(store):
    subscriptions = push.Subscriptions(store)
    subscribe(store, path="/a")
    subscribe(store, path="/b")
    assert subscriptions.remove(1) is True and subscriptions.remove(1) is False and [row["id"] for row in subscriptions.all()] == [2]


# ---- what an answer means --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, outcome", [
    (200, "accepted"), (201, "accepted"), (202, "accepted"), (204, "rejected"), (404, "gone"), (410, "gone"), (400, "rejected"), (401, "rejected"), (403, "rejected"),
    (413, "rejected"), (301, "rejected"), (302, "rejected"), (405, "rejected"), (408, "retry"), (429, "retry"), (500, "retry"), (503, "retry"), (599, "retry"), (None, "retry"),
])
def test_each_answer_has_the_consequence_the_design_gives_it(status, outcome):
    assert push.classify(status) == outcome


def test_one_request_carries_what_a_push_service_needs_and_a_body_only_the_device_can_read(store, vapid):
    device = subscribe(store)
    service = FakeService([device])
    sub = push.Subscriptions(store).all()[0]
    now = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)
    assert push.send_one(sub, b'{"title":"Diya"}', vapid, SUBJECT, now, service) == ("accepted", 201)
    (request,) = service.requests
    headers = request["headers"]
    assert request["url"] == device.endpoint and request["timeout"] == push.REQUEST_TIMEOUT
    assert {k: v for k, v in headers.items() if k != "Authorization"} == {"Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": "3600", "Urgency": "normal"}
    verify_vapid(headers["Authorization"], vapid.public_b64u, "push.example.net", SUBJECT, now.timestamp())
    assert device.decrypt(request["body"]) == b'{"title":"Diya"}' and b"Diya" not in request["body"]


def test_a_stored_key_that_cannot_be_used_is_a_refusal_not_a_crash(vapid):
    sub = {"id": 1, "endpoint": "https://push.example.net/x", "p256dh": "!!", "auth": "!!"}
    assert push.send_one(sub, b"x", vapid, SUBJECT, datetime(2026, 10, 12, tzinfo=timezone.utc), FakeService()) == ("rejected", None)


def test_the_real_request_returns_a_status_or_none_and_follows_no_redirect(monkeypatch):
    import httpx

    seen = {}

    def fake_post(url, headers=None, content=None, timeout=None, follow_redirects=None):
        seen.update(url=url, timeout=timeout, follow_redirects=follow_redirects, content=content)
        return httpx.Response(201)

    monkeypatch.setattr(httpx, "post", fake_post)
    assert push.post_https("https://push.example.net/x", {"a": "b"}, b"body", 7.0) == 201
    assert seen == {"url": "https://push.example.net/x", "timeout": 7.0, "follow_redirects": False, "content": b"body"}

    def broken(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", broken)
    assert push.post_https("https://push.example.net/x", {}, b"", 1.0) is None

    def bad_url(*args, **kwargs):
        raise httpx.InvalidURL("bad")

    monkeypatch.setattr(httpx, "post", bad_url)
    assert push.post_https("https://push.example.net/x", {}, b"", 1.0) is None


# ---- a pass of sending -----------------------------------------------------------------------------------------------------------

def run_pass(store, config, service, now=NOW, **kwargs):
    lines = []
    report = push.deliver(store, config, now, say=lines.append, post=service, **kwargs)
    return report, lines


def test_with_no_device_nothing_is_sent_and_nothing_is_recorded(store, config):
    remind(store, "call the bank", NOW - timedelta(minutes=5))
    service = FakeService()
    assert run_pass(store, config, service)[0] == push.Report(0, 0, 0, 0)
    assert service.requests == [] and diya_events.Deliveries(store, "push").told() == set()
    assert not os.path.exists(config.push_vapid_path)


def test_a_due_reminder_is_sent_once_with_the_text_hidden_and_never_again(store, config):
    device = subscribe(store)
    due = remind(store, "call the bank", NOW - timedelta(minutes=5))
    service = FakeService([device])
    report, lines = run_pass(store, config, service)
    assert report == push.Report(1, 1, 0, 0)
    assert service.messages() == [{"title": "Diya", "body": "A reminder is due", "tag": f"reminder:{due}"}]
    assert diya_events.Deliveries(store, "push").told() == {f"reminder:{due}"}
    assert run_pass(store, config, service)[0] == push.Report(0, 0, 0, 0) and len(service.requests) == 1


def test_the_words_are_in_the_message_only_when_the_setting_says_so(store, config):
    device = subscribe(store)
    remind(store, "call the bank", datetime(2026, 10, 12, 9, 55))
    service = FakeService([device])
    run_pass(store, dataclasses.replace(config, push_show_text=True), service)
    assert service.messages()[0]["body"] == "call the bank" and service.messages()[0]["title"].startswith("Diya: ")


def test_a_message_goes_to_every_device_and_is_told_when_one_of_them_accepted_it(store, config):
    first, second = subscribe(store, path="/one"), subscribe(store, path="/two")
    remind(store, "x", NOW - timedelta(minutes=5))
    service = FakeService([first, second], statuses=(lambda url: 201 if url.endswith("/one") else 503,))
    report, lines = run_pass(store, config, service)
    assert report == push.Report(1, 1, 0, 0) and len(service.requests) == 2
    assert diya_events.Deliveries(store, "push").told() == {"reminder:1"}
    assert any("device 2" in line for line in lines) and push.Subscriptions(store).all()[1]["failures"] == 0  # a retry is not a refusal


@pytest.mark.parametrize("status", [None, 429, 500, 503])
def test_when_no_device_accepts_nothing_is_recorded_and_the_next_pass_tries_again(store, config, status):
    device = subscribe(store)
    remind(store, "x", NOW - timedelta(minutes=5))
    failing = FakeService([device], statuses=(status,))
    assert run_pass(store, config, failing)[0] == push.Report(1, 0, 1, 0)
    assert diya_events.Deliveries(store, "push").told() == set() and len(push.Subscriptions(store).all()) == 1
    working = FakeService([device])
    assert run_pass(store, config, working)[0] == push.Report(1, 1, 0, 0)


def test_a_device_the_service_says_is_gone_is_removed_and_the_message_is_left_for_the_others(store, config):
    gone, alive = subscribe(store, path="/gone"), subscribe(store, path="/alive")
    remind(store, "x", NOW - timedelta(minutes=5))
    service = FakeService([gone, alive], statuses=(lambda url: 410 if url.endswith("/gone") else 201,))
    report, lines = run_pass(store, config, service)
    assert report == push.Report(1, 1, 0, 1) and [d["endpoint"] for d in push.Subscriptions(store).all()] == [alive.endpoint]
    assert any("is gone" in line and "removed" in line for line in lines)
    run_pass(store, config, service)
    assert len(service.requests) == 2  # the removed device is not asked again, and the delivered message is not sent again


def test_a_device_that_refuses_is_counted_once_a_pass_and_paused_after_five_passes_never_removed(store, config):
    device = subscribe(store)
    service = FakeService([device], statuses=(403,))
    for n in range(3):
        remind(store, f"x{n}", NOW - timedelta(minutes=5))  # the earlier ones are still waiting, so later passes send several messages
        run_pass(store, config, service)
    assert push.Subscriptions(store).all()[0]["failures"] == 3
    for n in range(2):
        run_pass(store, config, service)
    assert push.Subscriptions(store).all()[0]["failures"] == push.MAX_FAILURES
    asked = len(service.requests)
    report, lines = run_pass(store, config, service)
    assert len(service.requests) == asked and report.sent == 0 and report.removed == 0 and len(push.Subscriptions(store).all()) == 1
    assert any("device 1 is paused after 5 refusals" in line for line in lines)


def test_a_paused_device_does_not_hold_up_the_others_and_a_test_that_works_resumes_it(store, config):
    paused, other = subscribe(store, path="/paused"), subscribe(store, path="/other")
    conn = store.connect()
    conn.execute("UPDATE push_subscriptions SET failures = ? WHERE id = 1", (push.MAX_FAILURES,))
    conn.commit()
    conn.close()
    remind(store, "x", NOW - timedelta(minutes=5))
    service = FakeService([paused, other])
    assert run_pass(store, config, service)[0].sent == 1 and [r["url"] for r in service.requests] == [other.endpoint]
    assert push.send_test(store, config, post=FakeService([paused, other])) == (2, 0)
    assert [row["failures"] for row in push.Subscriptions(store).all()] == [0, 0]


def test_a_test_that_is_refused_counts_and_one_the_service_says_is_gone_removes_the_device(store, config):
    refused, gone = subscribe(store, path="/refused"), subscribe(store, path="/gone")
    service = FakeService([refused, gone], statuses=(lambda url: 403 if url.endswith("/refused") else 410,))
    assert push.send_test(store, config, post=service) == (0, 2)
    assert [(row["id"], row["failures"]) for row in push.Subscriptions(store).all()] == [(1, 1)]


def test_when_every_device_is_paused_the_messages_wait_and_nothing_is_recorded(store, config):
    subscribe(store)
    conn = store.connect()
    conn.execute("UPDATE push_subscriptions SET failures = ?", (push.MAX_FAILURES,))
    conn.commit()
    conn.close()
    remind(store, "x", NOW - timedelta(minutes=5))
    service = FakeService()
    assert run_pass(store, config, service)[0] == push.Report(1, 0, 1, 0) and service.requests == [] and diya_events.Deliveries(store, "push").told() == set()


def test_a_flood_is_four_messages_and_one_that_stands_for_the_rest(store, config):
    device = subscribe(store)
    for n in range(7):
        remind(store, f"x{n}", NOW - timedelta(minutes=10 - n))
    service = FakeService([device])
    assert run_pass(store, config, service)[0] == push.Report(5, 5, 0, 0)
    bodies = [m["body"] for m in service.messages()]
    assert bodies == ["A reminder is due"] * 4 + ["3 more reminders are due. Open the Reminders page to see them."]
    assert len(diya_events.Deliveries(store, "push").told()) == 7


def test_at_most_twelve_messages_in_an_hour_and_the_rest_wait(store, config):
    device = subscribe(store)
    service = FakeService([device])
    for n in range(14):
        remind(store, f"x{n}", NOW - timedelta(minutes=1))
        run_pass(store, config, service, now=NOW + timedelta(minutes=n))  # one new reminder each minute: one message each
    assert len(service.requests) == 12
    report, lines = run_pass(store, config, service, now=NOW + timedelta(minutes=20))
    assert report.sent == 0 and any("12 messages in the last hour" in line for line in lines)
    report, _ = run_pass(store, config, service, now=NOW + timedelta(hours=1, minutes=1))
    assert report.sent >= 1  # the hour has gone by; the two that waited are sent


def test_a_pass_makes_at_most_twenty_requests_and_never_sends_a_message_to_only_some_devices(store, config):
    devices = [subscribe(store, path=f"/d{n}") for n in range(10)]
    for n in range(3):
        remind(store, f"x{n}", NOW - timedelta(minutes=1))
    service = FakeService(devices)
    report, lines = run_pass(store, config, service)
    assert len(service.requests) == 20 and report.sent == 2 and any("20 requests in one pass" in line for line in lines)
    counts = {}
    for request in service.requests:
        counts[request["url"]] = counts.get(request["url"], 0) + 1
    assert set(counts.values()) == {2}
    assert len(diya_events.Deliveries(store, "push").told()) == 2


def test_a_question_an_action_and_the_day_wait_for_the_morning_but_a_reminder_does_not(store, config):
    device = subscribe(store)
    night = datetime(2026, 10, 12, 23, 0)
    remind(store, "alarm", night - timedelta(minutes=5))
    conn = store.connect()
    conn.execute("INSERT INTO actions (kind, args, args_hash, summary, status, created_at, expires_at) VALUES ('k', '{}', 'h', 's', 'pending', '2026-10-12T00:00:00Z', ?)", (diya_time.iso_of_local(night + timedelta(days=1)),))
    conn.commit()
    conn.close()
    service = FakeService([device])
    assert run_pass(store, config, service, now=night)[0].sent == 1 and [m["tag"] for m in service.messages()] == ["reminder:1"]
    assert run_pass(store, config, service, now=datetime(2026, 10, 13, 7, 0))[0].sent == 1 and service.messages()[-1]["body"] == "An action is waiting for your approval."


def test_the_day_is_sent_when_it_is_set_and_something_is_due(store, config):
    device = subscribe(store)
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    service = FakeService([device])
    assert run_pass(store, dataclasses.replace(config, push_day_at="09:30"), service, now=datetime(2026, 10, 12, 9, 40))[0].sent == 1
    assert service.messages() == [{"title": "Diya", "body": "Your day is ready.", "tag": "day:2026-10-12"}]


def test_a_dry_run_says_what_it_would_push_and_sends_and_records_nothing(store, config):
    device = subscribe(store)
    remind(store, "secret errand", NOW - timedelta(minutes=5))
    service = FakeService([device])
    report, lines = run_pass(store, dataclasses.replace(config, push_show_text=True), service, dry_run=True)
    assert report == push.Report(1, 0, 0, 0) and service.requests == [] and lines == ["would push: Diya: " + lines[0].split("Diya: ", 1)[1]] and "secret errand" in lines[0]
    assert diya_events.Deliveries(store, "push").told() == set() and not os.path.exists(config.push_vapid_path)


def test_a_pass_with_nothing_to_say_does_not_even_make_a_key(store, config):
    subscribe(store)
    assert run_pass(store, config, FakeService())[0] == push.Report(0, 0, 0, 0) and not os.path.exists(config.push_vapid_path)


def test_a_pass_refuses_when_push_is_off(store, config):
    with pytest.raises(push.PushError, match="DIYA_PUSH=1"):
        push.deliver(store, dataclasses.replace(config, push=False), NOW, post=FakeService())


def test_nothing_said_by_a_pass_holds_an_endpoint_a_key_or_a_messages_words(store, config):
    secret_path = "/send/SECRETPATHtoken123"
    devices = [subscribe(store, path=secret_path), subscribe(store, path="/other")]
    remind(store, "private errand words", NOW - timedelta(minutes=5))
    lines = []
    for statuses in ((503,), (410,), (400,), (201,)):
        remind(store, "more private errand words", NOW - timedelta(minutes=4))
        push.deliver(store, dataclasses.replace(config, push_show_text=True), NOW, say=lines.append, post=FakeService(devices, statuses=statuses))
    text = "\n".join(lines)
    vapid = push.Vapid.load_or_create(config.push_vapid_path)
    for forbidden in (secret_path, "SECRETPATH", "private errand", b64u(devices[0].public), vapid.public_b64u, "push.example.net"):
        assert forbidden not in text
    assert lines  # and it did say something


def test_the_test_message_says_nothing_about_the_person_and_records_nothing(store, config):
    first, second = subscribe(store, path="/one"), subscribe(store, path="/two")
    service = FakeService([first, second], statuses=(lambda url: 201 if url.endswith("/one") else 500,))
    assert push.send_test(store, config, post=service) == (1, 1)
    assert service.messages()[0] == {"title": "Diya", "body": "Notifications work here. This says nothing about you.", "tag": "test"}
    assert diya_events.Deliveries(store, "push").told() == set()


def test_the_test_message_refuses_when_push_is_off(store, config):
    with pytest.raises(push.PushError):
        push.send_test(store, dataclasses.replace(config, push=False), post=FakeService())


# ---- readiness and the command line -----------------------------------------------------------------------------------------------

def test_readiness_names_what_is_missing(config, monkeypatch):
    assert push.readiness(config) is None
    assert "DIYA_PUSH=1" in push.readiness(dataclasses.replace(config, push=False))
    monkeypatch.setattr(push, "_crypto", lambda: (_ for _ in ()).throw(push.PushError('Web Push needs the cryptography package: run pip install ".[push]"')))
    assert push.readiness(config) == 'Web Push needs the cryptography package: run pip install ".[push]"'


def test_status_says_how_many_devices_and_that_the_notifier_sends(store, config, tmp_path):
    out = []
    cfg = dataclasses.replace(config, db_path=str(tmp_path / "p.db"))
    subscribe(store)
    assert push.main(["--status"], config=cfg, out=_Out(out)) == push.EXIT_OK and "1 device(s) subscribed" in "".join(out) and "diya_notify.py" in "".join(out)


class _Out:
    def __init__(self, parts):
        self.parts = parts

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass


def test_the_command_line_refuses_when_push_is_off_and_when_the_settings_are_bad(config, tmp_path, monkeypatch):
    out = []
    assert push.main(["--status"], config=dataclasses.replace(config, push=False), out=_Out(out)) == push.EXIT_UNUSABLE and "DIYA_PUSH=1" in "".join(out)
    monkeypatch.setenv("DIYA_PUSH", "maybe")
    out.clear()
    assert push.main(["--status"], out=_Out(out)) == push.EXIT_UNUSABLE and "diya_push:" in "".join(out)


def test_the_public_key_is_printed_and_is_the_one_in_the_key_file(config, tmp_path):
    out = []
    cfg = dataclasses.replace(config, db_path=str(tmp_path / "p.db"))
    assert push.main(["--public-key"], config=cfg, out=_Out(out)) == push.EXIT_OK
    assert "".join(out).strip() == push.Vapid.load_or_create(cfg.push_vapid_path).public_b64u


def test_the_test_command_needs_a_device_and_reports_how_many_accepted(store, config, tmp_path):
    cfg = dataclasses.replace(config, db_path=str(tmp_path / "p.db"))
    out = []
    assert push.main(["--test"], config=cfg, out=_Out(out)) == push.EXIT_UNUSABLE and "no device is subscribed" in "".join(out)
    device = subscribe(store)
    out.clear()
    assert push.main(["--test"], config=cfg, out=_Out(out), post=FakeService([device])) == push.EXIT_OK and "1 accepted, 0 not" in "".join(out)
    out.clear()
    assert push.main(["--test"], config=cfg, out=_Out(out), post=FakeService([device], statuses=(500,))) == push.EXIT_SOME_FAILED and "0 accepted, 1 not" in "".join(out)


def test_two_actions_at_once_are_a_usage_error(config):
    assert push.main(["--status", "--test"], config=config, out=_Out([])) == 2


def test_importing_the_module_does_nothing(run_python):
    done = run_python("import diya_push, os; print(sorted(n for n in os.listdir('.') if n != '__pycache__'))")
    assert done.returncode == 0 and done.stdout.strip() == "[]"


def test_without_the_cryptography_package_the_error_says_what_to_install(monkeypatch):
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("no cryptography")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    with pytest.raises(push.PushError, match=r'pip install "\.\[push\]"'):
        push._crypto()


# ---- the edges that mutation found --------------------------------------------------------------------------------------------------

def compressed(device):
    from cryptography.hazmat.primitives import serialization

    return device.private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)


def test_a_compressed_key_is_refused_by_the_encryption_and_by_a_subscription():
    device = Device()
    short = compressed(device)
    assert len(short) == 33
    with pytest.raises(push.PushError):
        push.encrypt(b"x", short, device.auth)
    with pytest.raises(push.InvalidSubscription):
        push.validate_subscription(device.endpoint, b64u(short), b64u(device.auth))


@pytest.mark.parametrize("size", [64, 66, 1, 130])
def test_a_key_that_starts_like_a_point_but_is_the_wrong_size_is_refused(size):
    key = b"\x04" + b"\x01" * (size - 1)
    with pytest.raises(push.InvalidSubscription):
        push.validate_subscription("https://push.example.net/x", b64u(key), b64u(b"0123456789abcdef"))
    with pytest.raises(push.PushError):
        push.encrypt(b"x", key, b"0123456789abcdef")


def test_nothing_but_padding_or_nothing_at_all_is_not_a_key():
    for text in ("=", "==", "===="):
        with pytest.raises(ValueError):
            push.unb64u(text)
        with pytest.raises(push.InvalidSubscription):
            push.validate_subscription("https://push.example.net/x", text, text)


def test_an_endpoint_may_be_exactly_2048_characters_and_not_one_more():
    base = "https://push.example.net/"
    assert len(push.validate_subscription(**good(endpoint=base + "a" * (2048 - len(base))))[0]) == 2048
    with pytest.raises(push.InvalidSubscription):
        push.validate_subscription(**good(endpoint=base + "a" * (2049 - len(base))))


@pytest.mark.parametrize("endpoint", ["", "https://", "https://./x", "https://push.example.net./x", "https://push.example.net_x/y", "https://push.exam_ple.net/x", "https://push.example.n/x",
                                      "https://:pw@push.example.net/x", "https://@push.example.net/x", "https://a:b@push.example.net/x", "https://push..example.net/x",
                                      "https://-push.example.net/x", "https://push-.example.net/x", "https://example/x", "https://example.123/x", "https://1.2.3.4.5/x"])
def test_more_endpoints_that_are_not_public_host_names_are_refused(endpoint):
    with pytest.raises(push.InvalidSubscription):
        push.validate_subscription(**good(endpoint=endpoint))


@pytest.mark.parametrize("endpoint", ["https://push.example.net/x", "https://a.bc/x", "https://xn--push-9ra.example.net/x", "https://1.2.3.4.example.net/x", "https://my-push.example-net.org/x"])
def test_more_endpoints_that_are_public_host_names_are_accepted(endpoint):
    assert push.validate_subscription(**good(endpoint=endpoint))[0] == endpoint


def test_the_time_a_device_subscribed_is_kept_in_utc(store):
    device = Device()
    sub = device.subscription
    ist = timezone(timedelta(hours=5, minutes=30))
    push.Subscriptions(store).add(sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"], datetime(2026, 10, 12, 9, 30, tzinfo=ist))
    assert push.Subscriptions(store).all()[0]["created_at"] == "2026-10-12T04:00:00Z"


def test_a_refusal_is_counted_for_that_device_and_no_other(store, config):
    fine, refused = subscribe(store, path="/fine"), subscribe(store, path="/refused")  # the device that works is asked first, so a refusal after it is the last thing written
    remind(store, "x", NOW - timedelta(minutes=5))
    run_pass(store, config, FakeService([refused, fine], statuses=(lambda url: 403 if url.endswith("/refused") else 201,)))
    assert [(row["id"], row["failures"]) for row in push.Subscriptions(store).all()] == [(1, 0), (2, 1)]


def test_the_timeout_and_the_other_limits_are_what_the_design_says():
    assert (push.REQUEST_TIMEOUT, push.MAX_REQUESTS_PER_PASS, push.MAX_PER_HOUR, push.MAX_FAILURES, push.MAX_SUBSCRIPTIONS) == (10.0, 20, 12, 5, 10)
    assert (push.MAX_PAYLOAD_BYTES, push.TTL_SECONDS, push.MAX_ENDPOINT_CHARS, push.TOKEN_LIFETIME) == (3993, 3600, 2048, timedelta(hours=12))


def test_non_ascii_words_survive_the_trip(store, config):
    device = subscribe(store)
    remind(store, "café ☕ 你好", datetime(2026, 10, 12, 9, 55))
    service = FakeService([device])
    run_pass(store, dataclasses.replace(config, push_show_text=True), service)
    assert service.messages()[0]["body"] == "café ☕ 你好"


def test_a_waiting_question_is_pushed_only_when_memory_raises_questions(store, config):
    import diya_questions
    from diya_memory import Memory

    device = subscribe(store)
    memory = Memory(store)
    fact = memory.add_candidate("private thing", batch_first=1, batch_last=1, position=0, model="m", extracted_at="2026-10-11T03:30:00+00:00", raw="- x")
    memory.set_flags(fact, ["ask:sensitive:model_private"], "system")
    diya_questions.Questions(store, None).refill(memory, NOW)
    service = FakeService([device])
    assert run_pass(store, dataclasses.replace(config, auto_memory=False), service)[0].sent == 0 and service.requests == []
    assert run_pass(store, dataclasses.replace(config, auto_memory=True), service)[0].sent == 1
    assert service.messages() == [{"title": "Diya", "body": "Diya has a question for you.", "tag": "question:1"}]


def test_the_day_message_waits_for_its_minute(store, config):
    device = subscribe(store)
    remind(store, "dentist", datetime(2026, 10, 12, 16, 0))
    service = FakeService([device])
    cfg = dataclasses.replace(config, push_day_at="09:30")
    assert run_pass(store, cfg, service, now=datetime(2026, 10, 12, 9, 15))[0].sent == 0
    assert run_pass(store, cfg, service, now=datetime(2026, 10, 12, 9, 30))[0].sent == 1


def test_a_pass_with_nine_devices_sends_two_messages_and_stops_before_a_third_would_go_over_twenty(store, config):
    devices = [subscribe(store, path=f"/d{n}") for n in range(9)]
    for n in range(3):
        remind(store, f"x{n}", NOW - timedelta(minutes=1))
    service = FakeService(devices)
    report, lines = run_pass(store, config, service)
    assert len(service.requests) == 18 and report.sent == 2 and report.failed == 0


def test_devices_that_are_gone_free_up_the_cap_for_the_messages_after_them(store, config):
    devices = [subscribe(store, path=f"/d{n}") for n in range(8)]
    for n in range(3):
        remind(store, f"x{n}", NOW - timedelta(minutes=1))
    gone = {devices[0].endpoint, devices[1].endpoint, devices[2].endpoint}
    service = FakeService(devices, statuses=(lambda url: 410 if url in gone else 201,))
    report, lines = run_pass(store, config, service)
    assert report == push.Report(3, 3, 0, 3) and len(service.requests) == 8 + 5 + 5  # three messages, the third allowed because five devices are left


def test_a_gone_device_is_asked_once_and_counted_once_however_many_messages_follow(store, config):
    gone, alive = subscribe(store, path="/gone"), subscribe(store, path="/alive")
    for n in range(3):
        remind(store, f"x{n}", NOW - timedelta(minutes=1))
    service = FakeService([gone, alive], statuses=(lambda url: 410 if url.endswith("/gone") else 201,))
    report, lines = run_pass(store, config, service)
    assert report.removed == 1 and report.sent == 3 and [r["url"] for r in service.requests].count(gone.endpoint) == 1 and len([l for l in lines if "is gone" in l]) == 1


def test_an_accepted_message_notes_the_time_on_the_device_and_clears_its_refusals(store, config):
    device = subscribe(store)
    conn = store.connect()
    conn.execute("UPDATE push_subscriptions SET failures = 3")
    conn.commit()
    conn.close()
    remind(store, "x", NOW - timedelta(minutes=5))
    run_pass(store, config, FakeService([device]))
    (row,) = push.Subscriptions(store).all()
    assert row["failures"] == 0 and row["last_ok_at"] == diya_events.utc_of_local(NOW).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_refusal_and_a_retry_are_each_said_in_their_own_words(store, config):
    first, second = subscribe(store, path="/refuses"), subscribe(store, path="/retries")
    remind(store, "x", NOW - timedelta(minutes=5))
    service = FakeService([first, second], statuses=(lambda url: 403 if url.endswith("/refuses") else 503,))
    report, lines = run_pass(store, config, service)
    assert "could not push to device 1: the push service said 403" in lines and "could not push to device 2: no usable answer (status 503)" in lines


def test_two_actions_at_once_are_a_usage_error_with_the_parsers_own_words(config, capsys):
    assert push.main(["--status", "--test"], config=config, out=_Out([])) == 2
    assert "not allowed with argument" in capsys.readouterr().err
    assert push.main(["--public-key", "--status"], config=config, out=_Out([])) == 2


def test_help_is_a_success(config):
    assert push.main(["--help"], config=config, out=_Out([])) == 0


def test_a_data_folder_that_cannot_be_made_is_one_line_and_exit_two(tmp_path, monkeypatch):
    blocker = tmp_path / "a-file"
    blocker.write_text("x")
    monkeypatch.setenv("DIYA_DATA_DIR", str(blocker / "inside"))
    monkeypatch.setenv("DIYA_PUSH", "1")
    monkeypatch.setenv("DIYA_PUSH_SUBJECT", SUBJECT)
    out = []
    assert push.main(["--status"], out=_Out(out)) == 2 and "".join(out).startswith("diya_push: ")


def test_the_data_folder_is_made_before_the_database_is_opened(config, tmp_path):
    folder = tmp_path / "new" / "data"
    cfg = dataclasses.replace(config, data_dir=str(folder), db_path=str(folder / "p.db"))
    out = []
    assert push.main(["--status"], config=cfg, out=_Out(out)) == 0 and folder.is_dir()


def test_a_database_that_cannot_be_opened_is_one_line_and_exit_two(config, tmp_path):
    cfg = dataclasses.replace(config, data_dir="", db_path=str(tmp_path))  # a folder where the database file should be
    out = []
    assert push.main(["--status"], config=cfg, out=_Out(out)) == 2 and "".join(out).startswith("diya_push: ")
