"""The Next.js proxy: the browser calls same-origin /api/* routes; the UI's server forwards them to
the Python API and attaches the access token (frontend/lib/proxy.mjs, frontend/app/api/*).
Stage 1 design, unit 4 (docs/STAGE1_DESIGN.md section 3, "How the UI obtains it", and the "Rollout
plan" -> "Next.js BFF proxy").

The real route files and the real proxy module run under Node through tests/proxy_harness.mjs --
against a fake API that records exactly what reaches it, and against the real FastAPI app with the
token required, so "the outbound call carries the right Authorization header" is checked by the API
itself accepting it, not by reading the code.
"""
import base64
import dataclasses
import json
import pathlib
import re
import shutil
import socket
import subprocess
import threading
import time
import types

import pytest
import uvicorn

import diya
import diya_web
from diya_config import load_config
from fakes import FakeClient, text_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
HARNESS = ROOT / "tests" / "proxy_harness.mjs"
TOKEN = "test-token-not-a-real-one-0123456789abcdef"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def b64(data):
    return base64.b64encode(data if isinstance(data, bytes) else data.encode()).decode()


def unb64(text):
    return base64.b64decode(text)


def run_harness(scenario):
    result = subprocess.run(
        ["node", str(HARNESS)], input=json.dumps(scenario), capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def call(route, method="GET", headers=None, body=None, params=None, url="https://localhost:3000/api/x"):
    entry = {"route": route, "method": method, "url": url, "headers": headers or {}}
    if params is not None:
        entry["params"] = params
    if body is not None:
        entry["bodyB64"] = b64(body)
    return entry


def json_call(route, payload):
    return call(route, "POST", {"content-type": "application/json"}, json.dumps(payload))


def multipart(audio, boundary="----diya-test-boundary"):
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="a.webm"\r\n'
        "Content-Type: audio/webm\r\n\r\n"
    ).encode()
    return head + audio + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def leaks(out):
    """Everything the token must never be in: what goes back to the browser (headers and the
    *decoded* body -- the harness base64-encodes bodies, which would hide it from a plain search)
    and the server log. Not spyCalls or captured: those are the outgoing request, which carries
    it on purpose."""
    parts = list(out["logs"])
    for result in out["results"]:
        parts.append(json.dumps(result.get("headers", {})))
        parts.append(unb64(result.get("bodyB64", "")).decode("utf-8", "replace"))
    return "\n".join(parts)


def closed_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- a real API, with the token required, for the end-to-end tests ---------------------------------

@pytest.fixture
def api(tmp_path):
    path = tmp_path / "token.hash"
    diya_web.ensure_token(str(path))
    path.write_text(diya_web.hash_token(TOKEN) + "\n")  # a token we know, stored the way the API stores it
    config = dataclasses.replace(
        load_config({"DIYA_REQUIRE_TOKEN": "1", "DIYA_TOKEN_PATH": str(path)}),
        db_path=str(tmp_path / "api.db"),
        profile_path=str(tmp_path / "api_profile.txt"),
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("hello from the model")] * 20))
    heard = []

    def transcribe(audio_path):
        heard.append(pathlib.Path(audio_path).read_bytes())
        return "what is on my list"

    app = diya_web.create_app(config, agent, transcriber=types.SimpleNamespace(transcribe=transcribe))
    port = closed_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    thread_id = agent.store.create_thread()
    agent.store.add_message(thread_id, "user", "an earlier message")
    yield types.SimpleNamespace(url=f"http://127.0.0.1:{port}", agent=agent, thread_id=thread_id, heard=heard)
    server.should_exit = True
    thread.join(10)


def through_the_ui(api, calls, token=TOKEN):
    env = {"DIYA_TOKEN": token} if token is not None else {}
    return run_harness({"mode": "route", "env": env, "apiUrl": api.url, "calls": calls})["results"]


# --- 1. the browser reaches every API route without ever sending a token --------------------------

