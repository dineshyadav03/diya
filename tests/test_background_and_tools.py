"""Two things that made Diya slow and chatty, found 2026-10-27 (diya_background.py; diya.Agent._tools_asked_for; docs/SPEED_DESIGN.md, section 4).

What this proves:
* A reply that brings up the person's pet or instrument when their message did not touch it has that sentence (or the clause after a dash) taken out, and is otherwise left word for word; nothing is taken out when the
  message touched the topic, when no fact is about the topic, or when it would leave nothing; and the agent applies it to ordinary replies. The real reply that started this ("...and your dog Hog will be proud.") is the first case.
* A proposal tool (one of the 39 that only PROPOSE an action) is offered to the model only on a message that asks for that kind of action, which is what `_propose` already enforced; every other tool is offered as before,
  so a message that is not asking for an action sends about a fifth of the tool text.
"""
import dataclasses
import json

import pytest

import diya
import diya_actions
import diya_background as background
import diya_config
import diya_connectors
import diya_memory
from fakes import FakeClient, text_reply

FACTS = ["has a dog named hog", "bought new guitar", "Favorite color is teal."]
REAL = ("Next Tuesday, you have:\n\nDiya smoke test\n5:00 PM - 5:30 PM\n\nSo your next Tuesday is packed with learning.\n\nStay focused, stay cool, and keep practicing.\n"
        "You've got this — and your dog Hog will be proud.")


def test_the_reply_that_started_this_loses_only_the_dog():
    said = background.drop_unasked(REAL, "what am I doing next Tuesday?", FACTS)
    assert said == REAL.replace(" — and your dog Hog will be proud.", ".")
    assert "dog" not in said.lower() and "hog" not in said.lower() and said.endswith("You've got this.")


@pytest.mark.parametrize("reply, user, expected", [
    ("Canberra. Hog says hi.", "capital of australia", "Canberra."),
    ("Try 25-minute blocks. Maybe play your guitar on breaks.", "how do I focus", "Try 25-minute blocks."),
    ("Dal and rice.\n\nYour dog would like the leftovers.\n\nEnjoy.", "what should I cook", "Dal and rice.\n\nEnjoy."),
    ("Your puppy is lucky. Canberra.", "capital of australia", "Canberra."),
    ("Short answer; and the dog will be proud", "ok", "Short answer."),
])
def test_a_mention_of_the_pet_or_the_guitar_the_message_did_not_touch_is_taken_out(reply, user, expected):
    assert background.drop_unasked(reply, user, FACTS) == expected


@pytest.mark.parametrize("user", ["what is my dog's name?", "tell me about hog", "how do I train a puppy", "should I get a cat too"])
def test_a_message_that_touches_the_pet_leaves_the_reply_alone(user):
    reply = "Hog is a golden retriever, and he is a good boy. Walk him daily."
    assert background.drop_unasked(reply, user, FACTS) == reply


def test_the_guitar_is_guarded_by_its_own_message_not_the_dogs():
    reply = "Your dog Hog is great. Practise your guitar daily."
    assert background.drop_unasked(reply, "any tips for my guitar?", FACTS) == "Practise your guitar daily."  # about the guitar: the guitar stays, the dog goes
    assert background.drop_unasked(reply, "tips for my dog", FACTS) == "Your dog Hog is great."  # about the dog: the dog stays, the guitar goes


def test_with_no_fact_about_a_pet_nothing_is_guarded_and_a_reply_of_only_the_mention_is_kept():
    assert background.drop_unasked("Your dog is cute.", "hi", ["Favorite color is teal."]) == "Your dog is cute."
    assert background.drop_unasked("Your dog Hog will be proud.", "hi", FACTS) == "Your dog Hog will be proud."  # it would leave nothing
    assert background.drop_unasked("Canberra.", "hi", FACTS) == "Canberra."
    assert background.drop_unasked("Canberra.", "hi", []) == "Canberra." and background.drop_unasked("Canberra.", "hi", None) == "Canberra."
    for value in (None, 5, ["a"], "", "   "):
        assert background.drop_unasked(value, "hi", FACTS) == value


def test_only_the_topic_words_of_a_fact_count_not_every_word_of_it():
    topics = background.topics_of(["has a dog named hog", "bought new guitar", "Favorite color is teal."])
    assert {"dog", "hog"} <= topics["pet"] and "named" not in topics["pet"] and "has" not in topics["pet"]
    assert {"guitar"} <= topics["instrument"] and "bought" not in topics["instrument"] and "teal" not in topics["pet"] | topics["instrument"]
    assert background.topics_of(["Library card expires on March 3rd"]) == {}


