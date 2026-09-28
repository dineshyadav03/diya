"""Connectors and permissions (docs/CONNECTORS_DESIGN.md, unit C1): the shared plumbing -- the
Connector type, credential storage, and the plain call log. Not any one real connector: CONNECTORS
is empty in production (test_the_real_registry_is_still_empty pins that down); everything else here
uses fake Connector instances, the way the design doc always intended this module to be proven.

What this proves: a connector's token lives in its own file, never the database, and is never
written for one that fails validation or is not implemented; disconnecting is idempotent and never
touches anything else; every call is logged, and the token itself never appears in that log; and the
registry lookup and status shape a test (or the API) can rely on.
"""
import dataclasses
import os

import pytest

import diya_config
import diya_connectors
from diya_connectors import Connector, ConnectorError


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        connector_tokens_dir=str(tmp_path / "tokens"),
        connectors_log_path=str(tmp_path / "connectors.log"),
    )


def token_connector(name="demo", implemented=True, validate=lambda token: None):
    return Connector(name=name, label="Demo", description="A fake connector for tests.",
                     auth_kind="token", implemented=implemented, validate=validate)


def oauth_connector(name="demo_oauth", implemented=False, oauth_connect=lambda config: None):
    return Connector(name=name, label="Demo OAuth", description="A fake oauth connector.",
                     auth_kind="oauth", implemented=implemented,
                     oauth_connect=oauth_connect if implemented else None)


# --- the type itself ---------------------------------------------------------------------------

def test_the_real_registry_is_still_empty():
    """The whole point of C1: no real connector is registered yet (docs/CONNECTORS_DESIGN.md)."""
    assert diya_connectors.CONNECTORS == ()


@pytest.mark.parametrize("name", ["Demo", "demo-1", "1demo", "de mo", "", "d" * 41])
def test_a_bad_name_is_refused(name):
    with pytest.raises(ValueError):
        Connector(name=name, label="x", description="x", auth_kind="token", validate=lambda t: None)


def test_a_bad_auth_kind_is_refused():
    with pytest.raises(ValueError):
        Connector(name="demo", label="x", description="x", auth_kind="carrier_pigeon")


def test_an_implemented_token_connector_needs_a_validator():
    with pytest.raises(ValueError):
        Connector(name="demo", label="x", description="x", auth_kind="token", implemented=True)


def test_an_unimplemented_token_connector_needs_no_validator():
    token_connector(implemented=False, validate=None)  # does not raise


def test_an_implemented_oauth_connector_needs_an_oauth_connect_function():
    with pytest.raises(ValueError):
        Connector(name="demo", label="x", description="x", auth_kind="oauth", implemented=True)


def test_an_unimplemented_oauth_connector_needs_no_oauth_connect_function():
    Connector(name="demo", label="x", description="x", auth_kind="oauth", implemented=False)  # does not raise


def test_by_name_finds_and_misses():
    demo = token_connector()
    assert diya_connectors.by_name((demo,), "demo") is demo
    assert diya_connectors.by_name((demo,), "nope") is None
    assert diya_connectors.by_name((), "demo") is None


# --- store_token: the part connect() shares with an oauth flow's own exchange (unit C3) ------------

def test_store_token_writes_and_logs_without_any_validation(config):
    """store_token is what an oauth-kind connector's own oauth_connect calls once its exchange with
    the real provider has already succeeded -- there is no separate token to validate here."""
    diya_connectors.store_token(config, "demo_oauth", "a-refresh-token")
    assert diya_connectors.read_token(config, "demo_oauth") == "a-refresh-token"
    assert "demo_oauth  connected  ok" in open(config.connectors_log_path, encoding="utf-8").read()


def test_store_token_overwrites_a_previous_one(config):
    diya_connectors.store_token(config, "demo_oauth", "first")
    diya_connectors.store_token(config, "demo_oauth", "second")
    assert diya_connectors.read_token(config, "demo_oauth") == "second"


# --- connecting ----------------------------------------------------------------------------------

def test_connecting_stores_the_token_trimmed(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "  a-real-token  ")
    assert diya_connectors.is_connected(config, "demo")
    assert diya_connectors.read_token(config, "demo") == "a-real-token"


def test_the_stored_file_holds_exactly_the_trimmed_token(config):
    """read_token() also strips, so a test that only calls it can't tell a clean write from one with
    stray whitespace baked in -- this reads the raw file instead."""
    connector = token_connector()
    diya_connectors.connect(config, connector, "  a-real-token  ")
    with open(os.path.join(config.connector_tokens_dir, "demo.token"), encoding="utf-8") as f:
        assert f.read() == "a-real-token\n"


