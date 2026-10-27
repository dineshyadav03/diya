"""Typing yes in the chat approves the action Diya just asked about (Agent._approval_reply; docs/HOME_DESIGN.md), added 2026-10-27.

What this proves: a message that is only a yes, typed right after the turn that proposed one action, approves and performs exactly that action, with no model call; a no drops it; a yes for an action that
came from outside text (tainted) does nothing and says to press Approve; a yes to anything but the action just asked about (another chat, an earlier turn, two waiting, nothing waiting, a longer message) is
left to the model as any message is; and a paused Diya does nothing.
"""
import pytest

import diya_pause
from diya_actions import ActionKind
from test_actions_agent import agent_with
from fakes import text_reply

DONE = []


def kind():
    return ActionKind("note", "Note", None, lambda a: None, lambda a: "Add the note: buy milk.", lambda c, a: DONE.append(a) or "done it")


@pytest.fixture(autouse=True)
def clear():
    DONE.clear()


def proposal(agent, tainted=False, extra_turns=0, other_thread=False, kinds=1):
    """A chat in which the person asked for something and Diya proposed `kinds` actions while answering; returns (thread, the id of the person's next message, the action ids)."""
    store = agent.store
    thread = store.create_thread()
    asked = store.add_message(thread, "user", "add a note to buy milk")
    ids = [agent.actions.propose("note", {"n": n}, thread_id=thread, message_id=asked, taint_sources=["read_mail"] if tainted else ()) ["id"] for n in range(kinds)]
    store.add_message(thread, "assistant", "Ready for your OK: Add the note: buy milk.")
    for n in range(extra_turns):
        store.add_message(thread, "user", f"something else {n}")
        store.add_message(thread, "assistant", "ok")
    if other_thread:
        thread = store.create_thread()
    return thread, store.add_message(thread, "user", "yes"), ids


def say(agent, text, thread, message):
    return agent.ask([{"role": "user", "content": text}], thread_id=thread, message_id=message)


def status(agent, action_id):
    return agent.actions.get(action_id)["status"]


@pytest.mark.parametrize("text", ["yes", "Yes!", "yeah", "ok", "go ahead", "do it", "Yes, please", "sure."])
def test_a_typed_yes_right_after_the_proposal_approves_and_performs_it_without_the_model(text):
    agent = agent_with(kind())  # no scripted model reply: asking the model would fail
    thread, message, (action,) = proposal(agent)
    answer, tools = say(agent, text, thread, message)
    assert answer == "Done: Add the note: buy milk." and tools == [] and DONE == [{"n": 0}] and status(agent, action) == "succeeded"


@pytest.mark.parametrize("text", ["no", "No thanks", "cancel", "don't", "never mind"])
def test_a_typed_no_drops_it_and_nothing_is_done(text):
    agent = agent_with(kind())
    thread, message, (action,) = proposal(agent)
    answer, _ = say(agent, text, thread, message)
    assert answer == "Dropped: Add the note: buy milk." and DONE == [] and status(agent, action) == "rejected"


def test_an_action_that_came_from_outside_text_is_not_approved_by_typing_but_a_no_is_always_taken():
    agent = agent_with(kind())
    thread, message, (action,) = proposal(agent, tainted=True)
    answer, _ = say(agent, "yes", thread, message)
    assert "press Approve" in answer and DONE == [] and status(agent, action) == "pending"
    answer, _ = say(agent, "no", thread, message)
    assert answer.startswith("Dropped:") and status(agent, action) == "rejected"


@pytest.mark.parametrize("how", [{"extra_turns": 1}, {"other_thread": True}])
def test_a_yes_to_anything_but_the_action_just_asked_about_goes_to_the_model(how):
    agent = agent_with(kind(), replies=[text_reply("Glad you agree.")])
    thread, message, (action,) = proposal(agent, **how)
    answer, _ = say(agent, "yes", thread, message)
    assert answer == "Glad you agree." and DONE == [] and status(agent, action) == "pending"


def test_a_yes_with_nothing_waiting_goes_to_the_model():
    agent = agent_with(kind(), replies=[text_reply("Yes to what?")])
    thread = agent.store.create_thread()
    agent.store.add_message(thread, "user", "hello")
    message = agent.store.add_message(thread, "user", "yes")
    assert say(agent, "yes", thread, message)[0] == "Yes to what?" and DONE == []


def test_two_waiting_are_not_guessed_between():
    agent = agent_with(kind())
    thread, message, ids = proposal(agent, kinds=2)
    answer, _ = say(agent, "yes", thread, message)
    assert "will not guess" in answer and DONE == [] and {status(agent, i) for i in ids} == {"pending"}


@pytest.mark.parametrize("text", ["yes but also delete everything", "yes and send it to bob", "yes yes yes please do it right now", "is that a yes?"])
def test_only_a_message_that_is_nothing_but_a_yes_counts(text):
    agent = agent_with(kind(), replies=[text_reply("Hm.")])
    thread, message, (action,) = proposal(agent)
    assert say(agent, text, thread, message)[0] == "Hm." and DONE == [] and status(agent, action) == "pending"


def test_a_message_that_is_not_in_a_chat_never_approves_anything():
    agent = agent_with(kind(), replies=[text_reply("Hm.")])
    proposal(agent)
    assert agent.ask([{"role": "user", "content": "yes"}])[0] == "Hm." and DONE == []  # a script, an automation: no thread, no message


def test_a_paused_diya_does_nothing_and_the_action_waits():
    agent = agent_with(kind())
    thread, message, (action,) = proposal(agent)
    diya_pause.pause(agent.store) if hasattr(diya_pause, "pause") else diya_pause.set_paused(agent.store, True)
    answer, _ = say(agent, "yes", thread, message)
    assert "paused" in answer and DONE == [] and status(agent, action) == "pending"
