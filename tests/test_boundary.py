"""The API's network/browser boundary: who may talk to it, and from where.

Three rules, enforced on every route (including the auto-generated docs):
  1. It listens on this computer only, unless LAN mode is switched on deliberately.
  2. It answers only to Host names it was told about (defeats DNS rebinding).
  3. A browser request must come from the UI's own origin (defeats a web page from anywhere else
     reading the chat history through the user's browser). CORS is never "*".
Requests with no Origin header (curl, scripts, a future server-side proxy) are not browsers, so
rule 3 doesn't apply to them; the per-install token is the next increment.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from diya_config import ConfigError, load_config
from fakes import FakeClient, text_reply

LAN_ENV = {"DIYA_LAN": "1", "DIYA_ALLOWED_HOSTS": "phone.local,10.1.2.3"}


def client_for(env=None, tmp_path=None, base_url="https://localhost"):
    # These tests are about Host and Origin; the access token (required by default) has its own
    # tests in test_token.py, including how it layers over this boundary. Opted out here.
    config = load_config({"DIYA_REQUIRE_TOKEN": "0", **(env or {})})
    config = dataclasses.replace(
        config,
        db_path=str(tmp_path / "b.db"),
        profile_path=str(tmp_path / "b_profile.txt"),
    )
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 20))
    app = diya_web.create_app(config, agent, transcriber=object())
    return TestClient(app, base_url=base_url), app


@pytest.fixture
def client(tmp_path):
    return client_for(tmp_path=tmp_path)[0]


# --- Host allowlist -------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8080", "LOCALHOST:8080", "127.0.0.1", "127.0.0.1:8080", "[::1]", "[::1]:8080"],
)
def test_the_computers_own_names_are_answered(client, host):
    assert client.get("/api/threads", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize(
    "host",
    ["evil.example", "evil.example:8080", "localhost.evil.example", "127.0.0.1.evil.example", "10.1.2.3",
     "0.0.0.0", "testserver", "", "localhost@evil.example", "[::1", "[::2]"],
)
def test_any_other_host_is_refused_so_dns_rebinding_gets_nothing(client, host):
    response = client.get("/api/threads", headers={"Host": host})
    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_no_route_answers_to_a_foreign_host_including_the_docs(tmp_path):
    client, app = client_for(tmp_path=tmp_path)
    paths = {route.path for route in app.routes}
    assert {"/docs", "/openapi.json", "/api/threads", "/api/chat", "/api/transcribe"} <= paths
    for path in sorted(paths):
        concrete = path.replace("{thread_id}", "1")
        for method in ("GET", "POST", "OPTIONS"):
            response = client.request(method, concrete, headers={"Host": "evil.example"})
            assert response.status_code == 400, (method, path)
    assert client.get("/no/such/route", headers={"Host": "evil.example"}).status_code == 400


def test_a_refused_host_never_reaches_the_agent(tmp_path):
    client, _ = client_for(tmp_path=tmp_path)
    response = client.post("/api/chat", json={"message": "hi"}, headers={"Host": "evil.example"})
    assert response.status_code == 400
    assert client.get("/api/threads").json() == {"threads": []}  # nothing was created


# --- Origin allowlist -----------------------------------------------------------------------------

@pytest.mark.parametrize("origin", ["https://localhost:3000", "https://127.0.0.1:3000", "https://[::1]:3000"])
def test_the_uis_own_origin_is_allowed(client, origin):
    response = client.get("/api/threads", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin  # exact, never "*"


@pytest.mark.parametrize(
    "origin",
    ["https://evil.example", "https://evil.example:3000", "http://localhost:3000", "https://localhost:3001",
     "https://localhost", "https://localhost:3000.evil.example", "https://localhost:3000/", "null", "*", ""],
)
def test_a_page_from_anywhere_else_is_refused_before_anything_runs(tmp_path, origin):
    client, _ = client_for(tmp_path=tmp_path)
    response = client.get("/api/threads", headers={"Origin": origin})
    assert response.status_code == 403
    assert response.text == "Origin not allowed"
    assert "access-control-allow-origin" not in response.headers


def test_a_cross_site_page_cannot_send_a_chat_message(tmp_path):
    client, _ = client_for(tmp_path=tmp_path)
    # what a hostile page's fetch() would send (the browser adds Origin itself; the page can't remove it)
    response = client.post("/api/chat", json={"message": "hi"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert client.get("/api/threads").json() == {"threads": []}


def test_a_hostile_preflight_is_refused_too(client):
    response = client.options(
        "/api/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_requests_without_an_origin_are_not_browsers_and_pass(client):
    assert client.get("/api/threads").status_code == 200
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 200


def test_cors_is_never_a_wildcard(client):
    for origin in ("https://localhost:3000", "https://evil.example", "null"):
        response = client.options(
            "/api/chat",
            headers={"Origin": origin, "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "content-type"},
        )
        assert response.headers.get("access-control-allow-origin") != "*"
    allowed = client.options(
        "/api/chat",
        headers={"Origin": "https://localhost:3000", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-methods"] == "GET, POST"  # no PUT/DELETE/PATCH


def test_a_custom_frontend_port_moves_the_allowed_origin(tmp_path):
    client, _ = client_for({"DIYA_FRONTEND_PORT": "4000"}, tmp_path)
    assert client.get("/api/threads", headers={"Origin": "https://localhost:4000"}).status_code == 200
    assert client.get("/api/threads", headers={"Origin": "https://localhost:3000"}).status_code == 403


# --- LAN mode: allowed names come from configuration, nothing is hard-coded --------------------------

def test_lan_names_are_answered_only_when_configured(tmp_path):
    lan, _ = client_for(LAN_ENV, tmp_path)
    plain, _ = client_for({}, tmp_path)
    for name in ("phone.local", "10.1.2.3", "PHONE.local:8080"):
        assert lan.get("/api/threads", headers={"Host": name}).status_code == 200
        assert plain.get("/api/threads", headers={"Host": name}).status_code == 400


def test_lan_origins_follow_the_allowed_hosts(tmp_path):
    lan, _ = client_for(LAN_ENV, tmp_path)
    for origin in ("https://phone.local:3000", "https://10.1.2.3:3000", "https://localhost:3000"):
        response = lan.get("/api/threads", headers={"Host": "phone.local", "Origin": origin})
        assert response.status_code == 200 and response.headers["access-control-allow-origin"] == origin
    assert lan.get("/api/threads", headers={"Origin": "https://10.9.9.9:3000"}).status_code == 403
    assert lan.get("/api/threads", headers={"Host": "10.9.9.9"}).status_code == 400


def test_the_default_allowlists_contain_only_loopback_names():
    config = load_config({})
    assert diya_config.api_allowed_hosts(config) == ("localhost", "127.0.0.1", "::1")
    assert diya_config.api_allowed_origins(config) == (
        "https://localhost:3000", "https://127.0.0.1:3000", "https://[::1]:3000",
    )


def test_configured_loopback_names_are_not_listed_twice():
    config = load_config({"DIYA_ALLOWED_HOSTS": "LocalHost, 127.0.0.1, phone.local, phone.local"})
    assert diya_config.api_allowed_hosts(config) == ("localhost", "127.0.0.1", "::1", "phone.local")


# --- configuration: what is read, what is rejected -------------------------------------------------------

def test_the_api_listens_on_this_computer_only_by_default():
    config = load_config({})
    assert (config.host, config.lan, config.allowed_hosts, config.frontend_port) == ("127.0.0.1", False, (), 3000)


def test_lan_mode_listens_on_all_interfaces_unless_told_otherwise():
    assert load_config(LAN_ENV).host == "0.0.0.0"
    assert load_config({**LAN_ENV, "DIYA_HOST": "10.1.2.3"}).host == "10.1.2.3"


@pytest.mark.parametrize("word", ["1", "true", "YES", "on"])
def test_lan_accepts_the_usual_true_words(word):
    assert load_config({"DIYA_LAN": word}).lan is True


@pytest.mark.parametrize("word", ["0", "false", "No", "off"])
def test_lan_accepts_the_usual_false_words(word):
    config = load_config({"DIYA_LAN": word})
    assert config.lan is False and config.host == "127.0.0.1"


def test_a_lan_typo_is_an_error_not_a_silent_guess():
    with pytest.raises(ConfigError, match="DIYA_LAN"):
        load_config({"DIYA_LAN": "enabled"})


@pytest.mark.parametrize(
    "bad",
    ["*", "*.local", "https://phone.local", "phone.local:8080", "phone.local/", "0.0.0.0", "a@b", "a b", "[::1]"],
)
def test_allowed_hosts_rejects_wildcards_schemes_ports_and_paths(bad):
    with pytest.raises(ConfigError, match="DIYA_ALLOWED_HOSTS"):
        load_config({"DIYA_ALLOWED_HOSTS": bad})


def test_allowed_hosts_tolerates_spaces_case_duplicates_and_empty_items():
    config = load_config({"DIYA_ALLOWED_HOSTS": " Phone.Local ,, 10.1.2.3 ,phone.local,"})
    assert config.allowed_hosts == ("phone.local", "10.1.2.3")


@pytest.mark.parametrize("bad", ["abc", "0", "70000", "-1", "3000.5"])
def test_a_bad_frontend_port_is_rejected(bad):
    with pytest.raises(ConfigError, match="DIYA_FRONTEND_PORT"):
        load_config({"DIYA_FRONTEND_PORT": bad})


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.1.2.3", "::1", " LocalHost "])
def test_loopback_hosts_are_recognised(host):
    assert diya_config.is_loopback(host)


@pytest.mark.parametrize(
    "host", ["0.0.0.0", "10.1.2.3", "203.0.113.5", "::", "phone.local", "127.evil.example", "", "localhost.evil.example"]
)
def test_other_hosts_are_not_loopback(host):
    assert not diya_config.is_loopback(host)


# --- refusing an accidental exposure -----------------------------------------------------------------

def test_the_defaults_pass_the_exposure_check():
    diya_config.check_exposure(load_config({}))


def test_listening_beyond_this_computer_without_lan_mode_is_refused():
    for host in ("0.0.0.0", "10.1.2.3", "::"):
        with pytest.raises(ConfigError, match="DIYA_LAN=1"):
            diya_config.check_exposure(load_config({"DIYA_HOST": host}))


def test_lan_mode_without_named_hosts_is_refused():
    with pytest.raises(ConfigError, match="DIYA_ALLOWED_HOSTS"):
        diya_config.check_exposure(load_config({"DIYA_LAN": "1"}))


def test_lan_mode_with_named_hosts_passes():
    diya_config.check_exposure(load_config(LAN_ENV))


def test_allowed_hosts_alone_do_not_expose_anything():
    config = load_config({"DIYA_ALLOWED_HOSTS": "phone.local"})
    assert config.host == "127.0.0.1" and config.lan is False
    diya_config.check_exposure(config)