@needs_node
def test_every_route_works_through_the_ui_server_though_the_browser_sent_no_token(api):
    audio = bytes(range(256)) * 8
    body, content_type = multipart(audio)
    chat, threads, history, transcribe = through_the_ui(
        api,
        [
            json_call("chat", {"message": "hi"}),
            call("threads", "GET"),
            call("history", "GET", params={"thread_id": str(api.thread_id)}),
            call("transcribe", "POST", {"content-type": content_type}, body),
        ],
    )
    for answer in (chat, threads, history, transcribe):
        assert answer["status"] == 200, answer
    assert json.loads(unb64(chat["bodyB64"]))["answer"] == "hello from the model"
    assert any(t["preview"] == "an earlier message" for t in json.loads(unb64(threads["bodyB64"]))["threads"])
    assert json.loads(unb64(history["bodyB64"]))["messages"][0]["content"] == "an earlier message"
    assert json.loads(unb64(transcribe["bodyB64"])) == {"text": "what is on my list"}
    assert api.heard == [audio]  # the audio arrived byte for byte


@needs_node
def test_the_api_itself_refuses_the_same_requests_without_the_token(api):
    (answer,) = through_the_ui(api, [call("threads", "GET")], token=None)
    assert answer["status"] == 401
    assert unb64(answer["bodyB64"]) == b"Missing or invalid access token"  # the API's own answer, passed on


@needs_node
def test_a_wrong_token_in_the_ui_servers_environment_is_refused_by_the_api(api):
    (answer,) = through_the_ui(api, [call("threads", "GET")], token="not-the-token")
    assert answer["status"] == 401


@needs_node
def test_a_token_the_browser_sends_is_not_forwarded_and_cannot_stand_in_for_the_real_one(api):
    browser_header = {"authorization": f"Bearer {TOKEN}"}
    (answer,) = through_the_ui(api, [call("threads", "GET", browser_header)], token=None)
    assert answer["status"] == 401  # the right token, sent by the "browser", never reached the API
    (answer,) = through_the_ui(api, [call("threads", "GET", {"authorization": "Bearer wrong"})])
    assert answer["status"] == 200  # and a wrong one doesn't override the server's own


@needs_node
def test_only_the_content_type_and_the_token_are_taken_from_the_browsers_request():
    browser = {
        "content-type": "application/json",
        "cookie": "session=abc",
        "origin": "https://localhost:3000",
        "referer": "https://localhost:3000/",
        "authorization": "Bearer browser-supplied",
        "x-forwarded-for": "203.0.113.9",
        "x-forwarded-host": "evil.example",
        "x-api-key": "k",
    }
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [call("chat", "POST", browser, "{}")]})
    (seen,) = out["captured"]
    names = set(seen["headers"])
    assert not names & {"cookie", "origin", "referer", "x-forwarded-for", "x-forwarded-host", "x-api-key"}
    assert seen["headers"]["authorization"] == f"Bearer {TOKEN}"
    assert [v for k, v in zip(seen["rawHeaders"][::2], seen["rawHeaders"][1::2]) if k.lower() == "authorization"] == [f"Bearer {TOKEN}"]
    assert seen["headers"]["content-type"] == "application/json"


@needs_node
def test_no_authorization_header_is_sent_when_no_token_is_set():
    out = run_harness({"mode": "route", "env": {}, "calls": [call("threads", "GET", {"authorization": "Bearer browser-supplied"})]})
    assert "authorization" not in out["captured"][0]["headers"]


@needs_node
def test_a_request_body_arrives_byte_for_byte():
    body, content_type = multipart(bytes(range(256)) * 4)
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [call("transcribe", "POST", {"content-type": content_type}, body)]})
    (seen,) = out["captured"]
    assert unb64(seen["bodyB64"]) == body and seen["headers"]["content-type"] == content_type
    assert (seen["method"], seen["url"]) == ("POST", "/api/transcribe")


@needs_node
def test_the_apis_status_and_content_type_come_back_but_not_its_other_headers():
    reply = {
        "status": 422,
        "headers": {"content-type": "application/json", "set-cookie": "a=b", "x-secret": "y", "www-authenticate": "Bearer"},
        "bodyB64": b64('{"detail":"nope"}'),
    }
    out = run_harness({"mode": "route", "env": {}, "reply": reply, "calls": [call("threads", "GET")]})
    (answer,) = out["results"]
    assert answer["status"] == 422 and unb64(answer["bodyB64"]) == b'{"detail":"nope"}'
    assert answer["headers"]["content-type"] == "application/json"
    assert not {"set-cookie", "x-secret", "www-authenticate"} & set(answer["headers"])
    assert answer["headers"]["cache-control"] == "no-store"


