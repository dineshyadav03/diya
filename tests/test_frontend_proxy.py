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
from datetime import timedelta

import pytest
import uvicorn

import diya
import diya_web
from diya_config import load_config
from fakes import FakeClient, task_kind, text_reply

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

def serve_api(tmp_path, action_kinds=(), executed=None):
    path = tmp_path / "token.hash"
    diya_web.ensure_token(str(path))
    path.write_text(diya_web.hash_token(TOKEN) + "\n")  # a token we know, stored the way the API stores it
    config = dataclasses.replace(
        load_config({"DIYA_REQUIRE_TOKEN": "1", "DIYA_TOKEN_PATH": str(path)}),
        db_path=str(tmp_path / "api.db"),
        profile_path=str(tmp_path / "api_profile.txt"),
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("hello from the model")] * 20), action_kinds=action_kinds)
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
    yield types.SimpleNamespace(url=f"http://127.0.0.1:{port}", agent=agent, thread_id=thread_id, heard=heard, executed=executed)
    server.should_exit = True
    thread.join(10)


@pytest.fixture
def api(tmp_path):
    yield from serve_api(tmp_path)


@pytest.fixture
def api_with_actions(tmp_path):
    """The same real API, whose agent also has a fake kind of action; `executed` lists every time its effect ran."""
    executed = []
    yield from serve_api(tmp_path, (task_kind(executed=executed),), executed)


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
    assert sorted(targets) == sorted([
        "/api/history/${threadId}", "/api/chat", "/api/threads", "/api/transcribe",
        "/api/memory", "/api/memory/${id}", "/api/memory/ingest", "/api/memory/add", "/api/memory/${fact.id}/${action}", "/api/memory/${id}/edit",
        "/api/reminders", "/api/reminders", "/api/reminders", "/api/reminders/${reminder.id}/done",  # the chat's due count, the page's list and add, and done
        "/api/tasks", "/api/tasks", "/api/tasks/${task.id}/done", "/api/tasks/${task.id}/reopen",  # the Tasks page: its list, add, done and put back
        "/api/connections", "/api/connections/${connector.name}/connect", "/api/connections/${connector.name}/connect",
        "/api/connections/${connector.name}/disconnect",  # the token-kind form and the oauth-kind button both post here
        "/api/actions", "/api/actions",  # the chat header's waiting count, and the Actions page's list
        "/api/actions/${action.id}/approve", "/api/actions/${action.id}/reject", "/api/actions/${action.id}/resolve",
    ])
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
    found = {}
    for r in app.routes:
        if r.path.startswith("/api/"):
            found.setdefault(r.path, set()).update(r.methods - {"HEAD"})  # one path can carry both a GET and a POST
    return found


def proxy_route_files():
    found = {}
    for path in (FRONTEND / "app" / "api").rglob("route.js"):
        segments = ["{" + s[1:-1] + "}" if s.startswith("[") else s for s in path.relative_to(FRONTEND / "app").parts[:-1]]
        source = path.read_text(encoding="utf-8")
        found["/" + "/".join(segments)] = set(re.findall(r"export const (GET|POST|PUT|PATCH|DELETE)\b", source)), source
    return found


def test_every_api_route_has_a_same_origin_proxy_route_for_the_same_methods(tmp_path):
    routes, proxies = api_routes(tmp_path), proxy_route_files()
    assert set(routes) == {
        "/api/threads", "/api/history/{thread_id}", "/api/chat", "/api/transcribe",
        "/api/memory", "/api/memory/{fact_id}", "/api/memory/ingest", "/api/memory/add", "/api/memory/merge", "/api/memory/{fact_id}/{action}",
        "/api/reminders", "/api/reminders/{reminder_id}/done",
        "/api/tasks", "/api/tasks/{task_id}/done", "/api/tasks/{task_id}/reopen",
        "/api/connections", "/api/connections/{name}/connect", "/api/connections/{name}/disconnect",
        "/api/actions", "/api/actions/{action_id}", "/api/actions/{action_id}/approve",
        "/api/actions/{action_id}/reject", "/api/actions/{action_id}/resolve",
    }
    assert set(proxies) == set(routes), "an API route with no proxy route (or the reverse)"
    for path, methods in routes.items():
        exported, source = proxies[path]
        assert exported == methods, path
        assert "lib/proxy.mjs" in source and any(
            name in source
            for name in ("forward(", "forwardHistory(", "forwardFact(", "forwardFactAction(", "forwardReminderDone(", "forwardConnection(",
                         "forwardAction(", "forwardActionDecision(", "forwardTaskAction(")
        ), path
        assert "force-dynamic" in source, path  # never cached


