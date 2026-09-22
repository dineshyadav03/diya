"""Request body-size limits: the API rejects an over-large body with 413, before any route -- or
the model -- ever sees it. The transcription endpoint gets its own, larger limit, since audio
uploads are legitimately bigger than a chat message.

The first half tests BodyLimitMiddleware directly at the ASGI level: that is the only way to
control what a client *declares* (Content-Length) separately from what it actually *sends*, which
is exactly the gap a naive header-only check would miss. The second half checks the same behaviour
end to end, through the real app.
"""
import asyncio
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from diya_config import ConfigError, load_config
from fakes import FakeClient, text_reply

LOCAL = "https://localhost"


# --- the middleware itself --------------------------------------------------------------------

def make_receive(chunks):
    """An ASGI receive() that yields `chunks` (each an (bytes, more_body) pair) as separate
    http.request messages, then reports a disconnect if asked again."""
    queue = list(chunks) + [None]

    async def receive():
        item = queue.pop(0)
        if item is None:
            return {"type": "http.disconnect"}
        body, more_body = item
        return {"type": "http.request", "body": body, "more_body": more_body}

    return receive


class RecordingApp:
    """A minimal downstream ASGI app: reads its whole body, records it, and answers 200."""

    def __init__(self):
        self.calls = 0
        self.body = None

    async def __call__(self, scope, receive, send):
        self.calls += 1
        chunks = []
        more_body = True
        while more_body:
            message = await receive()
            chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        self.body = b"".join(chunks)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def run(middleware, path="/api/chat", headers=None, chunks=()):
    scope = {
        "type": "http", "path": path, "method": "POST",
        "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()],
    }
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, make_receive(chunks), send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body


def test_a_body_within_the_limit_reaches_the_app_unchanged():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=100)
    status, _ = run(mw, chunks=[(b"hello", False)])
    assert (status, app.body, app.calls) == (200, b"hello", 1)


def test_a_body_split_across_several_chunks_is_reassembled_before_the_app_sees_it():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=100)
    status, _ = run(mw, chunks=[(b"hel", True), (b"l", True), (b"o", False)])
    assert (status, app.body) == (200, b"hello")


def test_an_empty_body_is_fine():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=100)
    status, _ = run(mw, chunks=[(b"", False)])
    assert (status, app.body) == (200, b"")


def test_a_body_exactly_at_the_limit_is_allowed():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=5)
    status, _ = run(mw, chunks=[(b"x" * 5, False)])
    assert (status, app.body) == (200, b"x" * 5)


def test_a_declared_content_length_over_the_limit_is_rejected_before_the_app_ever_runs():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=10)
    status, body = run(mw, headers={"content-length": "999"}, chunks=[(b"x" * 999, False)])
    assert status == 413 and app.calls == 0
    assert b"too large" in body and b"10" in body


def test_a_content_length_that_overstates_the_real_body_is_refused_up_front_anyway():
    """A declared size beyond the limit is refused immediately -- even though what actually
    follows here would have fit -- because trusting it enough to find that out is the risk."""
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=10)
    status, _ = run(mw, headers={"content-length": "999999"}, chunks=[(b"ok", False)])
    assert status == 413 and app.calls == 0


def test_a_body_that_exceeds_the_limit_with_no_content_length_header_is_also_rejected():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=10)
    status, _ = run(mw, chunks=[(b"x" * 5, True), (b"y" * 6, False)])  # no Content-Length at all
    assert status == 413 and app.calls == 0


def test_a_content_length_that_understates_the_real_body_does_not_help_it_through():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=10)
    status, _ = run(mw, headers={"content-length": "3"}, chunks=[(b"x" * 3, True), (b"y" * 20, False)])
    assert status == 413 and app.calls == 0


def test_reading_stops_as_soon_as_the_limit_is_crossed_not_after_the_whole_body():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=10)
    # a body that would take many more chunks to finish -- the middleware must not read them all
    chunks = [(b"x", True)] * 5 + [(b"y", True)] * 1000
    status, _ = run(mw, chunks=chunks)
    assert status == 413 and app.calls == 0


def test_a_malformed_content_length_does_not_crash_the_middleware():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=10)
    status, _ = run(mw, headers={"content-length": "not-a-number"}, chunks=[(b"ok", False)])
    assert (status, app.body) == (200, b"ok")


def test_a_path_in_limit_overrides_gets_its_own_limit_others_keep_the_default():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=5, limit_overrides={"/api/transcribe": 100})
    status, _ = run(mw, path="/api/transcribe", chunks=[(b"x" * 50, False)])
    assert (status, app.body) == (200, b"x" * 50)
    status, _ = run(mw, path="/api/chat", chunks=[(b"x" * 50, False)])
    assert status == 413


