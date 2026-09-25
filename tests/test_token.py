"""The per-install access token: generation, storage and verification (diya_web.py, diya_config.py).
Stage 1 design, units 3 and 5 (docs/STAGE1_DESIGN.md section 3 and the "Rollout plan" -> "Bearer
token middleware" and "Flip DIYA_REQUIRE_TOKEN to default on"). A random token is shown once and
only its SHA-256 is kept; every request must carry it unless DIYA_REQUIRE_TOKEN=0, the explicit
opt-out. (Unit 3 shipped it off by default; unit 5 flipped the default once the Next.js proxy could
hold the token for the UI.)
"""
import asyncio
import base64
import dataclasses
import hashlib
import hmac
import os
import re
import secrets
import sys
import types

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from diya_config import ConfigError, load_config
from fakes import FakeClient, text_reply

HOST = "https://localhost"


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def client_for(tmp_path, require=None):
    """An app whose token file is <tmp_path>/token.hash. `require` is DIYA_REQUIRE_TOKEN's value;
    None leaves it unset, i.e. the real default (the token is required), so most tests here run the
    app exactly as a fresh install gets it."""
    env = {"DIYA_TOKEN_PATH": str(tmp_path / "token.hash")}
    if require is not None:
        env["DIYA_REQUIRE_TOKEN"] = require
    config = dataclasses.replace(
        load_config(env),
        db_path=str(tmp_path / "t.db"),
        profile_path=str(tmp_path / "t_profile.txt"),
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 20))
    app = diya_web.create_app(config, agent, transcriber=object())
    return TestClient(app, base_url=HOST), app


@pytest.fixture
def token(tmp_path):
    """A freshly generated token, its hash stored where client_for() will look for it."""
    return diya_web.ensure_token(str(tmp_path / "token.hash"))


# Every route the app has today, with a request that succeeds once it is past the token layer.
ENDPOINTS = [
    ("GET", "/api/threads", {}),
    ("GET", "/api/history/1", {}),
    ("POST", "/api/chat", {"json": {"message": "hi"}}),
    ("POST", "/api/transcribe", {"files": {"audio": ("a.webm", b"x", "audio/webm")}}),
    ("GET", "/docs", {}),
    ("GET", "/redoc", {}),
    ("GET", "/openapi.json", {}),
    ("GET", "/docs/oauth2-redirect", {}),
]


# --- 1. no token, once it is required: 401 -------------------------------------------------------

def test_a_request_with_no_token_is_refused_once_the_token_is_required(tmp_path, token):
    client, _ = client_for(tmp_path)
    response = client.get("/api/threads")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.text == "Missing or invalid access token"


def test_a_refused_request_never_reaches_the_agent(tmp_path, token):
    client, _ = client_for(tmp_path)
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/api/threads", headers=auth(token)).json() == {"threads": []}  # nothing was created


def test_the_token_layer_is_the_outermost_one(tmp_path, token):
    _, app = client_for(tmp_path)
    assert [m.cls for m in app.user_middleware] == [
        diya_web.TokenMiddleware,
        diya_web.BoundaryMiddleware,
        diya_web.BodyLimitMiddleware,
        diya_web.CORSMiddleware,
    ]


def test_no_token_is_refused_before_the_host_the_origin_or_the_body_size_is_looked_at(tmp_path, token):
    client, _ = client_for(tmp_path)
    assert client.get("/api/threads", headers={"Host": "evil.example"}).status_code == 401  # not 400
    assert client.get("/api/threads", headers={"Origin": "https://evil.example"}).status_code == 401  # not 403
    huge = client.post("/api/chat", content=b"x" * 2_000_000, headers={"Content-Type": "application/json"})
    assert huge.status_code == 401  # not 413: the body was never read


def test_a_valid_token_does_not_bypass_the_host_and_origin_checks(tmp_path, token):
    client, _ = client_for(tmp_path)
    assert client.get("/api/threads", headers={**auth(token), "Host": "evil.example"}).status_code == 400
    assert client.get("/api/threads", headers={**auth(token), "Origin": "https://evil.example"}).status_code == 403


# --- 2. a wrong token: 401, including one that looks exactly like a real one ----------------------

