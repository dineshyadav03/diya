"""Connectors over HTTP (docs/CONNECTORS_DESIGN.md, unit C1): diya_connections_api.py. The real
registry (diya_connectors.CONNECTORS) is empty, so every test here injects fake Connector instances
through register()'s own `connectors=` parameter -- proving the routes work generically, the same way
the module itself is proven (tests/test_connectors.py), before any real connector exists.

What this proves: the routes carry diya_connectors's rules and no others; a connector name that does
not exist is a 404 before anything runs; an unimplemented connector refuses with a 409, not a crash or
a silent success; a token-kind connector's bad token, or an oauth-kind connector's own refusal, is a
422 with the connector's own reason and nothing is stored; disconnecting is idempotent; nothing here
ever returns a stored token; only GET and POST exist; and nothing is reachable without the access
token.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_connectors
import diya_web
from diya_connectors import Connector, ConnectorError
from fakes import FakeClient

LOCAL = "https://localhost"


def token_connector(name="demo", implemented=True, validate=lambda token: None):
    return Connector(name=name, label="Demo", description="A fake connector for tests.",
                     auth_kind="token", implemented=implemented, validate=validate)


def oauth_connector(name="demo_oauth", implemented=False, oauth_connect=None):
    return Connector(name=name, label="Demo OAuth", description="A fake oauth connector.",
                     auth_kind="oauth", implemented=implemented, oauth_connect=oauth_connect)


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(tmp_path / "api.db"),
        profile_path=str(tmp_path / "profile.txt"),
        connector_tokens_dir=str(tmp_path / "tokens"),
        connectors_log_path=str(tmp_path / "connectors.log"),
        require_token=False,
    )


def client_with(config, connectors):
    """A real app (real token middleware, real CORS/Host rules) whose /api/connections routes see
    only `connectors` -- create_app's own connectors= parameter, the same way it already takes a
    fake model client or a temp database."""
    app = diya_web.create_app(config, diya.Agent(config, client=FakeClient()), object(), connectors=connectors)
    return TestClient(app, base_url=LOCAL)


# --- listing --------------------------------------------------------------------------------------

def test_an_empty_registry_lists_nothing(config):
    client = client_with(config, ())
    assert client.get("/api/connections").json() == {"connectors": []}


def test_the_list_shows_every_connectors_state(config):
    connected = token_connector(name="connected_one")
    not_connected = token_connector(name="not_connected_one")
    client = client_with(config, (connected, not_connected))
    diya_connectors.connect(config, connected, "x")

    body = client.get("/api/connections").json()

    assert body == {"connectors": [
        {"name": "connected_one", "label": "Demo", "description": "A fake connector for tests.",
         "auth_kind": "token", "implemented": True, "connected": True},
        {"name": "not_connected_one", "label": "Demo", "description": "A fake connector for tests.",
         "auth_kind": "token", "implemented": True, "connected": False},
    ]}


def test_a_stored_token_is_never_sent_back(config):
    connector = token_connector()
    client = client_with(config, (connector,))
    diya_connectors.connect(config, connector, "super-secret-value")
    assert "super-secret-value" not in client.get("/api/connections").text


# --- connecting -----------------------------------------------------------------------------------

def test_connecting_with_a_good_token_succeeds(config):
    connector = token_connector()
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo/connect", json={"token": "good"})
    assert response.status_code == 200
    assert response.json()["connectors"][0]["connected"] is True
    assert diya_connectors.read_token(config, "demo") == "good"


def test_a_token_the_connector_refuses_is_a_422_and_nothing_is_stored(config):
    def validate(token):
        raise ConnectorError("the demo service said this token is wrong")

    connector = token_connector(validate=validate)
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo/connect", json={"token": "bad"})
    assert response.status_code == 422 and "said this token is wrong" in response.json()["detail"]
    assert not diya_connectors.is_connected(config, "demo")


def test_an_unimplemented_connector_is_a_409_not_a_crash(config):
    connector = token_connector(implemented=False, validate=None)
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo/connect", json={"token": "x"})
    assert response.status_code == 409 and "not available yet" in response.json()["detail"]


def test_an_oauth_connector_runs_its_own_flow_not_the_pasted_token_path(config):
    """docs/CONNECTORS_DESIGN.md, D6 revised for unit C3: an oauth-kind connector's own
    oauth_connect(config) runs the whole flow and stores the result itself -- connect() here is a
    thin dispatch, not a form handler, so a token in the body (if one is even sent) is unused."""
    calls = []
    connector = oauth_connector(implemented=True, oauth_connect=calls.append)
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo_oauth/connect")
    assert response.status_code == 200 and calls == [config]


def test_an_oauth_connectors_own_refusal_is_a_422(config):
    def refuse(cfg):
        raise ConnectorError("the (fake) browser flow was cancelled")

    connector = oauth_connector(implemented=True, oauth_connect=refuse)
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo_oauth/connect")
    assert response.status_code == 422 and "cancelled" in response.json()["detail"]


def test_an_unknown_connector_is_a_404(config):
    client = client_with(config, ())
    response = client.post("/api/connections/nope/connect", json={"token": "x"})
    assert response.status_code == 404 and "there is no connector" in response.json()["detail"]


@pytest.mark.parametrize("payload", [{}, {"token": 5}, {"token": None}, None])
def test_a_bad_connect_body_is_a_422(config, payload):
    connector = token_connector()
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo/connect", json=payload) if payload is not None else client.post("/api/connections/demo/connect")
    assert response.status_code == 422
    assert not diya_connectors.is_connected(config, "demo")


# --- disconnecting ----------------------------------------------------------------------------------

def test_disconnecting_a_connected_connector_succeeds(config):
    connector = token_connector()
    client = client_with(config, (connector,))
    diya_connectors.connect(config, connector, "x")
    response = client.post("/api/connections/demo/disconnect")
    assert response.status_code == 200
    assert response.json()["connectors"][0]["connected"] is False
    assert not diya_connectors.is_connected(config, "demo")


def test_disconnecting_something_never_connected_still_succeeds(config):
    connector = token_connector()
    client = client_with(config, (connector,))
    response = client.post("/api/connections/demo/disconnect")
    assert response.status_code == 200


def test_disconnecting_an_unknown_connector_is_a_404(config):
    client = client_with(config, ())
    assert client.post("/api/connections/nope/disconnect").status_code == 404


# --- only GET and POST, and the token -------------------------------------------------------------

@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("path", ["/api/connections", "/api/connections/demo/connect", "/api/connections/demo/disconnect"])
def test_no_other_method_exists(config, method, path):
    connector = token_connector()
    client = client_with(config, (connector,))
    assert client.request(method, path).status_code == 405


def test_without_the_token_nothing_is_read_and_nothing_is_written(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config(), db_path=str(tmp_path / "api.db"), profile_path=str(tmp_path / "profile.txt"),
        connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "connectors.log"),
        require_token=True, token_path=str(tmp_path / "token.hash"),
    )
    connector = token_connector()
    client = client_with(config, (connector,))
    for method, path, kwargs in [("GET", "/api/connections", {}), ("POST", "/api/connections/demo/connect", {"json": {"token": "x"}}),
                                 ("POST", "/api/connections/demo/disconnect", {})]:
        assert client.request(method, path, **kwargs).status_code == 401, path
    assert not diya_connectors.is_connected(config, "demo")
