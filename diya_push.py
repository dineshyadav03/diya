"""Telling the phone by Web Push (docs/PUSH_DESIGN.md, unit P2): the encryption, the key, the subscriptions and one pass of sending.

    python diya_push.py --status       say whether push is ready and, if not, why not; sends nothing
    python diya_push.py --test         send one notification that says nothing about you to every subscribed device
    python diya_push.py --public-key   print the application server key (the public half) the browser subscribes with

Sending is one pass of diya_notify.py (the scheduled task the owner already has) when DIYA_PUSH=1; this file is what that pass calls, and what the UI's routes call.

The crypto is not written here: ECDH on P-256, ECDSA (ES256) and AES-128-GCM come from the `cryptography` package, an OPTIONAL dependency (`pip install ".[push]"`), and this file only
arranges them as RFC 8291 (message encryption), RFC 8188 (the aes128gcm coding) and RFC 8292 (VAPID) say. HKDF is the small `hmac` construction of RFC 5869.

Nothing here logs, prints or returns a subscription's endpoint (it is a bearer URL for pushing to that device), a key, or a message's words. Messages are made by diya_events.py.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import hmac
import json
import os
import re
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import diya_config
import diya_events
import diya_time
from diya_db import Store
from diya_memory import printable

MAX_PAYLOAD_BYTES = 3993  # RFC 8291: a push service must take 4,096 bytes of body, and the header is 86 of them
RECORD_SIZE = 4096
MAX_SUBSCRIPTIONS = 10
MAX_ENDPOINT_CHARS = 2048
MAX_FAILURES = 5  # consecutive passes in which a device refused Diya's request before it is paused (never removed: a wrong contact setting would otherwise cost every subscription)
MAX_PER_HOUR = 12  # messages accepted on this channel in a rolling hour
MAX_REQUESTS_PER_PASS = 20
REQUEST_TIMEOUT = 10.0
TOKEN_LIFETIME = timedelta(hours=12)  # RFC 8292: at most 24
TTL_SECONDS = 3600
EXIT_OK, EXIT_SOME_FAILED, EXIT_UNUSABLE = 0, 1, 2
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".home.arpa", ".corp", ".intranet")
# Names with at least two labels, the last of which is letters (or punycode): that is what keeps out every spelling of an IP address (127.1, 0x7f.1, 2130706433), since a resolver
# reads a name as an address only when its last part is a number.
_PUBLIC_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})")


class PushError(RuntimeError):
    """Something about Web Push cannot be done. The text is safe to show and to log: it never holds an endpoint, a key or a message."""


class InvalidSubscription(PushError):
    pass


# ---- the small pieces ------------------------------------------------------------------------------------------------------------

def b64u(data):
    """URL-safe base64 without padding, as every Web Push value is written."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text):
    """The bytes of URL-safe base64, padding optional. Anything else is a ValueError (the standard-alphabet characters + and / are not accepted, and neither is nothing at all)."""
    stripped = text.rstrip("=") if isinstance(text, str) else ""
    if not stripped or len(text) > 4096 or not all(ch.isascii() and (ch.isalnum() or ch in "-_") for ch in stripped):
        raise ValueError("not URL-safe base64")
    return base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4))


def hkdf_extract(salt, ikm):
    return hmac.new(salt, ikm, hashlib.sha256).digest()