def test_a_wrong_token_of_the_right_length_and_alphabet_is_refused(tmp_path, token):
    client, _ = client_for(tmp_path)
    wrong = secrets.token_urlsafe(32)
    assert wrong != token and len(wrong) == len(token) and re.fullmatch(r"[A-Za-z0-9_-]+", wrong)
    assert client.get("/api/threads", headers=auth(wrong)).status_code == 401


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer ", "Basic <T>", "<T>", "Token <T>", "Bearer <T>x", "Bearer x<T>", "Bearer <T> extra",
     "Bearer <T>=", "Bearer 0"],
)
def test_these_authorization_headers_are_refused(tmp_path, token, header):
    client, _ = client_for(tmp_path)
    response = client.get("/api/threads", headers={"Authorization": header.replace("<T>", token)})
    assert response.status_code == 401


def test_the_token_is_case_sensitive_but_the_scheme_name_is_not(tmp_path, token):
    client, _ = client_for(tmp_path)
    assert client.get("/api/threads", headers=auth(token.swapcase())).status_code == 401
    for scheme in ("bearer", "BEARER", "Bearer"):
        assert client.get("/api/threads", headers={"Authorization": f"{scheme} {token}"}).status_code == 200
    assert client.get("/api/threads", headers={"Authorization": f"Bearer   {token}"}).status_code == 200


def test_the_token_is_only_accepted_in_the_authorization_header(tmp_path, token):
    client, _ = client_for(tmp_path)
    assert client.get(f"/api/threads?token={token}&access_token={token}").status_code == 401
    assert client.get("/api/threads", headers={"Cookie": f"token={token}", "X-Token": token}).status_code == 401


def test_more_than_one_authorization_header_is_refused_even_if_one_is_right(tmp_path, token):
    client, _ = client_for(tmp_path)
    wrong = secrets.token_urlsafe(32)
    for headers in ([("Authorization", f"Bearer {token}")] * 2,
                    [("Authorization", f"Bearer {wrong}"), ("Authorization", f"Bearer {token}")],
                    [("Authorization", f"Bearer {token}"), ("Authorization", f"Bearer {wrong}")]):
        assert client.get("/api/threads", headers=headers).status_code == 401


# --- 3. the right token gets through every route -------------------------------------------------

@pytest.mark.parametrize("method, path, kwargs", ENDPOINTS)
def test_the_right_token_succeeds_and_no_token_does_not_on_every_route(tmp_path, token, method, path, kwargs):
    client, _ = client_for(tmp_path)
    assert client.request(method, path, **kwargs).status_code == 401
    assert client.request(method, path, headers=auth(token), **kwargs).status_code == 200


def test_the_endpoint_list_above_covers_every_route_the_app_has(tmp_path, token):
    _, app = client_for(tmp_path)
    routes = {route.path.replace("{thread_id}", "1") for route in app.routes}
    assert routes == {path for _, path, _ in ENDPOINTS}  # a new route means a new line above


def test_every_route_the_app_has_refuses_no_token_including_ones_added_later(tmp_path, token):
    """Discovered from app.routes, not from a list: a route someone adds tomorrow is covered too,
    because the middleware wraps the whole app rather than naming paths."""
    client, app = client_for(tmp_path)
    for path in sorted({route.path for route in app.routes}):
        concrete = path.replace("{thread_id}", "1")
        for method in ("GET", "POST", "OPTIONS"):
            assert client.request(method, concrete).status_code == 401, (method, path)
            assert client.request(method, concrete, headers=auth(token)).status_code != 401, (method, path)
    assert client.get("/no/such/route").status_code == 401  # not a 404: no hint which paths exist
    assert client.get("/no/such/route", headers=auth(token)).status_code == 404


def test_a_websocket_without_the_token_is_closed_and_a_lifespan_scope_is_left_alone():
    reached = []

    async def app(scope, receive, send):
        reached.append(scope["type"])

    middleware = diya_web.TokenMiddleware(app, hashlib.sha256(b"t").hexdigest(), required=True)
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(middleware({"type": "websocket", "headers": []}, None, send))
    assert sent == [{"type": "websocket.close", "code": 1008}] and reached == []
    asyncio.run(middleware({"type": "lifespan"}, None, send))
    assert reached == ["lifespan"]


