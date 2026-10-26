"""What Diya says after she proposes something is written by code, and she never claims a proposal that was not made (diya.Agent._settle_proposals; diya_actions.proposal_reply), added 2026-10-26.

The owner asked, in one long chat, for a calendar event, a Google task, a Drive folder and a Google Doc. The model's replies were paragraphs: "Why? To help test my own system", an offer to send reminders, a
remark about the owner's dog, and, for the folder and the document, "Proposed Folder ... waiting for your approval on the Actions page" when the model had not called the tool and no action existed.
What this proves: after a turn that recorded a proposal the reply is the action's own sentence (the one the owner approves) and one line about approval, whatever the model wrote; several proposals are listed;
the streamed text is taken back and replaced; a reply that says something is waiting when the turn recorded nothing is replaced, for a message that did ask for an addition, with the plain fact and how to ask
again (and the reason, if a proposal was refused); a reply that mentions the Actions page for any other message is left alone; and an unattended run is never touched.
"""
import diya
import diya_actions
import pytest
from fakes import text_reply, tool_reply
from test_actions_agent import PROPOSE, agent_with, ask, task_kind

FLUFF = "Done! Why? To test my own system.\n\nWant me to send a reminder after you approve?\n\nP.S. You have a dog named Hog! 🐶"


def asks_for_a_task(text):
    return "add a task" in text.lower()


def test_the_reply_after_a_proposal_is_the_actions_own_sentence_and_not_the_models_words():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply(FLUFF)])
    answer, called = ask(agent, "add a task: buy milk", thread_id=1, message_id=1)
    assert called == [PROPOSE] and answer.startswith("Ready for your OK: Add the task 'buy milk'.")
    assert "Hog" not in answer and "Why?" not in answer and "reminder" not in answer and "🐶" not in answer
    assert answer.endswith("press Approve (under this message, or on the Actions page).")


def test_several_proposals_in_one_turn_are_listed():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), tool_reply(PROPOSE, '{"title": "call mum"}'), text_reply(FLUFF)])
    answer, _ = ask(agent, "add a task: buy milk, and add a task: call mum")
    assert answer.startswith("Ready for your OK:\n- Add the task 'buy milk'.\n- Add the task 'call mum'.\n\n")


def test_the_notes_written_for_the_model_are_not_shown_to_the_person_what_was_left_out_is_plain_from_the_sentence():
    kind = task_kind(prepare=lambda args, said: ({"title": args["title"]}, ["It has no due date: 'friday' was left out, because the user did not say when. Ask the user when."]))
    agent = agent_with(kind, replies=[tool_reply(PROPOSE, '{"title": "buy milk", "due": "friday"}'), text_reply(FLUFF)])
    answer, _ = ask(agent, "add a task: buy milk")
    assert answer.startswith("Ready for your OK: Add the task 'buy milk'.\n\nNothing is added") and "the user" not in answer and "friday" not in answer


def test_a_streamed_reply_is_taken_back_and_replaced():
    agent = agent_with(task_kind(), replies=[tool_reply(PROPOSE, '{"title": "buy milk"}'), text_reply(FLUFF)])
    events = []
    answer, _ = agent.ask([{"role": "user", "content": "add a task: buy milk"}], on_event=lambda kind, payload: events.append((kind, payload)))
    assert events[-2] == ("reset", None) and events[-1] == ("delta", answer)


def test_a_reply_that_says_a_proposal_is_waiting_when_none_was_made_is_replaced_by_the_plain_fact():
    claim = "Proposed Folder: Diya smoke test. This is now waiting for your approval on the Actions page."
    agent = agent_with(task_kind(asked=asks_for_a_task), replies=[text_reply(claim)])  # the model never called the tool
    answer, called = ask(agent, "add a task: Diya smoke test")
    assert called == [] and agent.actions.actions() == []
    assert answer.startswith("I did not set that up: nothing is waiting for your approval.") and "Say it again in one line" in answer
    assert "Proposed Folder" not in answer


def test_the_example_to_ask_again_is_the_kinds_own():
    assert diya.PROPOSAL_EXAMPLES["propose_drive_folder"] == "make a Drive folder called Notes"
    assert set(diya.PROPOSAL_EXAMPLES) >= {"propose_calendar_event", "propose_google_task", "propose_drive_folder", "propose_google_doc", "propose_todoist_task"}


def test_a_refused_proposal_gives_its_reason_if_the_reply_claims_it_was_made():
    agent = agent_with(task_kind(asked=asks_for_a_task), replies=[tool_reply(PROPOSE, '{"title": ""}'), text_reply("It is waiting for your approval on the Actions page.")])
    answer, _ = ask(agent, "add a task: x")
    assert agent.actions.actions() == [] and answer.startswith("I did not set that up (") and "nothing is waiting for your approval" in answer


@pytest.mark.parametrize("text, reply", [
    ("what is waiting for my approval?", "Nothing is waiting for you on the Actions page."),
    ("how do approvals work", "You approve each one on the Actions page."),
    ("hello", "Hi!"),
])
def test_a_reply_that_mentions_approval_for_a_message_that_asked_for_nothing_is_left_alone(text, reply):
    agent = agent_with(task_kind(asked=asks_for_a_task), replies=[text_reply(reply)])
    answer, _ = ask(agent, text)
    assert answer == reply


def test_an_unattended_run_is_never_touched():
    agent = agent_with(task_kind(asked=asks_for_a_task), replies=[text_reply("Proposed. Waiting for your approval on the Actions page.")])
    answer, _ = agent.ask([{"role": "user", "content": "add a task: x"}], only_tools=("get_weather",))
    assert answer == "Proposed. Waiting for your approval on the Actions page."


def test_proposal_reply_and_the_claim_words_on_their_own():
    action = {"summary": "Add to your Google Calendar: Dentist, Tuesday 27 Oct 2026, 17:00 (just you: nobody is invited)"}
    assert diya_actions.proposal_reply([(action, [])]).startswith("Ready for your OK: Add to your Google Calendar: Dentist, Tuesday 27 Oct 2026, 17:00 (just you: nobody is invited).")
    for said in ("It is waiting for your approval.", "Please approve it on the Actions page", "I've proposed a folder", "Proposed Event:", "awaiting approval"):
        assert diya_actions.claims_a_proposal(said), said
    for said in ("Done.", "Your calendar is empty.", None, 5):
        assert not diya_actions.claims_a_proposal(said), said
