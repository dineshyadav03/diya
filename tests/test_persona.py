"""Diya's voice (diya.PERSONA): every "hey" used to get the same stock line because the model was told nothing about who it was.

What this proves: the system message starts with who Diya is and what day it is, then what is known about the person (and is only the voice when nothing is known); a greeting turn adds a short
instruction at the END of that message, with the part of the day, a looser temperature and no tools; any other turn gets none of that; the voice forbids the stock line; and with the voice
switched off (as the older tests do) the message is exactly the old one.
"""
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_config
from fakes import FakeClient, text_reply

REAL_PERSONA = diya.PERSONA  # read at import, before the autouse fixture empties it for the other tests


@pytest.fixture(autouse=True)
def voice_on(monkeypatch):
    monkeypatch.setattr(diya, "PERSONA", REAL_PERSONA)


def make_agent(tmp_path, replies=(), when=datetime(2026, 10, 11, 14, 20)):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "p.db"), profile_path=str(tmp_path / "profile.txt"))
    return diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: when)


def test_the_voice_says_who_diya_is_and_forbids_the_stock_greeting():
    assert REAL_PERSONA.startswith("You are Diya, a private personal assistant") and "never say \"How can I assist you today\"" in REAL_PERSONA
    assert "never make up facts" in REAL_PERSONA and len(REAL_PERSONA) < 700  # short: it is read on every first message after a pause


def test_with_nothing_known_the_system_message_is_the_voice_and_the_day(tmp_path):
    agent = make_agent(tmp_path)
    (system, user) = agent.with_profile([{"role": "user", "content": "hi"}])
    assert user == {"role": "user", "content": "hi"} and system["role"] == "system"
    assert system["content"] == f"{REAL_PERSONA} Today is Sunday 11 Oct 2026."


def test_with_facts_the_voice_comes_first_then_what_is_known(tmp_path):
    agent = make_agent(tmp_path)
    agent.store.connect().close()
    import diya_memory

    diya_memory.Memory(agent.store).add_manual("name is Alex", "api")
    (system, _) = agent.with_profile([{"role": "user", "content": "hi"}])
    assert system["content"] == f"{REAL_PERSONA} Today is Sunday 11 Oct 2026.\n\nWhat you know about the user so far:\n- name is Alex"


def test_the_day_follows_the_agents_clock(tmp_path):
    agent = make_agent(tmp_path, when=datetime(2027, 1, 2, 9, 0))
    assert "Today is Saturday 2 Jan 2027." in agent.with_profile([])[0]["content"]


def test_with_the_voice_off_nothing_is_added_and_the_old_shape_is_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(diya, "PERSONA", "")
    agent = make_agent(tmp_path)
    assert agent.with_profile([{"role": "user", "content": "hi"}]) == [{"role": "user", "content": "hi"}]
    import diya_memory

    diya_memory.Memory(agent.store).add_manual("likes tea", "api")
    assert agent.with_profile([])[0]["content"] == "What you know about the user so far:\n- likes tea"


@pytest.mark.parametrize("hour, part", [(0, "late at night"), (5, "morning"), (11, "morning"), (12, "afternoon"), (16, "afternoon"), (17, "evening"), (21, "evening"), (22, "late at night"), (23, "late at night")])
def test_a_greeting_gets_a_short_instruction_at_the_end_with_the_part_of_the_day(tmp_path, hour, part):
    agent = make_agent(tmp_path, [text_reply("Hey!")], when=datetime(2026, 10, 11, hour, 5))
    agent.ask(agent.with_profile([{"role": "user", "content": "hey"}]))
    call = agent.client.chat_calls[0]
    system = call["messages"][0]["content"]
    assert system.startswith(f"{REAL_PERSONA} Today is Sunday 11 Oct 2026.") and system.endswith(f"It is {part} for them. " + diya.SMALL_TALK_PROMPT.split("It is {part} for them. ")[1])
    assert call["tools"] is None and call["options"] == {"temperature": diya.SMALL_TALK_TEMPERATURE} and diya.SMALL_TALK_TEMPERATURE == 0.9


def test_a_greeting_with_no_system_message_still_gets_the_instruction(tmp_path):
    agent = make_agent(tmp_path, [text_reply("Hey!")])
    agent.ask([{"role": "user", "content": "thanks"}])
    messages = agent.client.chat_calls[0]["messages"]
    assert messages[0]["role"] == "system" and messages[0]["content"].startswith("The user is only saying hello") and messages[1] == {"role": "user", "content": "thanks"}


def test_anything_else_gets_neither_the_instruction_nor_the_temperature(tmp_path):
    agent = make_agent(tmp_path, [text_reply("It is sunny.")])
    agent.ask(agent.with_profile([{"role": "user", "content": "what is the weather in Pune"}]))
    call = agent.client.chat_calls[0]
    assert "only saying hello" not in call["messages"][0]["content"] and call["options"] == {} and call["tools"] == agent.tools


def test_a_fact_share_keeps_its_own_prompt_and_gets_no_greeting_instruction(tmp_path):
    agent = make_agent(tmp_path, [text_reply("Got it.")])
    agent.ask(agent.with_profile([{"role": "user", "content": "my flight is on Friday at 6pm"}]))
    system = agent.client.chat_calls[0]["messages"][0]["content"]
    assert system.startswith(diya.FACT_SHARE_PROMPT) and "only saying hello" not in system and agent.client.chat_calls[0]["options"] == {}


def test_priming_reads_the_same_start_of_the_message_a_real_chat_sends(tmp_path):
    import diya_warm

    agent = make_agent(tmp_path, [text_reply("x")])
    config = dataclasses.replace(agent.config)
    assert diya_warm.KeepWarm(config, agent, post=lambda *a: True, say=lambda line: None).prime() is True
    primed = agent.client.chat_calls[0]["messages"][0]
    assert primed == agent.with_profile([{"role": "user", "content": "anything"}])[0]