# --- 4. the comparison is hmac.compare_digest, asserted directly ---------------------------------

def test_the_hashes_are_compared_with_hmac_compare_digest_not_equality(tmp_path, token, monkeypatch):
    client, _ = client_for(tmp_path)
    stored = bytes.fromhex((tmp_path / "token.hash").read_text().strip())
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(diya_web.hmac, "compare_digest", spy)
    assert client.get("/api/threads", headers=auth(token)).status_code == 200
    assert calls == [(hashlib.sha256(token.encode()).digest(), stored)]

    calls.clear()
    wrong = secrets.token_urlsafe(32)
    assert client.get("/api/threads", headers=auth(wrong)).status_code == 401
    assert calls == [(hashlib.sha256(wrong.encode()).digest(), stored)]  # a wrong one is compared the same way


# --- 5. required by default; DIYA_REQUIRE_TOKEN=0 is the explicit opt-out --------------------------

def test_TRIPWIRE_the_token_is_required_by_default():
    """Step 5 of docs/STAGE1_DESIGN.md's rollout plan flipped this default (unit 3 shipped it False
    and this test then asserted that). Flipping it back re-opens the gap the whole stage exists to
    close -- any process on this computer, or any device that sends an allowed Host, could call the
    API -- so this fails on purpose if it changes: update it, README.md, ROADMAP.md,
    PRODUCT_VISION.md and docs/lan.md together, and say why."""
    assert load_config({}).require_token is True


def test_a_fresh_install_requires_the_token_on_every_route(tmp_path, token):
    client, _ = client_for(tmp_path)  # DIYA_REQUIRE_TOKEN unset: the default
    for method, path, kwargs in ENDPOINTS:
        assert client.request(method, path, **kwargs).status_code == 401, (method, path)
        assert client.request(method, path, headers=auth(token), **kwargs).status_code == 200, (method, path)


@pytest.mark.parametrize("require", ["0", "false", "off", "no"])
def test_the_explicit_opt_out_means_no_route_asks_for_a_token(tmp_path, require):
    client, app = client_for(tmp_path, require=require)
    for method, path, kwargs in ENDPOINTS:
        assert client.request(method, path, **kwargs).status_code == 200, (method, path)
    # and a header that would be wrong if it were checked is simply ignored
    assert client.get("/api/threads", headers=auth("not-a-token")).status_code == 200


def test_an_app_that_opted_out_does_not_even_read_the_token_file(tmp_path):
    (tmp_path / "token.hash").write_text("this is not a hash")
    client, _ = client_for(tmp_path, require="0")  # would raise if the app tried to read it
    assert client.get("/api/threads").status_code == 200


def test_required_with_no_stored_token_refuses_everything(tmp_path):
    client, _ = client_for(tmp_path)  # no token was ever generated
    assert not (tmp_path / "token.hash").exists()
    for header in ({}, auth(secrets.token_urlsafe(32)), auth("")):
        assert client.get("/api/threads", headers=header).status_code == 401


def test_required_with_a_token_file_that_is_not_a_hash_refuses_to_build_the_app(tmp_path):
    (tmp_path / "token.hash").write_text("this is not a hash")
    with pytest.raises(ConfigError, match="token hash"):
        client_for(tmp_path)


# --- generation and storage ----------------------------------------------------------------------

def test_a_token_is_url_safe_and_32_random_bytes(tmp_path):
    token = diya_web.ensure_token(str(tmp_path / "t.hash"))
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
    assert len(base64.urlsafe_b64decode(token + "=")) == 32


def test_two_tokens_are_never_the_same(tmp_path):
    first = diya_web.ensure_token(str(tmp_path / "a.hash"))
    second = diya_web.ensure_token(str(tmp_path / "b.hash"))
    assert first != second


def test_only_the_hash_is_stored_never_the_token(tmp_path):
    path = tmp_path / "t.hash"
    token = diya_web.ensure_token(str(path))
    raw = path.read_bytes()
    assert raw == (hashlib.sha256(token.encode()).hexdigest() + "\n").encode()
    assert token.encode() not in raw and b"\r" not in raw
    assert diya_web.hash_token(token) == raw.decode().strip()
    assert sorted(os.listdir(tmp_path)) == ["t.hash"]  # no temporary file left behind


