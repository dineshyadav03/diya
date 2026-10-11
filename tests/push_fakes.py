"""Stand-ins for the other end of a Web Push, written from the RFCs and not from diya_push.py (docs/PUSH_DESIGN.md, section 7).

`Device` is a browser's side: it makes the subscription (a key pair and an auth secret) and DECRYPTS what arrives, with HKDF from the `cryptography` package and not from the
code under test, so an encryption mistake in diya_push.py shows up as a failure to decrypt. `FakeService` is the push service: it takes the place of the HTTPS request, records
what was asked of it, answers with the statuses it is told to, and decrypts for the device that owns the endpoint. `verify_vapid` checks the Authorization header's signature.
"""
import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def point(public_key):
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def hkdf(salt, info, length, secret):
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(secret)


class Device:
    """A browser's subscription: its key pair and auth secret, and what it can read."""

    def __init__(self, host="push.example.net", path="/send/abc123", auth=b"0123456789abcdef"):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.public = point(self.private.public_key())
        self.auth = auth
        self.endpoint = f"https://{host}{path}"

    @property
    def subscription(self):
        """What PushSubscription.toJSON() gives."""
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64u(self.public), "auth": b64u(self.auth)}}

    def decrypt(self, body):
        """RFC 8291 section 3.4 and RFC 8188, for one record. Raises cryptography.exceptions.InvalidTag if anything was altered."""
        salt, record_size, id_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
        as_public = body[21:21 + id_length]
        sealed = body[21 + id_length:]
        assert record_size == 4096 and id_length == 65 and as_public[0] == 4 and len(sealed) <= record_size
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
        secret = self.private.exchange(ec.ECDH(), peer)
        ikm = hkdf(self.auth, b"WebPush: info\x00" + self.public + as_public, 32, secret)
        key = hkdf(salt, b"Content-Encoding: aes128gcm\x00", 16, ikm)
        nonce = hkdf(salt, b"Content-Encoding: nonce\x00", 12, ikm)
        plain = AESGCM(key).decrypt(nonce, sealed, None).rstrip(b"\x00")
        assert plain.endswith(b"\x02"), "the last record ends with the delimiter 0x02"
        return plain[:-1]

    def read(self, body):
        return json.loads(self.decrypt(body).decode("utf-8"))


def verify_vapid(header, public_b64u, endpoint_host, subject, now_ts):
    """Check an Authorization header of the form `vapid t=<jwt>, k=<key>`: the key is the one expected, the signature is ES256 over header.claims, and the claims say what RFC 8292 wants.
    Returns the claims."""
    scheme, _, rest = header.partition(" ")
    assert scheme == "vapid"
    fields = dict(part.strip().split("=", 1) for part in rest.split(","))
    assert fields["k"] == public_b64u
    head, claims, signature = fields["t"].split(".")
    assert json.loads(unb64u(head)) == {"typ": "JWT", "alg": "ES256"}
    raw = unb64u(signature)
    assert len(raw) == 64
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(public_b64u))
    public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), f"{head}.{claims}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
    decoded = json.loads(unb64u(claims))
    assert decoded["aud"] == f"https://{endpoint_host}" and decoded["sub"] == subject
    assert 0 < decoded["exp"] - now_ts <= 24 * 3600
    return decoded


class FakeService:
    """The push service. `statuses` is what it answers, in order (the last one repeats); an entry may be a status or a callable(endpoint) -> status. None is "no answer"."""

    def __init__(self, devices=(), statuses=(201,)):
        self.devices = {device.endpoint: device for device in devices}
        self.statuses = list(statuses)
        self.requests = []

    def __call__(self, url, headers, content, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "body": content, "timeout": timeout})
        entry = self.statuses[min(len(self.requests) - 1, len(self.statuses) - 1)]
        return entry(url) if callable(entry) else entry

    def messages(self, endpoint=None):
        """What each device (or one device) was sent, decrypted, oldest first."""
        return [self.devices[r["url"]].read(r["body"]) for r in self.requests if endpoint in (None, r["url"])]
