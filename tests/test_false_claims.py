"""A reply never says a reminder or a task was saved when the turn saved none (diya.Agent._settle_claims; diya_intent.claims_a_reminder / claims_a_task), added 2026-10-26.

Found by replaying the owner's long chat against the real model: asked "remind me about the dentist" it answered "I've added a reminder ... Reminder: Don't forget the dentist" without calling any tool, so nothing would
ever have gone off. The same kind of fault as the folder and the document that were "waiting for your approval" when no action existed. What this proves: when the message asks for a reminder (or a task) and the turn
called no tool that saves one, a reply that claims it was saved is replaced by the plain fact and how to ask; nothing is changed when the saving tool ran, whatever it answered, when the message asked for neither, or
when the reply only asks for the time; a streamed reply is taken back; and an unattended run is never touched.
"""
import pytest

import diya
import diya_config
import diya_intent as intent
from fakes import FakeClient, text_reply, tool_reply


def agent_for(replies):
    return diya.Agent(diya_config.load_config(), client=FakeClient(list(replies)), action_kinds=[])


@pytest.mark.parametrize("reply", [
    "I've added a reminder for your dentist appointment.", "I have set a reminder for the dentist.", "✅ **Reminder**: Don't forget the dentist.", "Your reminder is set.", "The reminder has been saved.",
    "I’ve just created a new reminder for you.",
])
def test_these_words_claim_a_reminder_was_saved(reply):
    assert intent.claims_a_reminder(reply)


@pytest.mark.parametrize("reply", [
    "I'll remind you about the dentist. When should it go off?", "I haven't set a reminder yet: what time?", "Tell me the time and I will set a reminder.", "Not saved: a reminder needs a time.",
    "You have two reminders: call mum at 5.", "", None, 5,
])
def test_these_do_not(reply):
    assert not intent.claims_a_reminder(reply)


@pytest.mark.parametrize("reply", ["I've added the task to your list.", "I have created a task: buy milk.", "The task has been added.", "✅ **Task**: buy milk"])
def test_these_words_claim_a_task_was_added(reply):
    assert intent.claims_a_task(reply)


@pytest.mark.parametrize("reply", ["What should the task be called?", "You have 3 tasks.", "I haven't added anything.", None])
def test_these_do_not_claim_a_task(reply):
    assert not intent.claims_a_task(reply)


def test_a_claim_of_a_saved_reminder_with_nothing_saved_is_replaced():
    agent = agent_for([text_reply("I've added a reminder for your dentist appointment.\n\n✅ **Reminder**: Don't forget the dentist.")])
    answer, tools = agent.ask([{"role": "user", "content": "remind me about the dentist"}])
    assert tools == [] and answer == diya.NO_REMINDER_SAVED and agent.store.reminders() == []


def test_when_the_saving_tool_ran_the_reply_is_left_as_the_model_wrote_it():
    agent = agent_for([tool_reply("add_reminder", '{"content": "call the dentist", "due_at": "tomorrow at 5pm"}'), text_reply("I've set a reminder to call the dentist.")])
    answer, tools = agent.ask([{"role": "user", "content": "remind me to call the dentist tomorrow at 5pm"}])
    assert "add_reminder" in tools and answer == "I've set a reminder to call the dentist."


def test_a_message_that_asked_for_neither_is_left_alone():
    said = "I've added a reminder to my own phone, thanks."
    agent = agent_for([text_reply(said)])
    answer, _ = agent.ask([{"role": "user", "content": "how do I set a reminder on my phone?"}])
    assert answer == said  # the person did not ask Diya for one


def test_a_reply_that_asks_for_the_time_is_left_alone():
    asking = "I'll remind you about the dentist. When should it go off?"
    agent = agent_for([text_reply(asking)])
    answer, _ = agent.ask([{"role": "user", "content": "remind me about the dentist"}])
    assert answer == asking


def test_a_claim_of_an_added_task_with_nothing_added_is_replaced_but_not_for_todoist_or_google_tasks():
    agent = agent_for([text_reply("I've added the task to your list: buy milk.")])
    answer, tools = agent.ask([{"role": "user", "content": "add a task to buy milk"}])
    assert tools == [] and answer == diya.NO_TASK_SAVED and agent.tasks.tasks("open") == []
    other = agent_for([text_reply("I've added the task to Todoist.")])
    answer, _ = other.ask([{"role": "user", "content": "add a task to buy milk in Todoist"}])
    assert answer == "I've added the task to Todoist."  # Todoist's and Google's are proposals: their own guard (tests/test_proposal_replies.py)


def test_a_streamed_claim_is_taken_back_and_an_unattended_run_is_never_touched():
    agent = agent_for([text_reply("I've added a reminder for your dentist appointment.")])
    events = []
    answer, _ = agent.ask([{"role": "user", "content": "remind me about the dentist"}], on_event=lambda kind, payload: events.append((kind, payload)))
    assert answer == diya.NO_REMINDER_SAVED and events[-2:] == [("reset", None), ("delta", diya.NO_REMINDER_SAVED)]
    quiet = agent_for([text_reply("I've added a reminder for your dentist appointment.")])
    said, _ = quiet.ask([{"role": "user", "content": "remind me about the dentist"}], only_tools=("get_weather",))
    assert said == "I've added a reminder for your dentist appointment."