def test_an_existing_token_is_kept_and_nothing_is_returned(tmp_path):
    path = tmp_path / "t.hash"
    diya_web.ensure_token(str(path))
    before = path.read_bytes()
    assert diya_web.ensure_token(str(path)) is None
    assert path.read_bytes() == before


def test_rotation_replaces_the_token_and_the_old_one_stops_working(tmp_path):
    old = diya_web.ensure_token(str(tmp_path / "token.hash"))
    new = diya_web.ensure_token(str(tmp_path / "token.hash"), rotate=True)
    assert new and new != old
    assert (tmp_path / "token.hash").read_text().strip() == diya_web.hash_token(new)
    client, _ = client_for(tmp_path)
    assert client.get("/api/threads", headers=auth(old)).status_code == 401
    assert client.get("/api/threads", headers=auth(new)).status_code == 200


@pytest.mark.parametrize("garbage", ["", "hello", "z" * 64, "A" * 64, "ab" * 31, "ab" * 33])
def test_a_file_that_is_not_a_hash_is_an_error_and_is_left_alone(tmp_path, garbage):
    path = tmp_path / "t.hash"
    path.write_text(garbage)
    with pytest.raises(ConfigError, match="token hash"):
        diya_web.ensure_token(str(path))
    assert path.read_text() == garbage  # never silently replaced


# --- configuration -------------------------------------------------------------------------------

def test_token_settings_default_to_a_local_file_required_and_no_rotation():
    config = load_config({})
    assert (config.token_path, config.require_token, config.rotate_token) == ("diya_token.hash", True, False)


def test_token_settings_can_be_set():
    config = load_config({"DIYA_TOKEN_PATH": "x/t.hash", "DIYA_REQUIRE_TOKEN": "yes", "DIYA_ROTATE_TOKEN": "1"})
    assert (config.token_path, config.require_token, config.rotate_token) == ("x/t.hash", True, True)


@pytest.mark.parametrize("word", ["0", "false", "no", "off", "FALSE", " Off "])
def test_the_opt_out_words_turn_the_requirement_off(word):
    assert load_config({"DIYA_REQUIRE_TOKEN": word}).require_token is False


@pytest.mark.parametrize("name", ["DIYA_REQUIRE_TOKEN", "DIYA_ROTATE_TOKEN"])
def test_a_token_flag_typo_is_an_error_not_a_silent_guess(name):
    with pytest.raises(ConfigError, match=name):
        load_config({name: "enabled"})


def test_blank_token_settings_count_as_unset():
    config = load_config({"DIYA_TOKEN_PATH": " ", "DIYA_REQUIRE_TOKEN": "", "DIYA_ROTATE_TOKEN": "  "})
    assert config == load_config({})


# --- main(): the token is minted at startup, shown once, and only for a server that can start ------

@pytest.fixture
def served(monkeypatch):
    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.update(app=app, **kw))
    monkeypatch.setattr(diya, "Agent", lambda config=None: types.SimpleNamespace(config=config, warm_up=lambda: None))
    monkeypatch.setattr(diya_web, "WhisperTranscriber", lambda name: types.SimpleNamespace(name=name, warm_up=lambda: None))
    return calls


@pytest.fixture
def cert(tmp_path):
    (tmp_path / "host+2.pem").write_text("cert")
    (tmp_path / "host+2-key.pem").write_text("key")


def shown_tokens(text):
    return re.findall(r"^    ([A-Za-z0-9_-]{43})$", text, re.MULTILINE)


def test_main_generates_and_shows_a_token_on_first_start(served, cert, tmp_path, capsys):
    diya_web.main()
    out = capsys.readouterr().out
    (token,) = shown_tokens(out)
    assert out.count(token) == 1  # shown once
    assert (tmp_path / "diya_token.hash").read_text() == diya_web.hash_token(token) + "\n"
    assert "The API requires it" in out and "set DIYA_TOKEN to it" in out  # the UI needs it too
    assert "shown at first start" not in out  # that reminder is for the starts after this one