# --- the memory page's routes (docs/STAGE2_DESIGN.md, unit 6) -------------------------------------

MEMORY_CALLS = [
    ("memory", "GET", None, "/api/memory"),
    ("memoryFact", "GET", {"fact_id": "12"}, "/api/memory/12"),
    ("memoryAction", "POST", {"fact_id": "12", "action": "accept"}, "/api/memory/12/accept"),
    ("memoryAdd", "POST", None, "/api/memory/add"),
    ("memoryIngest", "POST", None, "/api/memory/ingest"),
]


@needs_node
def test_the_memory_routes_work_end_to_end_through_the_ui_server_with_no_token_in_the_browser(api):
    from diya_memory import Memory

    memory = Memory(api.agent.store)
    memory.add_candidate("likes tea", batch_first=1, batch_last=1, position=0, model="m",
                         extracted_at="2026-01-01T00:00:00+00:00", raw="- likes tea")
    listed, detail, accepted, added, ingested = through_the_ui(
        api,
        [
            call("memory", "GET"),
            call("memoryFact", "GET", params={"fact_id": "1"}),
            call("memoryAction", "POST", params={"fact_id": "1", "action": "accept"}),
            json_call("memoryAdd", {"text": "plays chess"}),
            call("memoryIngest", "POST"),
        ],
    )
    assert [a["status"] for a in (listed, detail, accepted, added, ingested)] == [200, 200, 200, 201, 200]
    assert json.loads(unb64(listed["bodyB64"]))["facts"][0]["text"] == "likes tea"
    assert json.loads(unb64(detail["bodyB64"]))["staged"] == "- likes tea"
    assert json.loads(unb64(accepted["bodyB64"]))["fact"]["status"] == "accepted"
    assert memory.accepted_texts() == ["likes tea", "plays chess"]


@needs_node
def test_the_api_refuses_the_memory_routes_without_the_token_and_nothing_is_written(api):
    from diya_memory import Memory

    memory = Memory(api.agent.store)
    fact_id = memory.add_candidate("likes tea", batch_first=1, batch_last=1, position=0, model="m",
                                   extracted_at="2026-01-01T00:00:00+00:00", raw="- likes tea")
    answers = through_the_ui(api, [call("memory", "GET"), call("memoryAction", "POST", params={"fact_id": str(fact_id), "action": "accept"}),
                                   json_call("memoryAdd", {"text": "x"})], token=None)
    assert [a["status"] for a in answers] == [401, 401, 401]
    assert memory.get(fact_id)["status"] == "candidate" and len(memory.facts()) == 1


@needs_node
def test_the_memory_routes_forward_to_their_own_path_and_method_with_the_token_and_nothing_else_of_the_browsers():
    calls = [call(route, method, {"content-type": "application/json", "authorization": "Bearer from-the-browser", "cookie": "a=b"},
                  "{}" if method == "POST" else None, params)  # a browser cannot send a body with a GET
             for route, method, params, _ in MEMORY_CALLS]
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": calls})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [(m, u) for _, m, _, u in MEMORY_CALLS]
    for captured in out["captured"]:
        assert captured["headers"]["authorization"] == f"Bearer {TOKEN}"
        assert "cookie" not in captured["headers"]
    assert "from-the-browser" not in json.dumps(out["captured"])


@needs_node
def test_a_memory_route_answers_only_the_method_the_api_route_does():
    wrong = {"memory": "POST", "memoryFact": "POST", "memoryAction": "GET", "memoryAdd": "GET", "memoryIngest": "GET"}
    calls = [call(route, wrong[route], params={"fact_id": "1", "action": "accept"}) for route in wrong]
    out = run_harness({"mode": "route", "env": {}, "calls": calls})
    assert out["results"] == [{"noHandler": True}] * len(wrong) and out["captured"] == []


