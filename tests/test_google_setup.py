"""Setting Google up from the Connections page (docs/GOOGLE_SETUP.md): the client id and secret pasted once, instead of two environment variables.

What this proves: the id and the secret are checked for the shape Google gives them and nothing is stored for one that cannot be right (the refusal says what the shape is, never what was pasted);
what is stored is a file of its own beside the connector tokens, and is what sign-in then uses, while DIYA_GOOGLE_* settings, when there are some, win; the connector list says whether it is set up and
from where, with the steps to follow, and never the values; the routes save, refuse a connector that needs no setup (409), unknown names (404) and bad values (422), and forgetting the app also
disconnects (a sign-in belongs to the app it was made with); the page's form sends the values and forgets them; and sign-in really goes to Google with the stored client id.
"""
import dataclasses
import json
import os

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_connector_tools
import diya_connectors
import diya_google_calendar as gcal
import diya_google_cards
import diya_web
from diya_connectors import ConnectorError
from fakes import FakeClient

ID = "123456789012-abcdefghijklmnop.apps.googleusercontent.com"
SECRET = "GOCSPX-abcDEF_123-xyz9876543210"


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"),
                               google_client_id="", google_client_secret="", db_path=str(tmp_path / "g.db"), profile_path=str(tmp_path / "p.txt"), require_token=False,
                               protect_secrets=False)  # these tests read the stored file as it is; tests/test_secrets.py is about the protected one


# ---- the storage ----------------------------------------------------------------------------------------------------------------

def test_a_pasted_client_is_stored_beside_the_tokens_and_is_what_sign_in_uses(config):
    assert gcal.client_state(config) is None
    gcal.save_client(config, {"client_id": f"  {ID} ", "client_secret": f" {SECRET}\n"})
    assert gcal.client_state(config) == "file" and gcal._client_credentials(config) == (ID, SECRET)
    stored = json.loads(open(os.path.join(config.connector_tokens_dir, "google_calendar.client"), encoding="utf-8").read())
    assert stored == {"client_id": ID, "client_secret": SECRET}


def test_settings_in_the_environment_win_over_what_the_page_stored(config):
    gcal.save_client(config, {"client_id": ID, "client_secret": SECRET})
    env = dataclasses.replace(config, google_client_id="env-id", google_client_secret="env-secret")
    assert gcal.client_state(env) == "environment" and gcal._client_credentials(env) == ("env-id", "env-secret")
    half = dataclasses.replace(config, google_client_id="env-id")  # only one of the two set: it is not a pair, the page's pair is used
    assert gcal.client_state(half) == "file" and gcal._client_credentials(half) == (ID, SECRET)


@pytest.mark.parametrize("client_id, secret, says", [
    ("not-a-client-id", SECRET, "ends in .apps.googleusercontent.com"),
    ("", SECRET, "ends in .apps.googleusercontent.com"),
    (ID, "short", "letters, digits"),
    (ID, "has a space in it 12345", "letters, digits"),
    (ID, "x" * 300, "letters, digits"),
])
def test_values_that_cannot_be_right_are_refused_in_words_and_nothing_is_stored(config, client_id, secret, says):
    with pytest.raises(ConnectorError, match=says) as caught:
        gcal.save_client(config, {"client_id": client_id, "client_secret": secret})
    assert secret not in str(caught.value) or secret == "short"  # the shape is named, the paste is not repeated
    assert gcal.client_state(config) is None and not os.path.exists(os.path.join(config.connector_tokens_dir, "google_calendar.client"))


def test_forgetting_removes_only_what_the_page_stored_and_says_whether_there_was_any(config):
    assert gcal.clear_client(config) is False
    gcal.save_client(config, {"client_id": ID, "client_secret": SECRET})
    assert gcal.clear_client(config) is True and gcal.client_state(config) is None


def test_a_damaged_file_is_nothing_stored_not_a_crash(config):
    os.makedirs(config.connector_tokens_dir)
    for text in ("not json", "[]", json.dumps({"client_id": ID})):
        open(os.path.join(config.connector_tokens_dir, "google_calendar.client"), "w", encoding="utf-8").write(text)
        assert gcal.client_state(config) is None
    with pytest.raises(ConnectorError, match="Connections page"):
        gcal._client_credentials(config)


def test_sign_in_goes_to_google_with_the_stored_client_id(config):
    gcal.save_client(config, {"client_id": ID, "client_secret": SECRET})
    opened = []

    def browser(url):
        opened.append(url)
        raise ConnectorError("stop here")  # the URL is what is being checked, not the whole flow (test_google_calendar.py has that)

    with pytest.raises(ConnectorError, match="stop here"):
        gcal.connect(config, open_browser=browser)
    assert f"client_id={ID}" in opened[0]