def test_main_shows_the_token_again_never_but_reminds_where_it_went_on_a_later_start(served, cert, tmp_path, capsys):
    diya_web.main()
    capsys.readouterr()
    before = (tmp_path / "diya_token.hash").read_bytes()
    diya_web.main()
    out = capsys.readouterr().out
    assert shown_tokens(out) == [] and "generated" not in out
    assert "shown at first start" in out and "--rotate-token replaces a lost one" in out
    assert (tmp_path / "diya_token.hash").read_bytes() == before


@pytest.mark.parametrize("how", ["flag", "env"])
def test_main_rotates_the_token_on_request(served, cert, tmp_path, capsys, monkeypatch, how):
    diya_web.main()
    (old,) = shown_tokens(capsys.readouterr().out)
    if how == "flag":
        monkeypatch.setattr(sys, "argv", ["diya_web.py", "--rotate-token"])
    else:
        monkeypatch.setenv("DIYA_ROTATE_TOKEN", "1")
    diya_web.main()
    out = capsys.readouterr().out
    (new,) = shown_tokens(out)
    assert new != old and "previous token no longer works" in out
    assert (tmp_path / "diya_token.hash").read_text() == diya_web.hash_token(new) + "\n"


def test_main_says_how_to_send_the_token_since_it_is_required_by_default(served, cert, capsys):
    diya_web.main()
    out = capsys.readouterr().out
    assert "Authorization: Bearer" in out and "nothing requires it" not in out


def test_main_with_the_opt_out_says_nothing_requires_the_token_and_does_not_nag(served, cert, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DIYA_REQUIRE_TOKEN", "0")
    diya_web.main()
    first = capsys.readouterr().out
    assert len(shown_tokens(first)) == 1  # a token is still minted, so turning the requirement on later needs nothing new
    assert "DIYA_REQUIRE_TOKEN=0: nothing requires it" in first and "Authorization: Bearer" not in first
    diya_web.main()
    later = capsys.readouterr().out
    assert shown_tokens(later) == [] and "access token" not in later and "shown at first start" not in later


def test_main_does_not_mint_a_token_for_a_server_that_refuses_to_start(served, tmp_path, capsys, monkeypatch):
    with pytest.raises(SystemExit):
        diya_web.main()  # no certificate
    monkeypatch.setenv("DIYA_HOST", "0.0.0.0")
    (tmp_path / "host+2.pem").write_text("cert")
    (tmp_path / "host+2-key.pem").write_text("key")
    with pytest.raises(SystemExit):
        diya_web.main()  # beyond this computer without LAN mode
    assert not (tmp_path / "diya_token.hash").exists()
    assert "app" not in served


def test_main_refuses_to_start_on_a_token_file_that_is_not_a_hash(served, cert, tmp_path, capsys):
    (tmp_path / "diya_token.hash").write_text("garbage")
    with pytest.raises(SystemExit) as excinfo:
        diya_web.main()
    assert excinfo.value.code == 1
    assert "doesn't hold a token hash" in capsys.readouterr().out
    assert "app" not in served and (tmp_path / "diya_token.hash").read_text() == "garbage"


def test_main_refuses_to_start_when_the_token_file_cannot_be_written(served, cert, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DIYA_TOKEN_PATH", str(tmp_path / "no-such-folder" / "t.hash"))
    with pytest.raises(SystemExit) as excinfo:
        diya_web.main()
    assert excinfo.value.code == 1
    assert "Couldn't start Diya's server" in capsys.readouterr().out and "app" not in served


def test_the_app_main_serves_asks_for_the_token_unless_opted_out(served, cert, capsys, monkeypatch):
    diya_web.main()
    (token,) = shown_tokens(capsys.readouterr().out)
    client = TestClient(served["app"], base_url=HOST)
    assert client.get("/no/such/route").status_code == 401  # required by default
    assert client.get("/no/such/route", headers=auth(token)).status_code == 404

    monkeypatch.setenv("DIYA_REQUIRE_TOKEN", "0")
    diya_web.main()
    assert TestClient(served["app"], base_url=HOST).get("/no/such/route").status_code == 404  # opted out