@needs_node
@pytest.mark.parametrize("fact_id", ["abc", "1.5", "-1", "1e3", "", " 1", "1 ", "1%2F2", "../1", "1/../2", "9" * 19, "0x10"])
def test_a_fact_id_that_is_not_a_whole_number_is_refused_before_anything_is_sent(fact_id):
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [
        call("memoryFact", "GET", params={"fact_id": fact_id}),
        call("memoryAction", "POST", params={"fact_id": fact_id, "action": "accept"}),
    ]})
    assert [r["status"] for r in out["results"]] == [404, 404]
    assert out["captured"] == []


@needs_node
@pytest.mark.parametrize("action", ["dance", "ACCEPT", "Accept", "", "accept/../x", "accept?x=1", "add", "ingest", "delete", "retire%2Fx", "accept "])
def test_an_action_the_api_does_not_have_is_refused_before_anything_is_sent(action):
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [call("memoryAction", "POST", params={"fact_id": "1", "action": action})]})
    assert out["results"][0]["status"] == 404
    assert out["captured"] == []


@needs_node
@pytest.mark.parametrize("action", ["accept", "reject", "reopen", "retire", "restore", "edit"])
@pytest.mark.parametrize("fact_id", ["1", "12", "9" * 18])
def test_every_real_action_on_a_whole_number_fact_is_forwarded_to_its_own_path(action, fact_id):
    out = run_harness({"mode": "route", "env": {}, "calls": [call("memoryAction", "POST", params={"fact_id": fact_id, "action": action})]})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [("POST", f"/api/memory/{fact_id}/{action}")]


# --- the reminders page's routes (docs/PROACTIVITY_DESIGN.md, unit P3) -----------------------------

REMINDER_CALLS = [
    ("reminders", "GET", None, "/api/reminders"),
    ("reminders", "POST", None, "/api/reminders"),
    ("reminderDone", "POST", {"reminder_id": "12"}, "/api/reminders/12/done"),
]


@needs_node
def test_the_reminder_routes_work_end_to_end_through_the_ui_server_with_no_token_in_the_browser(api):
    store = api.agent.store
    store.add_reminder("water plants")
    listed, added, done = through_the_ui(
        api,
        [
            call("reminders", "GET"),
            json_call("reminders", {"text": "call mum", "when": "in 2 hours"}),
            call("reminderDone", "POST", params={"reminder_id": "1"}),
        ],
    )
    assert [a["status"] for a in (listed, added, done)] == [200, 201, 200]
    assert [r["content"] for r in json.loads(unb64(listed["bodyB64"]))["reminders"]] == ["water plants"]
    assert json.loads(unb64(added["bodyB64"]))["reminder"]["state"] == "upcoming"
    assert [r["content"] for r in store.reminders()] == ["call mum"]  # the first was marked done


@needs_node
def test_the_api_refuses_the_reminder_routes_without_the_token_and_nothing_is_written(api):
    store = api.agent.store
    rid = store.add_reminder("water plants")
    answers = through_the_ui(api, [call("reminders", "GET"), json_call("reminders", {"text": "x"}),
                                   call("reminderDone", "POST", params={"reminder_id": str(rid)})], token=None)
    assert [a["status"] for a in answers] == [401, 401, 401]
    assert [r["content"] for r in store.reminders()] == ["water plants"] and store.get_reminder(rid)["done"] == 0


@needs_node
def test_the_reminder_routes_forward_to_their_own_path_and_method_with_the_token_and_nothing_else_of_the_browsers():
    calls = [call(route, method, {"content-type": "application/json", "authorization": "Bearer from-the-browser", "cookie": "a=b"},
                  "{}" if method == "POST" else None, params)
             for route, method, params, _ in REMINDER_CALLS]
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": calls})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [(m, u) for _, m, _, u in REMINDER_CALLS]
    for captured in out["captured"]:
        assert captured["headers"]["authorization"] == f"Bearer {TOKEN}"
        assert "cookie" not in captured["headers"]
    assert "from-the-browser" not in json.dumps(out["captured"])


