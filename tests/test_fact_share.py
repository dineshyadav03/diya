"""A plain fact-share gets a short acknowledgement; questions and requests are untouched.

The model-facing behaviour (one short sentence, no reflex tool calls) is measured on the real model
by the evals in diya_evals.py; these tests pin down the mechanism around it: what the model is and
is not sent, that ordinary turns reach it unchanged, and that nothing extra is stored.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_intent
import diya_web
from fakes import FakeClient, text_reply, tool_reply

FACTS = [
    "My driving test is on October 12 from 9 to 10am and I take the train from Leeds to York for it.",
    "My sister Anna lives in Lisbon and her birthday is on March 3rd.",
    "My flight to Berlin leaves on Friday at 6am.",
    "I have a dentist appointment next Tuesday at 3pm.",
    "I just moved to a new apartment on Baker Street.",
    "my pottery class is on June 5 from 3 to 5pm and I take the bus to Exampleville for it",
    "I’m allergic to penicillin.",  # phone keyboards send a typographic apostrophe
    "Remember that my locker code is 4821.",
    "We're moving to Paris in June.",
    "My wifi password is on the fridge.",
    "I work at Acme Corp.",
    "I've adopted a cat called Miso.",
]
NOT_FACTS = [
    # questions (including ones only a question mark gives away)
    "What's the weather in London?", "What did I say about my dentist?", "Is my flight on Friday?",
    "I have an exam on Friday, how should I prepare?", "My dog is sick, what should I do?",
    "My flight is on Friday, right?", "I have a dentist appointment on Tuesday, correct?",
    # a statement, but not the user's own (nothing to acknowledge as theirs)
    "The shop closes at 5pm on Sundays.",
    # commands and requests, including ones that look like a fact
    "Remind me to call mom tomorrow.", "Remember to buy milk on Friday.", "Tell me a joke.",
    "Add milk to my shopping list for Friday.", "Search for trains from Leeds to York on Monday.",
    "Can you check my notes for the dentist?", "call my mom on Friday",
    "I have a dentist appointment on Tuesday. Remind me the day before.",
    "My flight leaves on Friday. Can you find hotels near the airport?",
    # needs, wishes, problems, complaints
    "I need a taxi to the airport at 6am.", "I want to book a flight to Berlin on Friday.",
    "I'm looking for a good sushi place in Leeds.", "I don't know what to wear to my interview on Monday.",
    "My printer isn't working, help.", "My laptop crashed yesterday", "My code has a bug on line 40",
    "I keep getting an error when I log in on Monday", "My order hasn't arrived and it was due Tuesday",
    "I have three exams next week and no idea where to start", "I can't find my keys, I left them Tuesday",
    "I need to renew my passport by March",
    # chat, or not first-person, or nothing factual in it
    "hello", "thanks!", "The weather is nice today.", "I'm bored.", "9 times 7", "",
]


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(tmp_path / "t.db"),
        profile_path=str(tmp_path / "profile.txt"),
        require_token=False,  # about fact-shares over the web, not the access token (see test_token.py)
    )


def agent_with(config, *replies):
    client = FakeClient(replies)
    return diya.Agent(config, client=client), client


# --- the detector ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text", FACTS)
def test_clear_fact_shares_are_recognised(text):
    assert diya_intent.is_fact_share(text)


@pytest.mark.parametrize("text", NOT_FACTS)
def test_questions_requests_needs_and_chat_are_never_treated_as_fact_shares(text):
    assert not diya_intent.is_fact_share(text)


def test_long_or_rambling_messages_are_left_alone():
    assert not diya_intent.is_fact_share("My flight is on Friday. " + "It leaves early. " * 40)
    assert not diya_intent.is_fact_share("My flight is on Friday. It leaves at 6. I land at 9. Then a train at 11.")


def test_non_text_is_never_a_fact_share():
    assert not diya_intent.is_fact_share(None) and not diya_intent.is_fact_share(42)


def test_shorten_ack_keeps_short_replies_and_trims_rambling_ones():
    assert diya_intent.shorten_ack("Noted, your flight is on Friday.") == "Noted, your flight is on Friday."
    assert diya_intent.shorten_ack("Noted. " + "Here is some more advice. " * 12) == "Noted."
    assert diya_intent.shorten_ack("word " * 60) == "Got it."  # no short first sentence to keep
    assert diya_intent.shorten_ack("") == ""


# --- what the model is sent ---------------------------------------------------------------------------

def test_a_fact_share_gets_no_tools_and_the_short_reply_instructions(config):
    fact = "My flight to Berlin leaves on Friday at 6am."
    agent, client = agent_with(config, text_reply("Noted, your flight leaves on Friday at 6am."))
    messages = [{"role": "user", "content": fact}]
    answer, tools_called = agent.ask(messages)

    call = client.chat_calls[0]
    assert call["tools"] is None  # so it cannot save a reminder or search the web on its own
    assert call["messages"][0] == {"role": "system", "content": diya.FACT_SHARE_PROMPT}
    assert call["messages"][-1]["content"] == fact + "\n\n" + diya.FACT_SHARE_HINT
    assert (answer, tools_called) == ("Noted, your flight leaves on Friday at 6am.", [])
    assert messages == [{"role": "user", "content": fact}]  # the caller's list is not touched


def test_the_profile_is_merged_into_the_single_system_message(config):
    agent, client = agent_with(config, text_reply("Noted."))
    history = [
        {"role": "system", "content": "What you know about the user so far:\n- likes tea"},
        {"role": "user", "content": "I have a dentist appointment next Tuesday at 3pm."},
    ]
    agent.ask(history)
    sent = client.chat_calls[0]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]  # one system message, not two
    assert sent[0]["content"].startswith(diya.FACT_SHARE_PROMPT) and "likes tea" in sent[0]["content"]


@pytest.mark.parametrize("text", NOT_FACTS[:-1])
def test_every_other_turn_reaches_the_model_exactly_as_before(config, text):
    """Ordinary answers must stay ordinary: no instructions added, all tools offered."""
    agent, client = agent_with(config, text_reply("An ordinary answer."))
    history = [{"role": "system", "content": "What you know about the user so far:\n- likes tea"},
               {"role": "user", "content": text}]
    agent.ask(list(history))
    call = client.chat_calls[0]
    assert call["messages"] == history
    assert call["tools"] is diya.TOOLS


def test_a_request_can_still_use_a_tool(config):
    agent, client = agent_with(
        config, tool_reply("add_reminder", '{"content": "call mom"}'), text_reply("Done.")
    )
    answer, tools = agent.ask([{"role": "user", "content": "Remind me to call mom tomorrow."}])
    assert (answer, tools) == ("Done.", ["add_reminder"])
    assert [r[1] for r in agent.store.list_reminders()] == ["call mom"]


# --- the reply ------------------------------------------------------------------------------------------

def test_a_rambling_reply_to_a_fact_share_is_cut_back(config):
    rambling = "Noted, your flight is on Friday. " + "Here are some tips for travelling. " * 10
    agent, _ = agent_with(config, text_reply(rambling))
    answer, _ = agent.ask([{"role": "user", "content": "My flight to Berlin leaves on Friday at 6am."}])
    assert answer == "Noted, your flight is on Friday."


def test_a_long_reply_to_a_question_is_left_exactly_alone(config):
    long_answer = "A mortgage is a loan. " + "It has many parts. " * 30
    agent, _ = agent_with(config, text_reply(long_answer))
    answer, _ = agent.ask([{"role": "user", "content": "Explain what a mortgage is."}])
    assert answer == long_answer


def test_an_empty_reply_to_a_fact_share_is_retried_without_tools_and_falls_back(config):
    agent, client = agent_with(config, text_reply(""), text_reply(""))
    answer, _ = agent.ask([{"role": "user", "content": "My flight to Berlin leaves on Friday at 6am."}])
    assert answer == "I didn't get a clear answer -- try rephrasing."
    assert [c["tools"] for c in client.chat_calls] == [None, None]


# --- storing it: the message is saved as written, nothing extra is created ---------------------------------

def test_a_fact_share_over_the_web_saves_the_message_verbatim_and_creates_no_reminder(config):
    fact = "I have a dentist appointment next Tuesday at 3pm."
    agent, client = agent_with(config, text_reply("Noted, your dentist appointment is next Tuesday at 3pm."))
    web = TestClient(diya_web.create_app(config, agent, transcriber=object()), base_url="https://localhost")
    body = web.post("/api/chat", json={"message": fact}).json()

    assert body["answer"] == "Noted, your dentist appointment is next Tuesday at 3pm."
    assert body["tools_called"] == []
    assert agent.store.get_history(body["thread_id"]) == [
        {"role": "user", "content": fact},  # the hint the model saw is NOT saved with it
        {"role": "assistant", "content": "Noted, your dentist appointment is next Tuesday at 3pm."},
    ]
    assert agent.store.list_reminders() == []
    assert client.chat_calls[0]["tools"] is None