@needs_node
def test_each_route_forwards_to_its_own_path_and_method():
    calls = [
        call("chat", "POST", {"content-type": "application/json"}, "{}"),
        call("threads", "GET"),
        call("history", "GET", params={"thread_id": "12"}),
        call("transcribe", "POST", {"content-type": "audio/webm"}, "x"),
    ]
    out = run_harness({"mode": "route", "env": {}, "calls": calls})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [
        ("POST", "/api/chat"), ("GET", "/api/threads"), ("GET", "/api/history/12"), ("POST", "/api/transcribe"),
    ]


@needs_node
def test_a_route_answers_only_the_method_the_api_route_does():
    out = run_harness({
        "mode": "route", "env": {},
        "calls": [call("chat", "GET"), call("threads", "POST"), call("transcribe", "GET"), call("history", "POST", params={"thread_id": "1"})],
    })
    assert out["results"] == [{"noHandler": True}] * 4 and out["captured"] == []


# --- failures never carry the token --------------------------------------------------------------

@needs_node
def test_an_unreachable_api_is_a_502_and_the_token_appears_nowhere():
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "apiUrl": f"http://127.0.0.1:{closed_port()}", "calls": [call("threads", "GET")]})
    (answer,) = out["results"]
    assert answer["status"] == 502
    assert "Couldn't reach Diya's API" in json.loads(unb64(answer["bodyB64"]))["error"]
    assert TOKEN not in leaks(out)


@needs_node
def test_a_certificate_the_ui_server_does_not_trust_says_how_to_fix_it():
    out = run_harness({
        "mode": "direct", "env": {"DIYA_TOKEN": TOKEN}, "direct": {"path": "/api/threads", "error": {"code": "UNABLE_TO_VERIFY_LEAF_SIGNATURE"}},
        "calls": [call("threads", "GET")],
    })
    (answer,) = out["results"]
    message = json.loads(unb64(answer["bodyB64"]))["error"]
    assert answer["status"] == 502 and "--use-system-ca" in message and "UNABLE_TO_VERIFY_LEAF_SIGNATURE" in message
    assert TOKEN not in leaks(out)


@needs_node
@pytest.mark.parametrize("token, expected", [(TOKEN, "rejected DIYA_TOKEN"), (None, "DIYA_TOKEN is not set")])
def test_a_401_from_the_api_is_explained_in_the_server_log_without_the_token(token, expected):
    env = {"DIYA_TOKEN": token} if token else {}
    reply = {"status": 401, "headers": {"content-type": "text/plain"}, "bodyB64": b64("Missing or invalid access token")}
    out = run_harness({"mode": "route", "env": env, "reply": reply, "calls": [call("threads", "GET")]})
    assert out["results"][0]["status"] == 401
    assert any(expected in line for line in out["logs"]) and TOKEN not in leaks(out)


# --- 2. where requests go is fixed by configuration, never by the request ------------------------

@needs_node
def test_the_destination_never_depends_on_which_host_the_browser_used():
    """A phone that reaches the UI at a LAN name, or a request with a forged Host header, changes
    nothing about where the token is sent: the address comes from configuration alone."""
    spoofed = [
        {"url": "https://evil.example:3000/api/chat", "headers": {"host": "evil.example:3000", "x-forwarded-host": "evil.example"}},
        {"url": "https://phone.local:3000/api/chat", "headers": {}},
        {"url": "https://203.0.113.5:3000/api/chat", "headers": {"host": "203.0.113.5:3000"}},
    ]
    calls = [call("chat", "POST", {"content-type": "application/json", **s["headers"]}, "{}", url=s["url"]) for s in spoofed]
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": calls})
    assert len(out["captured"]) == 3  # all three landed on the one configured API
    assert all(c["headers"]["authorization"] == f"Bearer {TOKEN}" for c in out["captured"])
    assert all(c["headers"]["host"].startswith("127.0.0.1:") for c in out["captured"])
    direct = run_harness({"mode": "direct", "env": {"DIYA_TOKEN": TOKEN}, "direct": {"path": "/api/chat"}, "calls": [
        call("chat", "POST", {"host": "evil.example:3000"}, "{}", url="https://evil.example:3000/api/chat")]})
    assert direct["spyCalls"][0]["url"] == "https://127.0.0.1:8080/api/chat"