def hkdf_expand(prk, info, length):
    """RFC 5869 HKDF-Expand with SHA-256, for the short outputs Web Push needs (at most 32 bytes)."""
    if not 0 < length <= 32:
        raise ValueError("HKDF-Expand here makes at most 32 bytes")
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def _crypto():
    """The pieces of `cryptography` this file uses, or a PushError that says what to install."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise PushError('Web Push needs the cryptography package: run pip install ".[push]"') from None
    return hashes, serialization, ec, decode_dss_signature, AESGCM


def _point(public_key):
    _, serialization, _, _, _ = _crypto()
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---- the message (RFC 8291 over RFC 8188) ----------------------------------------------------------------------------------------

def encrypt(payload, p256dh, auth, *, salt=None, as_private=None):
    """The body of a push request: `payload` (bytes) encrypted for the device whose public key is `p256dh` (65 bytes) and whose auth secret is `auth` (16 bytes).
    A fresh salt and a fresh key are made for every message; `salt` and `as_private` are only for tests."""
    _, _, ec, _, AESGCM = _crypto()
    if not isinstance(payload, bytes) or len(payload) > MAX_PAYLOAD_BYTES:
        raise PushError(f"a push payload is at most {MAX_PAYLOAD_BYTES} bytes")
    if len(p256dh) != 65 or len(auth) != 16:
        raise PushError("a subscription's key is 65 bytes and its auth secret 16")
    try:
        ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    except ValueError:
        raise PushError("a subscription's key is not a point on the curve") from None
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    as_public = _point(as_private.public_key())
    salt = os.urandom(16) if salt is None else salt
    if len(salt) != 16:
        raise PushError("the salt is 16 bytes")
    shared = as_private.exchange(ec.ECDH(), ua_public)
    ikm = hkdf_expand(hkdf_extract(auth, shared), b"WebPush: info\x00" + p256dh + as_public, 32)
    prk = hkdf_extract(salt, ikm)
    key = hkdf_expand(prk, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf_expand(prk, b"Content-Encoding: nonce\x00", 12)
    sealed = AESGCM(key).encrypt(nonce, payload + b"\x02", None)  # 0x02: the delimiter of the last (here the only) record
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public + sealed


# ---- the identity (RFC 8292) -----------------------------------------------------------------------------------------------------

class Vapid:
    """The key pair that identifies this Diya to push services. The private half is made once, kept in one file, and never returned or logged."""

    def __init__(self, private_key):
        self._private = private_key
        self.public = _point(private_key.public_key())
        self.public_b64u = b64u(self.public)

    @classmethod
    def load_or_create(cls, path):
        _, _, ec, _, _ = _crypto()
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as handle:
                    stored = json.load(handle)
                private = ec.derive_private_key(int.from_bytes(unb64u(stored["private"]), "big"), ec.SECP256R1())
                vapid = cls(private)
                if stored.get("public") != vapid.public_b64u:
                    raise ValueError("the stored public key is not the private key's")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise PushError(f"the push key file could not be read ({printable(type(exc).__name__)}); move it aside to make a new one, which every subscribed device must then renew") from None
            return vapid
        private = ec.generate_private_key(ec.SECP256R1())
        vapid = cls(private)
        record = {"private": b64u(private.private_numbers().private_value.to_bytes(32, "big")), "public": vapid.public_b64u,
                  "made": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # never overwrites a key that is there
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(record, handle)
        except OSError as exc:
            raise PushError(f"the push key could not be saved ({printable(type(exc).__name__)})") from None
        return vapid

    def token(self, endpoint, subject, now_utc):
        """A signed ES256 token (a JWT) for a request to `endpoint`'s push service, good for TOKEN_LIFETIME."""
        hashes, _, ec, decode_dss_signature, _ = _crypto()
        parts = urlsplit(endpoint)
        header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode("ascii"))
        claims = b64u(json.dumps({"aud": f"{parts.scheme}://{parts.hostname}", "exp": int((now_utc + TOKEN_LIFETIME).timestamp()), "sub": subject}, separators=(",", ":")).encode("utf-8"))
        r, s = decode_dss_signature(self._private.sign(f"{header}.{claims}".encode("ascii"), ec.ECDSA(hashes.SHA256())))
        return f"{header}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


# ---- subscriptions ---------------------------------------------------------------------------------------------------------------