@needs_node
def test_a_reminder_route_answers_only_the_methods_the_api_route_does():
    out = run_harness({"mode": "route", "env": {}, "calls": [call("reminderDone", "GET", params={"reminder_id": "1"})]})
    assert out["results"] == [{"noHandler": True}] and out["captured"] == []


@needs_node
@pytest.mark.parametrize("reminder_id", ["abc", "1.5", "-1", "1e3", "", " 1", "1 ", "1%2F2", "../1", "1/../2", "9" * 19, "0x10"])
def test_a_reminder_id_that_is_not_a_whole_number_is_refused_before_anything_is_sent(reminder_id):
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [call("reminderDone", "POST", params={"reminder_id": reminder_id})]})
    assert out["results"][0]["status"] == 404
    assert out["captured"] == []


@needs_node
@pytest.mark.parametrize("reminder_id", ["1", "12", "9" * 18])
def test_a_whole_number_reminder_id_is_forwarded_to_its_own_path(reminder_id):
    out = run_harness({"mode": "route", "env": {}, "calls": [call("reminderDone", "POST", params={"reminder_id": reminder_id})]})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [("POST", f"/api/reminders/{reminder_id}/done")]


# --- the tasks page's routes (docs/TASKS_DESIGN.md, unit T2) -----------------------------------------

TASK_CALLS = [
    ("tasks", "GET", None, "/api/tasks"),
    ("tasks", "POST", None, "/api/tasks"),
    ("taskDone", "POST", {"task_id": "12"}, "/api/tasks/12/done"),
    ("taskReopen", "POST", {"task_id": "12"}, "/api/tasks/12/reopen"),
]


@needs_node
def test_the_task_routes_work_end_to_end_through_the_ui_server_with_no_token_in_the_browser(api):
    tasks = api.agent.tasks
    tasks.add("water plants")
    finished = tasks.add("old one")["id"]
    tasks.complete(finished)
    listed, added, done, reopened = through_the_ui(
        api,
        [
            call("tasks", "GET"),
            json_call("tasks", {"text": "call mum", "when": "tomorrow at 5pm"}),
            call("taskDone", "POST", params={"task_id": "1"}),
            call("taskReopen", "POST", params={"task_id": str(finished)}),
        ],
    )
    assert [a["status"] for a in (listed, added, done, reopened)] == [200, 201, 200, 200]
    body = json.loads(unb64(listed["bodyB64"]))
    assert [t["content"] for t in body["tasks"]] == ["water plants"] and [t["content"] for t in body["done"]] == ["old one"]
    assert json.loads(unb64(added["bodyB64"]))["task"]["due_text"].endswith("17:00")
    assert [t["content"] for t in tasks.tasks("open")] == ["old one", "call mum"]  # the first was ticked off, the old one put back


@needs_node
def test_the_api_refuses_the_task_routes_without_the_token_and_nothing_is_written(api):
    tasks = api.agent.tasks
    task_id = tasks.add("water plants")["id"]
    answers = through_the_ui(api, [call("tasks", "GET"), json_call("tasks", {"text": "x"}),
                                   call("taskDone", "POST", params={"task_id": str(task_id)}),
                                   call("taskReopen", "POST", params={"task_id": str(task_id)})], token=None)
    assert [a["status"] for a in answers] == [401, 401, 401, 401]
    assert [t["content"] for t in tasks.tasks("all")] == ["water plants"] and tasks.get(task_id)["done"] is False


@needs_node
def test_the_task_routes_forward_to_their_own_path_and_method_with_the_token_and_nothing_else_of_the_browsers():
    calls = [call(route, method, {"content-type": "application/json", "authorization": "Bearer from-the-browser", "cookie": "a=b"},
                  "{}" if method == "POST" else None, params)
             for route, method, params, _ in TASK_CALLS]
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": calls})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [(m, u) for _, m, _, u in TASK_CALLS]
    for captured in out["captured"]:
        assert captured["headers"]["authorization"] == f"Bearer {TOKEN}"
        assert "cookie" not in captured["headers"]
    assert "from-the-browser" not in json.dumps(out["captured"])