@needs_node
@pytest.mark.parametrize(
    "env, expected",
    [
        ({}, "https://127.0.0.1:8080/api/chat"),
        ({"DIYA_PORT": "9443"}, "https://127.0.0.1:9443/api/chat"),
        ({"DIYA_PORT": " 9443 "}, "https://127.0.0.1:9443/api/chat"),
        ({"DIYA_API_URL": "https://127.0.0.1:8443"}, "https://127.0.0.1:8443/api/chat"),
        ({"DIYA_API_URL": "https://127.0.0.1:8443/", "DIYA_PORT": "1"}, "https://127.0.0.1:8443/api/chat"),
    ],
)
def test_the_api_is_on_this_computer_at_the_configured_port(env, expected):
    out = run_harness({"mode": "direct", "env": env, "direct": {"path": "/api/chat"}, "calls": [call("chat", "POST", {}, "{}")]})
    assert [c["url"] for c in out["spyCalls"]] == [expected]


@needs_node
@pytest.mark.parametrize(
    "env, names",
    [
        ({"DIYA_PORT": "abc"}, "DIYA_PORT"), ({"DIYA_PORT": "0"}, "DIYA_PORT"), ({"DIYA_PORT": "70000"}, "DIYA_PORT"),
        ({"DIYA_PORT": "-1"}, "DIYA_PORT"), ({"DIYA_PORT": "80.5"}, "DIYA_PORT"),
        ({"DIYA_API_URL": "not a url"}, "DIYA_API_URL"), ({"DIYA_API_URL": "ftp://127.0.0.1:8080"}, "DIYA_API_URL"),
        ({"DIYA_API_URL": "https://127.0.0.1:8080/prefix"}, "DIYA_API_URL"),
        ({"DIYA_API_URL": "https://user:pw@127.0.0.1:8080"}, "DIYA_API_URL"),
        ({"DIYA_API_URL": "https://127.0.0.1:8080?x=1"}, "DIYA_API_URL"),
        ({"DIYA_API_URL": "https://127.0.0.1:8080#f"}, "DIYA_API_URL"),
    ],
)
def test_a_bad_address_is_a_500_that_names_the_setting_and_sends_nothing(env, names):
    out = run_harness({"mode": "direct", "env": {**env, "DIYA_TOKEN": TOKEN}, "direct": {"path": "/api/chat"}, "calls": [call("chat", "POST", {}, "{}")]})
    (answer,) = out["results"]
    assert answer["status"] == 500 and names in json.loads(unb64(answer["bodyB64"]))["error"]
    assert out["spyCalls"] == [] and TOKEN not in leaks(out)


@needs_node
@pytest.mark.parametrize(
    "url, token, sent",
    [
        ("http://203.0.113.5:8080", TOKEN, False),   # plain http to another computer: the token would cross the wire
        ("http://203.0.113.5:8080", None, True),     # ...but with no token there is nothing to protect
        ("https://203.0.113.5:8443", TOKEN, True),
        ("http://127.0.0.1:8080", TOKEN, True),
        ("http://localhost:8080", TOKEN, True),
        ("http://[::1]:8080", TOKEN, True),
    ],
)
def test_the_token_is_only_sent_over_https_or_to_this_computer(url, token, sent):
    env = {"DIYA_API_URL": url, **({"DIYA_TOKEN": token} if token else {})}
    out = run_harness({"mode": "direct", "env": env, "direct": {"path": "/api/chat"}, "calls": [call("chat", "POST", {}, "{}")]})
    assert bool(out["spyCalls"]) is sent
    if not sent:
        assert out["results"][0]["status"] == 500 and TOKEN not in leaks(out)


@needs_node
def test_forwarding_is_manual_about_redirects_and_a_get_has_no_body():
    out = run_harness({"mode": "direct", "env": {"DIYA_TOKEN": TOKEN}, "direct": {"path": "/api/threads"},
                       "calls": [call("threads", "GET"), call("threads", "POST", {"content-type": "application/json"}, "{}")]})
    get, post = out["spyCalls"]
    assert (get["method"], get["hasBody"], get["redirect"]) == ("GET", False, "manual")
    assert (post["method"], post["hasBody"]) == ("POST", True)
    assert get["headers"] == {"authorization": f"Bearer {TOKEN}"}  # nothing else was copied over


@needs_node
@pytest.mark.parametrize("thread_id", ["..", "5/../../threads", "%2e%2e", "5?x=1", "5#x", "abc", "", "-1", "1e3", " 5", "5 ", "٣", "1" * 19])
def test_a_thread_id_that_is_not_a_whole_number_is_refused_before_anything_is_sent(thread_id):
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [call("history", "GET", params={"thread_id": thread_id})]})
    assert out["results"][0]["status"] == 404 and out["captured"] == []