def validate_subscription(endpoint, p256dh, auth):
    """(endpoint, p256dh, auth) as they will be stored, or InvalidSubscription. See docs/PUSH_DESIGN.md section 4 for why each rule is there."""
    if not isinstance(endpoint, str) or len(endpoint) > MAX_ENDPOINT_CHARS or any(ord(ch) < 33 or ord(ch) > 126 for ch in endpoint):
        raise InvalidSubscription("the endpoint must be a plain address of at most 2,048 characters")
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise InvalidSubscription("the endpoint is not a valid address") from None
    host = parts.hostname or ""  # already lower case; a name with a trailing dot is refused below
    if parts.scheme != "https" or "@" in parts.netloc or parts.fragment:
        raise InvalidSubscription("the endpoint must be an https address with no credentials or fragment")
    if port not in (None, 443):
        raise InvalidSubscription("the endpoint must use the standard https port")
    if not _PUBLIC_HOST.fullmatch(host) or host.endswith(_LOCAL_SUFFIXES):
        raise InvalidSubscription("the endpoint must be a public host name (not an IP address in any spelling, not a name on a private network)")
    try:
        key, secret = unb64u(p256dh), unb64u(auth)
    except ValueError:
        raise InvalidSubscription("the keys must be URL-safe base64") from None
    if key[0] != 4 or len(secret) != 16:  # an uncompressed point starts with 0x04, and one that is not 65 bytes long is not on the curve (checked below)
        raise InvalidSubscription("the key must be an uncompressed point and the auth secret 16 bytes")
    _, _, ec, _, _ = _crypto()
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), key)
    except ValueError:
        raise InvalidSubscription("the key is not a point on the curve") from None
    return endpoint, b64u(key), b64u(secret)


class Subscriptions:
    """The `push_subscriptions` table. The endpoint is never given out: `public()` shows the service's host name and nothing after it."""

    def __init__(self, store):
        self.store = store

    def add(self, endpoint, p256dh, auth, now_utc):
        endpoint, p256dh, auth = validate_subscription(endpoint, p256dh, auth)
        stamp = now_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = self.store.connect()
        try:
            known = conn.execute("SELECT id FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).fetchone()
            if known:
                conn.execute("UPDATE push_subscriptions SET p256dh = ?, auth = ?, failures = 0 WHERE id = ?", (p256dh, auth, known[0]))
                conn.commit()
                return known[0]
            if conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0] >= MAX_SUBSCRIPTIONS:
                raise InvalidSubscription(f"at most {MAX_SUBSCRIPTIONS} devices can be subscribed; remove one first")
            cursor = conn.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?)", (endpoint, p256dh, auth, stamp))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def all(self):
        """Every subscription with its endpoint, for the sender only."""
        conn = self.store.connect()
        try:
            rows = conn.execute("SELECT id, endpoint, p256dh, auth, created_at, last_ok_at, failures FROM push_subscriptions ORDER BY id").fetchall()
        finally:
            conn.close()
        return [dict(zip(("id", "endpoint", "p256dh", "auth", "created_at", "last_ok_at", "failures"), row)) for row in rows]

    def public(self):
        """What may be shown: the id, the push service's host name, when it was made and last worked, and how many refusals in a row."""
        return [{"id": row["id"], "service": urlsplit(row["endpoint"]).hostname, "created_at": row["created_at"], "last_ok_at": row["last_ok_at"], "failures": row["failures"]}
                for row in self.all()]

    def remove_endpoint(self, endpoint):
        conn = self.store.connect()
        try:
            removed = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,)).rowcount
            conn.commit()
        finally:
            conn.close()
        return bool(removed)

    def remove(self, subscription_id):
        conn = self.store.connect()
        try:
            removed = conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (subscription_id,)).rowcount
            conn.commit()
        finally:
            conn.close()
        return bool(removed)

    def mark_ok(self, subscription_id, now_utc):
        conn = self.store.connect()
        try:
            conn.execute("UPDATE push_subscriptions SET last_ok_at = ?, failures = 0 WHERE id = ?", (now_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), subscription_id))
            conn.commit()
        finally:
            conn.close()

    def mark_failed(self, subscription_id):
        """One more refusal in a row. Returns how many there now are; at MAX_FAILURES the sender pauses the device until a test succeeds or it subscribes again."""
        conn = self.store.connect()
        try:
            conn.execute("UPDATE push_subscriptions SET failures = failures + 1 WHERE id = ?", (subscription_id,))
            row = conn.execute("SELECT failures FROM push_subscriptions WHERE id = ?", (subscription_id,)).fetchone()
            conn.commit()
        finally:
            conn.close()
        return row[0] if row else 0