@needs_node
@pytest.mark.parametrize("route", ["taskDone", "taskReopen"])
def test_a_task_route_answers_only_the_methods_the_api_route_does(route):
    out = run_harness({"mode": "route", "env": {}, "calls": [call(route, "GET", params={"task_id": "1"})]})
    assert out["results"] == [{"noHandler": True}] and out["captured"] == []


@needs_node
@pytest.mark.parametrize("route", ["taskDone", "taskReopen"])
@pytest.mark.parametrize("task_id", ["abc", "1.5", "-1", "1e3", "", " 1", "1 ", "1%2F2", "../1", "1/../2", "9" * 19, "0x10"])
def test_a_task_id_that_is_not_a_whole_number_is_refused_before_anything_is_sent(route, task_id):
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": [call(route, "POST", params={"task_id": task_id})]})
    assert out["results"][0]["status"] == 404
    assert out["captured"] == []


@needs_node
@pytest.mark.parametrize("route, action", [("taskDone", "done"), ("taskReopen", "reopen")])
@pytest.mark.parametrize("task_id", ["1", "12", "9" * 18])
def test_a_whole_number_task_id_is_forwarded_to_its_own_path_and_each_route_does_only_its_own_thing(route, action, task_id):
    out = run_harness({"mode": "route", "env": {}, "calls": [call(route, "POST", params={"task_id": task_id})]})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [("POST", f"/api/tasks/{task_id}/{action}")]


# --- the actions page's routes (docs/ACTIONS_DESIGN.md, unit A3) ---------------------------------------

ACTION_CALLS = [
    ("actions", "GET", None, "/api/actions"),
    ("action", "GET", {"action_id": "12"}, "/api/actions/12"),
    ("actionApprove", "POST", {"action_id": "12"}, "/api/actions/12/approve"),
    ("actionReject", "POST", {"action_id": "12"}, "/api/actions/12/reject"),
    ("actionResolve", "POST", {"action_id": "12"}, "/api/actions/12/resolve"),
]


def json_call_with(route, payload, params):
    entry = json_call(route, payload)
    entry["params"] = params
    return entry


def waiting(api, *titles):
    return [api.agent.actions.propose("add_task", {"title": title}) for title in titles]


@needs_node
def test_the_action_routes_work_end_to_end_through_the_ui_server_with_no_token_in_the_browser(api_with_actions):
    api = api_with_actions
    approve_me, reject_me = waiting(api, "buy milk", "walk the dog")
    listed, one, approved, rejected = through_the_ui(
        api,
        [
            call("actions", "GET"),
            call("action", "GET", params={"action_id": str(approve_me["id"])}),
            json_call_with("actionApprove", {"args_hash": approve_me["args_hash"]}, {"action_id": str(approve_me["id"])}),
            call("actionReject", "POST", params={"action_id": str(reject_me["id"])}),
        ],
    )
    assert [a["status"] for a in (listed, one, approved, rejected)] == [200, 200, 200, 200]
    assert [a["summary"] for a in json.loads(unb64(listed["bodyB64"]))["pending"]] == [approve_me["summary"], reject_me["summary"]]
    assert json.loads(unb64(approved["bodyB64"]))["action"]["status"] == "succeeded"
    assert json.loads(unb64(rejected["bodyB64"]))["action"]["status"] == "rejected"
    assert api.executed == [{"title": "buy milk"}]  # the approved one, once; the rejected one never


@needs_node
def test_the_api_refuses_the_action_routes_without_the_token_and_nothing_is_done(api_with_actions):
    api = api_with_actions
    (action,) = waiting(api, "buy milk")
    answers = through_the_ui(
        api,
        [call("actions", "GET"), call("action", "GET", params={"action_id": str(action["id"])}),
         json_call_with("actionApprove", {"args_hash": action["args_hash"]}, {"action_id": str(action["id"])}),
         call("actionReject", "POST", params={"action_id": str(action["id"])}),
         json_call_with("actionResolve", {"happened": True}, {"action_id": str(action["id"])})],
        token=None,
    )
    assert [a["status"] for a in answers] == [401] * 5
    assert api.executed == [] and api.agent.actions.get(action["id"])["status"] == "pending"