def test_non_http_scopes_are_not_touched():
    app = RecordingApp()
    mw = diya_web.BodyLimitMiddleware(app, default_limit=1)

    async def noop_send(message):
        pass

    async def go():
        await mw({"type": "lifespan"}, make_receive([]), noop_send)

    asyncio.run(go())
    assert app.calls == 1  # passed straight through, not read or buffered by us


# --- through the real app -----------------------------------------------------------------------

class FakeTranscriber:
    def __init__(self):
        self.calls = []

    def transcribe(self, path):
        self.calls.append(path)
        return "ok"


def app_for(env=None, tmp_path=None, transcriber=None):
    config = load_config(env or {})
    config = dataclasses.replace(
        config, db_path=str(tmp_path / "b.db"), profile_path=str(tmp_path / "b_profile.txt")
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 20))
    app = diya_web.create_app(config, agent, transcriber=transcriber or FakeTranscriber())
    return TestClient(app, base_url=LOCAL), agent


def test_the_default_limits_are_generous_enough_for_ordinary_use():
    config = load_config({})
    assert config.max_body_bytes == 1_000_000
    assert config.max_transcribe_bytes == 25_000_000
    assert config.max_transcribe_bytes > config.max_body_bytes


def test_an_ordinary_chat_message_is_unaffected(tmp_path):
    client, _ = app_for(tmp_path=tmp_path)
    assert client.post("/api/chat", json={"message": "hello"}).status_code == 200


def test_a_chat_message_over_the_configured_limit_gets_413_not_the_agent(tmp_path):
    client, agent = app_for({"DIYA_MAX_BODY_BYTES": "200"}, tmp_path)
    response = client.post("/api/chat", json={"message": "x" * 500})
    assert response.status_code == 413
    assert client.get("/api/threads").json() == {"threads": []}  # nothing was created


def test_a_chat_message_at_the_limit_still_works(tmp_path):
    client, _ = app_for({"DIYA_MAX_BODY_BYTES": "200"}, tmp_path)
    prefix, suffix = b'{"message": "', b'"}'
    body = prefix + b"x" * (200 - len(prefix) - len(suffix)) + suffix
    assert len(body) == 200
    response = client.post(
        "/api/chat", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 200
    response = client.post(
        "/api/chat", content=body + b" ", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413


def test_transcribe_accepts_a_file_bigger_than_the_general_limit(tmp_path):
    client, _ = app_for({"DIYA_MAX_BODY_BYTES": "200", "DIYA_MAX_TRANSCRIBE_BYTES": "50000"}, tmp_path)
    response = client.post(
        "/api/transcribe", files={"audio": ("clip.webm", b"a" * 10_000, "audio/webm")}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "ok"}


def test_transcribe_still_has_its_own_bound(tmp_path):
    client, _ = app_for({"DIYA_MAX_TRANSCRIBE_BYTES": "1000"}, tmp_path)
    response = client.post(
        "/api/transcribe", files={"audio": ("clip.webm", b"a" * 5000, "audio/webm")}
    )
    assert response.status_code == 413


def test_a_rejected_upload_never_reaches_the_transcriber(tmp_path):
    fake = FakeTranscriber()
    client, _ = app_for({"DIYA_MAX_TRANSCRIBE_BYTES": "1000"}, tmp_path, transcriber=fake)
    response = client.post(
        "/api/transcribe", files={"audio": ("clip.webm", b"a" * 5000, "audio/webm")}
    )
    assert response.status_code == 413
    assert fake.calls == []


# --- configuration: what is read, what is rejected -----------------------------------------------

def test_the_two_limits_can_be_set_independently():
    cfg = load_config({"DIYA_MAX_BODY_BYTES": "500", "DIYA_MAX_TRANSCRIBE_BYTES": "9000000"})
    assert (cfg.max_body_bytes, cfg.max_transcribe_bytes) == (500, 9_000_000)


@pytest.mark.parametrize("name", ["DIYA_MAX_BODY_BYTES", "DIYA_MAX_TRANSCRIBE_BYTES"])
@pytest.mark.parametrize("bad", ["abc", "1.5", "0", "-1"])
def test_a_bad_limit_is_rejected_with_a_clear_message(name, bad):
    with pytest.raises(ConfigError, match=name):
        load_config({name: bad})


def test_blank_limits_count_as_unset():
    cfg = load_config({"DIYA_MAX_BODY_BYTES": "  ", "DIYA_MAX_TRANSCRIBE_BYTES": " "})
    assert (cfg.max_body_bytes, cfg.max_transcribe_bytes) == (1_000_000, 25_000_000)