# ---- sending ---------------------------------------------------------------------------------------------------------------------

def post_https(url, headers, content, timeout):
    """POST and return the HTTP status, or None if there was no answer. No redirect is followed, and the body of the answer is never read into anything."""
    import httpx

    try:
        return httpx.post(url, headers=headers, content=content, timeout=timeout, follow_redirects=False).status_code
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return None


def classify(status):
    """What a push service's answer means for one subscription: accepted, gone (delete it), rejected (our request was wrong or it moved), or retry (later)."""
    if status in (200, 201, 202):
        return "accepted"
    if status in (404, 410):
        return "gone"
    if status is None or status in (408, 429) or status >= 500:
        return "retry"
    return "rejected"


def send_one(subscription, payload, vapid, subject, now_utc, post=post_https):
    """Send one message to one subscription. Returns (outcome, status): outcome is what classify says, or "retry" with status None for a request that could not be made."""
    try:
        body = encrypt(payload, unb64u(subscription["p256dh"]), unb64u(subscription["auth"]))
    except (PushError, ValueError):
        return "rejected", None
    headers = {
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDS),
        "Urgency": "normal",
        "Authorization": f"vapid t={vapid.token(subscription['endpoint'], subject, now_utc)}, k={vapid.public_b64u}",
    }
    status = post(subscription["endpoint"], headers, body, REQUEST_TIMEOUT)
    return classify(status), status


@dataclasses.dataclass(frozen=True)
class Report:
    events: int  # messages worth sending
    sent: int  # accepted by at least one device
    failed: int  # not accepted by any device; found again on the next pass
    removed: int  # subscriptions removed this pass (the push service said they are gone)


def readiness(config):
    """Why push cannot send, in one sentence safe to show, or None when it can."""
    if not config.push:
        return "Web Push is off (DIYA_PUSH=1 turns it on)"
    try:
        _crypto()
    except PushError as exc:
        return str(exc)
    return None


def payload_for(event):
    return json.dumps({"title": event.title, "body": event.body, "tag": event.keys[0]}, separators=(",", ":")).encode("utf-8")


def deliver(store, config, now_local=None, *, dry_run=False, say=print, post=post_https, vapid=None):
    """One pass of sending: every message worth sending (diya_events.pending) to every subscribed device, each recorded as told only after a device accepted it.
    `say(line)` is told counts and the words of nothing: never an endpoint, a key or a message."""
    problem = readiness(config)
    if problem:
        raise PushError(problem)
    now_local = datetime.now() if now_local is None else now_local
    now_utc = diya_events.utc_of_local(now_local)
    subscriptions = Subscriptions(store)
    everyone = subscriptions.all()
    if not everyone:
        return Report(0, 0, 0, 0)
    devices = [device for device in everyone if device["failures"] < MAX_FAILURES]
    deliveries = diya_events.Deliveries(store, "push")
    events = diya_events.pending(store, now_local, deliveries.told(), show_text=config.push_show_text, quiet=diya_time.parse_quiet(config.push_quiet),
                                 questions_on=config.auto_memory, day_at=diya_time.parse_day_at(config.push_day_at))
    if dry_run:
        for event in events:
            say(f"would push: {event.title} | {event.body}")
        return Report(len(events), 0, 0, 0)
    if not events:
        return Report(0, 0, 0, 0)
    for device in everyone:
        if device["failures"] >= MAX_FAILURES:
            say(f"push: device {device['id']} is paused after {MAX_FAILURES} refusals; sending a test (diya_push.py --test) resumes it when it works")
    if not devices:
        return Report(len(events), 0, len(events), 0)
    vapid = vapid or Vapid.load_or_create(config.push_vapid_path)
    sent = failed = removed = requests = 0
    gone, refused = set(), set()
    for event in events:
        if requests + len(devices) - len(gone) > MAX_REQUESTS_PER_PASS:  # a message goes to every device or to none this pass, never to some
            say(f"push: {MAX_REQUESTS_PER_PASS} requests in one pass; the rest wait for the next")
            break
        if deliveries.messages_since(now_utc - timedelta(hours=1)) >= MAX_PER_HOUR:
            say(f"push: {MAX_PER_HOUR} messages in the last hour; the rest wait for a later pass")
            break
        accepted = False
        for device in devices:
            if device["id"] in gone:
                continue
            requests += 1
            outcome, status = send_one(device, payload_for(event), vapid, config.push_subject, now_utc, post)
            if outcome == "accepted":
                accepted = True
                subscriptions.mark_ok(device["id"], now_utc)
            elif outcome == "gone":
                subscriptions.remove(device["id"])
                gone.add(device["id"])
                removed += 1
                say(f"push: device {device['id']} is gone (the push service said {status}); removed")
            elif outcome == "rejected":
                if device["id"] not in refused:  # one refusal a pass, however many messages it was sent
                    refused.add(device["id"])
                    subscriptions.mark_failed(device["id"])
                say(f"could not push to device {device['id']}: the push service said {status}")
            else:
                say(f"could not push to device {device['id']}: no usable answer (status {status})")
        if accepted:
            deliveries.record(event.keys, now_utc)
            sent += 1
        else:
            failed += 1
    return Report(len(events), sent, failed, removed)