@needs_node
def test_an_action_cut_off_mid_run_is_resolved_through_the_ui_server(api_with_actions):
    api = api_with_actions
    (action,) = waiting(api, "buy milk")
    api.agent.actions.approve(action["id"], action["args_hash"], "cli")
    real_kinds = api.agent.actions.kinds
    api.agent.actions.kinds = (task_kind(raises=KeyboardInterrupt()),)
    with pytest.raises(KeyboardInterrupt):
        api.agent.actions.run(action["id"])
    api.agent.actions.kinds = real_kinds
    (listed,) = through_the_ui(api, [call("actions", "GET")])  # reading the list moves a run cut off long ago to unknown
    assert listed["status"] == 200
    assert api.agent.actions.get(action["id"])["status"] == "executing"  # (it was only just cut off: left alone)
    api.agent.actions.reconcile(older_than=timedelta(0))
    (resolved,) = through_the_ui(api, [json_call_with("actionResolve", {"happened": False, "note": "not in my list"},
                                                      {"action_id": str(action["id"])})])
    assert resolved["status"] == 200
    done = json.loads(unb64(resolved["bodyB64"]))["action"]
    assert done["status"] == "failed" and "not in my list" in done["result"]
    assert api.executed == []  # finding out never ran it


@needs_node
def test_the_action_routes_forward_to_their_own_path_and_method_with_the_token_and_nothing_else_of_the_browsers():
    calls = [call(route, method, {"content-type": "application/json", "authorization": "Bearer from-the-browser", "cookie": "a=b"},
                  "{}" if method == "POST" else None, params)
             for route, method, params, _ in ACTION_CALLS]
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN}, "calls": calls})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [(m, u) for _, m, _, u in ACTION_CALLS]
    for captured in out["captured"]:
        assert captured["headers"]["authorization"] == f"Bearer {TOKEN}"
        assert "cookie" not in captured["headers"]
    assert "from-the-browser" not in json.dumps(out["captured"])


@needs_node
def test_an_action_route_answers_only_the_method_the_api_route_does():
    wrong = {"actions": "POST", "action": "POST", "actionApprove": "GET", "actionReject": "GET", "actionResolve": "GET"}
    calls = [call(route, wrong[route], params={"action_id": "1"}) for route in wrong]
    out = run_harness({"mode": "route", "env": {}, "calls": calls})
    assert out["results"] == [{"noHandler": True}] * len(wrong) and out["captured"] == []


@needs_node
@pytest.mark.parametrize("action_id", ["abc", "1.5", "-1", "1e3", "", " 1", "1 ", "1%2F2", "../1", "1/../2", "9" * 19, "0x10"])
def test_an_action_id_that_is_not_a_whole_number_is_refused_before_anything_is_sent(action_id):
    methods = {"action": "GET", "actionApprove": "POST", "actionReject": "POST", "actionResolve": "POST"}
    out = run_harness({"mode": "route", "env": {"DIYA_TOKEN": TOKEN},
                       "calls": [call(route, method, params={"action_id": action_id}) for route, method in methods.items()]})
    assert [r["status"] for r in out["results"]] == [404] * len(methods)
    assert out["captured"] == []


@needs_node
@pytest.mark.parametrize("action_id", ["1", "12", "9" * 18])
@pytest.mark.parametrize("route, decision", [("actionApprove", "approve"), ("actionReject", "reject"), ("actionResolve", "resolve")])
def test_a_whole_number_action_id_is_forwarded_to_its_own_decision_path(route, decision, action_id):
    out = run_harness({"mode": "route", "env": {}, "calls": [call(route, "POST", params={"action_id": action_id})]})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [("POST", f"/api/actions/{action_id}/{decision}")]


@needs_node
def test_a_whole_number_action_id_is_forwarded_to_its_own_path_for_the_read():
    out = run_harness({"mode": "route", "env": {}, "calls": [call("action", "GET", params={"action_id": "7"})]})
    assert [(c["method"], c["url"]) for c in out["captured"]] == [("GET", "/api/actions/7")]