# ---- in the agent ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "b.db"), profile_path=str(tmp_path / "p.txt"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"))


def test_the_agent_takes_the_dog_out_of_an_ordinary_reply(config):
    agent = diya.Agent(config, client=FakeClient([text_reply(REAL)]), action_kinds=[])
    diya_memory.open_memory(agent.store, config).add_manual("has a dog named hog", "api")
    answer, _ = agent.ask([{"role": "user", "content": "what am I doing next Tuesday?"}])
    assert "hog" not in answer.lower() and answer.endswith("You've got this.")


def test_the_agent_leaves_the_dog_in_when_the_message_asks_about_him(config):
    agent = diya.Agent(config, client=FakeClient([text_reply("Hog is a good boy.")]), action_kinds=[])
    diya_memory.open_memory(agent.store, config).add_manual("has a dog named hog", "api")
    answer, _ = agent.ask([{"role": "user", "content": "what is my dog called?"}])
    assert answer == "Hog is a good boy."


def test_with_the_tidy_off_the_reply_is_not_touched(config, monkeypatch):
    monkeypatch.setattr(diya, "TIDY_REPLIES", False)
    agent = diya.Agent(config, client=FakeClient([text_reply(REAL)]), action_kinds=[])
    diya_memory.open_memory(agent.store, config).add_manual("has a dog named hog", "api")
    answer, _ = agent.ask([{"role": "user", "content": "what am I doing next Tuesday?"}])
    assert answer == REAL


# ---- which tools the model is offered -------------------------------------------------------------------------------------------------

@pytest.fixture
def connected(config):
    """Every connector connected, so every proposal tool could be offered."""
    import diya_google_calendar

    for name in list(diya_connectors.CONNECTORS) + list(diya_google_calendar.every_card()):
        diya_connectors.store_token(config, name, "refresh")
    return config


def offered(config, message):
    client = FakeClient([text_reply("ok")])
    diya.Agent(config, client=client).ask([{"role": "user", "content": message}])
    return {spec["function"]["name"] for spec in client.chat_calls[0]["tools"]}


def test_a_message_that_asks_for_nothing_is_not_sent_the_description_of_every_proposal_tool(connected):
    agent = diya.Agent(connected, client=FakeClient([]))
    proposals = {kind.tool_name for kind in agent.actions.kinds if kind.tool is not None}
    everything = {spec["function"]["name"] for spec in agent.tools}
    assert len(proposals & everything) >= 20, "the test needs the many proposal tools to be on offer"
    for message in ("tell me a joke", "what is the capital of France", "explain gradient descent in one line", "how do I focus while studying"):
        sent = offered(connected, message)
        assert not (sent & proposals), (message, sorted(sent & proposals))
        assert {"get_weather", "web_search", "list_calendar_events"} <= sent  # the rest are offered as before


def test_a_message_that_asks_for_an_action_is_offered_that_tool(connected):
    sent = offered(connected, "make a Drive folder called Diya smoke test")
    assert any("folder" in name for name in sent), sorted(sent)
    assert len(sent) < 20  # the folder tool and the always-on ones, not all of them


def test_every_proposal_tool_has_a_gate_so_none_is_offered_when_nothing_asked_for_it(connected):
    agent = diya.Agent(connected, client=FakeClient([]))
    assert all(kind.asked is not None for kind in agent.actions.kinds if kind.tool is not None)


def test_offering_fewer_tools_never_lets_in_what_propose_would_have_refused(connected):
    """The filter uses the same test as `_propose`, on the same message: a tool left out is one the turn would have refused."""
    agent = diya.Agent(connected, client=FakeClient([]))
    for message in ("tell me a joke", "make a Drive folder called X", "put lunch on my calendar tomorrow at noon", "remind me to call mum at 5pm"):
        kept = {spec["function"]["name"] for spec in agent._tools_asked_for(agent.tools, message)}
        for kind in agent.actions.kinds:
            if kind.tool is not None:
                assert (kind.tool_name in kept) == bool(kind.asked(message)), (message, kind.tool_name)


def test_an_automation_run_is_still_offered_only_what_it_was_given(connected):
    client = FakeClient([text_reply("fine")])
    agent = diya.Agent(connected, client=client)
    agent.briefing("what is the weather")
    sent = {spec["function"]["name"] for spec in client.chat_calls[0]["tools"] or ()}
    assert not any(name.startswith("propose_") for name in sent)