@needs_node
@pytest.mark.parametrize("thread_id", ["5", "007", "1" * 18])
def test_a_whole_number_thread_id_is_forwarded(thread_id):
    out = run_harness({"mode": "route", "env": {}, "calls": [call("history", "GET", params={"thread_id": thread_id})]})
    assert [c["url"] for c in out["captured"]] == [f"/api/history/{thread_id}"]


# --- the browser side holds no token and no direct address ---------------------------------------

def browser_files():
    """Every source file shipped to the browser: the pages and components, and the shared helpers
    in lib/ they import -- but not app/api or lib/proxy.mjs, which are the server-side half."""
    server_side = FRONTEND / "app" / "api"
    files = [
        path
        for folder in ("app", "components")
        for path in (FRONTEND / folder).rglob("*")
        if path.suffix in (".js", ".jsx") and server_side not in path.parents
    ]
    files += [p for p in (FRONTEND / "lib").iterdir() if p.suffix in (".js", ".jsx", ".mjs") and p.name != "proxy.mjs"]
    return files


def test_browser_code_never_mentions_the_token_the_api_port_or_the_proxy_module():
    files = browser_files()
    assert {p.name for p in files} >= {"page.js", "VoiceBar.jsx", "layout.js", "api-failure.mjs"}
    assert "proxy.mjs" not in {p.name for p in files}  # the server-side half is exactly what this must exclude
    for path in files:
        source = path.read_text(encoding="utf-8")
        for forbidden in ("Authorization", "authorization", "DIYA_TOKEN", "NEXT_PUBLIC", "8080", "apiBase", "proxy.mjs", "Bearer"):
            assert forbidden not in source, (path.name, forbidden)


def test_every_browser_fetch_is_a_same_origin_api_path():
    targets = []
    for path in browser_files():
        targets += [m.group(2) for m in re.finditer(r"fetch\(\s*([`'\"])(.*?)\1", path.read_text(encoding="utf-8"))]
    assert sorted(targets) == sorted(["/api/history/${threadId}", "/api/chat", "/api/threads", "/api/transcribe"])
    assert not [p for p in browser_files() if re.search(r"fetch\(\s*[^`'\"\s]", p.read_text(encoding="utf-8"))]  # no computed URLs


def test_the_old_direct_to_the_api_url_helper_is_gone():
    assert not (FRONTEND / "lib" / "api.js").exists()


def test_the_token_has_no_home_in_any_file_the_repo_tracks_for_the_frontend():
    tracked = subprocess.run(["git", "ls-files", "frontend"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [f for f in tracked if pathlib.PurePosixPath(f).name.startswith(".env")]
    for name in tracked:
        if name.endswith((".js", ".jsx", ".mjs", ".json", ".md")) and "package-lock" not in name:
            source = (ROOT / name).read_text(encoding="utf-8")
            assert not re.search(r"DIYA_TOKEN\s*[=:]\s*['\"][A-Za-z0-9_-]{20,}", source), name


# --- every API route has a proxy route, and no proxy route is left without one -------------------

def api_routes(tmp_path):
    config = dataclasses.replace(load_config({}), db_path=str(tmp_path / "r.db"), profile_path=str(tmp_path / "r_profile.txt"))
    app = diya_web.create_app(config, diya.Agent(config, client=FakeClient()), transcriber=object())
    return {r.path: r.methods - {"HEAD"} for r in app.routes if r.path.startswith("/api/")}


def proxy_route_files():
    found = {}
    for path in (FRONTEND / "app" / "api").rglob("route.js"):
        segments = ["{" + s[1:-1] + "}" if s.startswith("[") else s for s in path.relative_to(FRONTEND / "app").parts[:-1]]
        source = path.read_text(encoding="utf-8")
        found["/" + "/".join(segments)] = set(re.findall(r"export const (GET|POST|PUT|PATCH|DELETE)\b", source)), source
    return found


def test_every_api_route_has_a_same_origin_proxy_route_for_the_same_methods(tmp_path):
    routes, proxies = api_routes(tmp_path), proxy_route_files()
    assert set(routes) == {"/api/threads", "/api/history/{thread_id}", "/api/chat", "/api/transcribe"}
    assert set(proxies) == set(routes), "an API route with no proxy route (or the reverse)"
    for path, methods in routes.items():
        exported, source = proxies[path]
        assert exported == methods, path
        assert "lib/proxy.mjs" in source and ("forward(" in source or "forwardHistory(" in source), path
        assert "force-dynamic" in source, path  # never cached
