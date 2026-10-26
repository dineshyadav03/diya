"""Diya knows what she is (diya_intent.asks_about_diya and diya.ABOUT_DIYA_NOTE), added 2026-10-14.

Asked "how do i connect you to my google account" the real model answered that it could not connect to Google or any external service and had no connectors, and "what can you do" got a list of things Diya
cannot do, because nothing the model was told says what Diya is. What this proves: the questions about Diya herself (what she can do, how to connect an account or turn a feature on) are recognised in code
and a short list of what is really built, and where each thing is in the app, is given for that turn only; the list says what has never been tried with a real account; an ordinary message, a long one, and
an unattended run get none of it; and it does not displace the record of what the person ticked off.
"""
import dataclasses

import pytest

import diya
import diya_config
import diya_intent
from fakes import FakeClient, text_reply


@pytest.mark.parametrize("text", [
    "how do i connect you to my google account", "i guess u have the connector", "what can you do", "hey diya tell me what can you do", "do you have a calendar", "can you connect to todoist",
    "how do i set up google calendar", "what features do you have", "how do i use the memory", "how can i turn on automations", "how do I link my gmail", "what are your abilities",
    "is there a google connector?", "you got a connector?", "what can you help me with",
])
def test_a_question_about_what_diya_can_do_or_how_to_connect_her_is_recognised(text):
    assert diya_intent.asks_about_diya(text)


@pytest.mark.parametrize("text", [
    "connect the dots for me", "what is a connector in electrical engineering", "i connected with my sister yesterday", "my google account password is hunter2", "what can you tell me about rockets",
    "do you have time to talk", "set up a reminder for tomorrow", "hey", "how do I use a semicolon", "", None, 5, "x" * 300, "how do i connect\nyou to google",
])
def test_an_ordinary_message_is_not_taken_for_one(text):
    assert not diya_intent.asks_about_diya(text)


def test_the_note_lists_only_what_is_built_where_it_is_and_what_was_never_tried():
    note = diya.ABOUT_DIYA_NOTE
    for must in ("Connections page", "Google Calendar", "docs/GOOGLE_SETUP.md", "Memory page", "Automations page", "Knowledge", "have not yet been tried with real accounts", "reads their mail and Drive when asked", "never deletes mail or files for good", "press Approve"):
        assert must in note, must
    assert len(note) < 1800  # it is read in the turns that ask for it, on a small model


def make_agent(tmp_path, replies=(text_reply("ok"),)):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "a.db"), profile_path=str(tmp_path / "p.txt"), lookup=False)
    return diya.Agent(config, client=FakeClient(list(replies)), action_kinds=[])


def system_of(agent, call=0):
    first = agent.client.chat_calls[call]["messages"][0]
    return first["content"] if first["role"] == "system" else ""


def test_a_question_about_diya_is_answered_with_the_note_at_the_end_of_the_system_message(tmp_path):
    agent = make_agent(tmp_path)
    agent.ask([{"role": "user", "content": "how do i connect you to my google account"}])
    assert system_of(agent).endswith(diya.ABOUT_DIYA_NOTE)


def test_another_message_gets_none_of_it_and_neither_does_an_unattended_run(tmp_path):
    agent = make_agent(tmp_path, [text_reply("a"), text_reply("b")])
    agent.ask([{"role": "user", "content": "what is the capital of France?"}])
    assert diya.ABOUT_DIYA_NOTE not in system_of(agent)
    agent.ask([{"role": "user", "content": "what can you do"}], only_tools=("get_weather",))
    assert diya.ABOUT_DIYA_NOTE not in system_of(agent, 1)


def test_the_note_is_added_to_a_turn_not_kept_for_the_next(tmp_path):
    agent = make_agent(tmp_path, [text_reply("a"), text_reply("b")])
    agent.ask([{"role": "user", "content": "what can you do"}])
    agent.ask([{"role": "user", "content": "what is the capital of France?"}])
    assert diya.ABOUT_DIYA_NOTE in system_of(agent, 0) and diya.ABOUT_DIYA_NOTE not in system_of(agent, 1)
