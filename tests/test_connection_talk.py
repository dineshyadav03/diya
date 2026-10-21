"""Answering "are you connected to my Google Calendar?" from the record (diya_connection_talk; docs/CONNECTORS_DESIGN.md), added 2026-10-21.

Found by the first real sign-in: with Google Calendar connected, the model said "No, I'm not connected to Google Calendar". What this proves, with the real connection files and the real agent: the question is told
from a request (a message that asks for events goes on to the model and its tools); a connected connection is reported as connected with what it can and cannot do, an unconnected one as not connected; "calendar"
covers both the reading card and the adding card and says which is which; a question about all of them lists the connected and the not connected; a question that is not about an account ("are you connected to the
internet?") is left to the model; the model is not asked for any of it (it cannot guess wrongly); the exchange is journalled as a flow; and a disconnection is believed at the next message.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_connection_talk as talk
import diya_connector_tools
import diya_connectors
import diya_web
from fakes import ByQuestionClient
from test_categories import FakeTranscriber, LOCAL


@pytest.mark.parametrize("text, subject", [
    ("are you connected to the google calendar ?", "calendar"), ("Is Gmail connected?", "gmail"), ("do you have access to my email", "gmail"), ("are you linked to my notion", "notion"),
    ("which accounts are connected?", ""), ("what services are you connected to", ""), ("can you see my calendar?", "calendar"), ("are you connected to google", ""),
    ("is my todoist connected?", "todoist"), ("can you access my drive", "drive"),
])
def test_what_is_taken_for_the_question(text, subject):
    assert talk.asks_about_connection(text) == subject


@pytest.mark.parametrize("text", [
    "what's on my calendar tomorrow?", "add dentist to my calendar", "can you see my calendar events for friday please and list them", "are you connected to the internet?", "hey are you ok", "how are you?",
    "", None, 7, "x" * 200, "are you connected\nto the calendar",
])
def test_a_request_or_anything_else_goes_on_to_the_model(text):
    assert talk.asks_about_connection(text) is None


@pytest.fixture
def world(tmp_path):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "c.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, categories=False, lookup=False,
    )
    return config, diya_connector_tools.real_connectors(config)


def test_a_connected_connection_is_said_to_be_connected_with_what_it_can_and_cannot_do(world):
    config, connectors = world
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    text = talk.answer(config, connectors, "calendar")
    assert "Yes: Google Calendar is connected." in text and "Reads your upcoming calendar events." in text and "Cannot add, change or delete events" in text
    assert "No: Google Calendar (add events) is not connected." in text  # the adding card is a different permission and is not connected
    assert "Approve on the Actions page" in text


def test_an_unconnected_connection_is_said_not_to_be(world):
    config, connectors = world
    assert talk.answer(config, connectors, "gmail").startswith("No: Gmail is not connected.")


def test_all_of_them_are_listed_by_state_and_a_subject_nothing_is_about_is_left_alone(world):
    config, connectors = world
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    text = talk.answer(config, connectors, "")
    assert text.startswith("Connected now: Google Calendar.") and "Not connected: " in text and "Gmail" in text.split("Not connected: ")[1]
    assert talk.answer(config, connectors, "spaceship") is None


def build(config, model):
    agent = diya.Agent(config, client=model)
    return TestClient(diya_web.create_app(config, agent, FakeTranscriber()), base_url=LOCAL), agent


def test_the_agent_answers_it_from_the_record_without_asking_the_model_and_believes_a_disconnection(world):
    config, _ = world
    model = ByQuestionClient(chat=["I do not have access to your calendar."])
    client, agent = build(config, model)
    diya_connectors.store_token(config, "google_calendar", "a-refresh-token")
    said = str(client.post("/api/chat", json={"message": "are you connected to the google calendar ?"}).json())
    assert "Yes: Google Calendar is connected." in said and "do not have access" not in said
    assert len(model.asked("chat")) == 0  # the model, which would have guessed, was not asked
    journal = agent.store.connect().execute("SELECT tool, kind, status FROM tool_journal ORDER BY id DESC LIMIT 1").fetchone()
    assert journal == ("explain_connections", "flow", "ok")
    diya_connectors.disconnect(config, "google_calendar")
    after = str(client.post("/api/chat", json={"message": "is the calendar connected?"}).json())
    assert "No: Google Calendar is not connected." in after


def test_a_question_that_is_not_about_an_account_still_reaches_the_model(world):
    config, _ = world
    model = ByQuestionClient(chat=["Yes, I am running on this computer."])
    client, _agent = build(config, model)
    said = str(client.post("/api/chat", json={"message": "are you connected to the internet?"}).json())
    assert "running on this computer" in said and len(model.asked("chat")) >= 1