def test_a_connector_that_is_not_implemented_is_refused_and_nothing_is_written(config):
    connector = token_connector(implemented=False, validate=None)
    with pytest.raises(ConnectorError, match="not available yet"):
        diya_connectors.connect(config, connector, "x")
    assert not diya_connectors.is_connected(config, "demo")


def test_an_empty_token_is_refused(config):
    connector = token_connector()
    with pytest.raises(ConnectorError, match="empty"):
        diya_connectors.connect(config, connector, "   ")
    assert not diya_connectors.is_connected(config, "demo")


def test_the_validator_is_called_with_the_trimmed_token_and_can_refuse_it(config):
    seen = []

    def validate(token):
        seen.append(token)
        raise ConnectorError("the demo service said no")

    connector = token_connector(validate=validate)
    with pytest.raises(ConnectorError, match="said no"):
        diya_connectors.connect(config, connector, "  raw-token  ")
    assert seen == ["raw-token"]
    assert not diya_connectors.is_connected(config, "demo")  # refused: nothing written


def test_a_working_validator_lets_the_token_through(config):
    connector = token_connector(validate=lambda token: None)
    diya_connectors.connect(config, connector, "good-token")
    assert diya_connectors.read_token(config, "demo") == "good-token"


def test_reconnecting_replaces_the_old_token(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "first")
    diya_connectors.connect(config, connector, "second")
    assert diya_connectors.read_token(config, "demo") == "second"


# --- disconnecting ---------------------------------------------------------------------------------

def test_disconnecting_removes_the_token(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "x")
    assert diya_connectors.disconnect(config, "demo") is True
    assert not diya_connectors.is_connected(config, "demo")
    assert diya_connectors.read_token(config, "demo") is None


def test_disconnecting_something_never_connected_is_not_an_error(config):
    assert diya_connectors.disconnect(config, "never_connected") is False


def test_disconnecting_a_real_connection_does_not_say_it_was_never_connected(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "x")
    diya_connectors.disconnect(config, "demo")
    log = open(config.connectors_log_path, encoding="utf-8").read()
    disconnect_line = next(line for line in log.splitlines() if "disconnected" in line)
    assert disconnect_line.endswith("disconnected  ok")  # nothing appended: it really was connected


def test_disconnecting_something_never_connected_says_so_in_the_log(config):
    diya_connectors.disconnect(config, "never_connected")
    log = open(config.connectors_log_path, encoding="utf-8").read()
    assert "was not connected" in log


def test_disconnecting_twice_is_fine_the_second_time_too(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "x")
    diya_connectors.disconnect(config, "demo")
    assert diya_connectors.disconnect(config, "demo") is False


# --- the log -------------------------------------------------------------------------------------

def test_every_connect_and_disconnect_is_logged(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "x")
    diya_connectors.disconnect(config, "demo")
    log = open(config.connectors_log_path, encoding="utf-8").read()
    assert log.count("\n") == 2
    assert "demo  connected  ok" in log
    assert "demo  disconnected  ok" in log


def test_the_token_itself_never_appears_in_the_log(config):
    connector = token_connector()
    diya_connectors.connect(config, connector, "super-secret-value")
    log = open(config.connectors_log_path, encoding="utf-8").read()
    assert "super-secret-value" not in log


def test_a_refused_connect_is_not_logged_as_a_success(config):
    connector = token_connector(implemented=False, validate=None)
    with pytest.raises(ConnectorError):
        diya_connectors.connect(config, connector, "x")
    assert not os.path.exists(config.connectors_log_path)  # never reached log_call at all


# --- status --------------------------------------------------------------------------------------

def test_status_reports_every_connector_and_its_state(config):
    connected = token_connector(name="connected_one")
    not_connected = token_connector(name="not_connected_one")
    future = oauth_connector()
    diya_connectors.connect(config, connected, "x")

    rows = diya_connectors.status(config, (connected, not_connected, future))

    assert rows == [
        {"name": "connected_one", "label": "Demo", "description": "A fake connector for tests.",
         "auth_kind": "token", "implemented": True, "connected": True},
        {"name": "not_connected_one", "label": "Demo", "description": "A fake connector for tests.",
         "auth_kind": "token", "implemented": True, "connected": False},
        {"name": "demo_oauth", "label": "Demo OAuth", "description": "A fake oauth connector.",
         "auth_kind": "oauth", "implemented": False, "connected": False},
    ]


def test_status_of_an_empty_registry_is_an_empty_list(config):
    assert diya_connectors.status(config, ()) == []


# --- credentials never land where they shouldn't --------------------------------------------------

def test_the_token_file_is_not_inside_the_database_directory_by_accident(config, tmp_path):
    connector = token_connector()
    diya_connectors.connect(config, connector, "x")
    assert os.path.exists(os.path.join(config.connector_tokens_dir, "demo.token"))
    assert not os.path.exists(str(tmp_path / "test.db") + ".token")