# ---- the list and the routes -------------------------------------------------------------------------------------------------

@pytest.fixture
def client(config):
    agent = diya.Agent(config, client=FakeClient())
    return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost")


SHARE_GOOGLES_CLIENT = ("google_calendar", "google_mail", "google_calendar_edit", "google_tasks", "google_drive_files") + diya_google_cards.names()  # the first five, and every newer card (docs/GOOGLE_CHANGES.md)


def google(client):
    return next(c for c in client.get("/api/connections").json()["connectors"] if c["name"] == "google_calendar")


def test_the_list_says_whether_google_is_set_up_with_the_steps_and_never_the_values(client):
    entry = google(client)
    assert entry["setup"]["done"] is False and entry["setup"]["from"] is None
    assert [f["name"] for f in entry["setup"]["fields"]] == ["client_id", "client_secret"] and [f["secret"] for f in entry["setup"]["fields"]] == [False, True]
    assert len(entry["setup"]["steps"]) == 5 and "In production" in " ".join(entry["setup"]["steps"])
    assert all("setup" not in c for c in client.get("/api/connections").json()["connectors"] if c["name"] not in SHARE_GOOGLES_CLIENT)  # the others have none; the other Google ones share Google's
    saved = client.post("/api/connections/google_calendar/setup", json={"values": {"client_id": ID, "client_secret": SECRET}})
    assert saved.status_code == 200 and google(client)["setup"]["done"] is True and google(client)["setup"]["from"] == "file"
    assert ID not in saved.text and SECRET not in saved.text and SECRET not in client.get("/api/connections").text


def test_bad_values_unknown_names_and_a_connector_with_no_setup_are_refused(client, config):
    bad = client.post("/api/connections/google_calendar/setup", json={"values": {"client_id": "nope", "client_secret": SECRET}})
    assert bad.status_code == 422 and "googleusercontent" in bad.json()["detail"] and SECRET not in bad.text
    assert client.post("/api/connections/google_calendar/setup", json={"values": {"client_id": ID}}).status_code == 422  # a missing field is named
    assert "Client secret" in client.post("/api/connections/google_calendar/setup", json={"values": {"client_id": ID}}).json()["detail"]
    assert client.post("/api/connections/nothing/setup", json={"values": {}}).status_code == 404
    assert client.post("/api/connections/todoist/setup", json={"values": {}}).status_code == 409
    assert client.post("/api/connections/todoist/clear-setup").status_code == 409 and client.get("/api/connections/google_calendar/setup").status_code == 405
    assert gcal.client_state(config) is None


def test_forgetting_the_app_also_disconnects_google_because_the_sign_in_belongs_to_the_app(client, config):
    client.post("/api/connections/google_calendar/setup", json={"values": {"client_id": ID, "client_secret": SECRET}})
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    assert google(client)["connected"] is True
    cleared = client.post("/api/connections/google_calendar/clear-setup")
    assert cleared.status_code == 200 and google(client)["connected"] is False and google(client)["setup"]["done"] is False
    assert client.post("/api/connections/google_calendar/clear-setup").status_code == 200  # again: nothing left, and that is fine


def test_the_real_registry_gives_google_its_setup_and_the_rest_none(config):
    real = {c.name: c for c in diya_connector_tools.real_connectors(config)}
    import diya_google_mail

    assert real["google_calendar"].setup is gcal.SETUP and real["google_mail"].setup is diya_google_mail.SETUP  # Gmail shares Google's client with Calendar
    assert all(c.setup is None for name, c in real.items() if name not in SHARE_GOOGLES_CLIENT)
    assert all(real[name].setup.fields == gcal.SETUP.fields and real[name].setup.state is gcal.client_state for name in SHARE_GOOGLES_CLIENT)  # one client id and secret for all of them


# ---- the page ----------------------------------------------------------------------------------------------------------------

def test_the_page_shows_the_form_only_until_it_is_set_up_and_forgets_what_was_typed():
    page = open(os.path.join(os.path.dirname(__file__), "..", "frontend", "app", "connections", "page.js"), encoding="utf-8").read()
    assert "connector.setup && !connector.setup.done" in page and "fetch(`/api/connections/${connector.name}/setup`" in page and "fetch(`/api/connections/${connector.name}/clear-setup`" in page
    assert "type={field.secret ? 'password' : 'text'}" in page and "autoComplete=\"off\"" in page
    assert "setSetupInputs((current) => ({ ...current, [connector.name]: {} }))" in page  # what was typed is forgotten after it is sent
    assert "connector.setup.from === 'file'" in page  # a setting in the environment is not the page's to forget