def send_test(store, config, now_utc=None, post=post_https, vapid=None):
    """One notification that says nothing about the person, to every device (a paused one too: a test that works is what resumes it). Returns (devices that accepted it, devices
    that did not). Records no message as told; a device that accepts is cleared of its refusals, one that is refused is counted, one the service says is gone is removed."""
    problem = readiness(config)
    if problem:
        raise PushError(problem)
    now_utc = now_utc or datetime.now(timezone.utc)
    vapid = vapid or Vapid.load_or_create(config.push_vapid_path)
    payload = json.dumps({"title": "Diya", "body": "Notifications work here. This says nothing about you.", "tag": "test"}, separators=(",", ":")).encode("utf-8")
    ok = bad = 0
    subscriptions = Subscriptions(store)
    for device in subscriptions.all():  # a paused device too: a test that works is what resumes it
        outcome, _ = send_one(device, payload, vapid, config.push_subject, now_utc, post)
        if outcome == "accepted":
            subscriptions.mark_ok(device["id"], now_utc)
            ok += 1
        else:
            if outcome == "rejected":
                subscriptions.mark_failed(device["id"])
            elif outcome == "gone":
                subscriptions.remove(device["id"])
            bad += 1
    return ok, bad


# ---- the command line ------------------------------------------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(prog="diya_push.py", description="Telling the phone by Web Push.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="say whether push is ready and, if not, why not")
    group.add_argument("--test", action="store_true", help="send one notification that says nothing about you to every subscribed device")
    group.add_argument("--public-key", action="store_true", help="print the application server key the browser subscribes with")
    return parser


def main(argv=None, config=None, out=None, post=post_https):
    out = sys.stdout if out is None else out
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_UNUSABLE
    try:
        config = config or diya_config.load_config()
        diya_config.ensure_data_dir(config)
    except (diya_config.ConfigError, OSError) as exc:
        print(f"diya_push: {exc}", file=out)
        return EXIT_UNUSABLE
    problem = readiness(config)
    if problem:
        print(f"diya_push: {problem}", file=out)
        return EXIT_UNUSABLE
    try:
        store = Store(config.db_path)
        if args.public_key:
            print(Vapid.load_or_create(config.push_vapid_path).public_b64u, file=out)
            return EXIT_OK
        devices = Subscriptions(store).public()
        if args.test:
            if not devices:
                print("diya_push: no device is subscribed; open the Today page in the UI and choose Notify this device.", file=out)
                return EXIT_UNUSABLE
            ok, bad = send_test(store, config, post=post)
            print(f"Sent a test notification: {ok} accepted, {bad} not.", file=out)
            return EXIT_OK if not bad else EXIT_SOME_FAILED
        print(f"Web Push is ready. {len(devices)} device(s) subscribed; messages sent only by diya_notify.py when it runs.", file=out)
        return EXIT_OK
    except (PushError, sqlite3.Error) as exc:
        print(f"diya_push: {printable(exc, 200)}", file=out)
        return EXIT_UNUSABLE


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
