"""The model's side of repeating reminders (docs/SCHEDULE_DESIGN.md, D7 and unit R3): add_reminder's `repeat` argument.

What this proves: a repeat the person said is read by code and saved as a series, with the chat and message it answers; a repeat
the person did not say is left out and the reminder is saved as a one-off (and the model is told), unless they did talk about
repeating, in which case the model changed their words and is told to try again; a repeat that cannot be read saves nothing and
says why; `due_at` is ignored beside a repeat and the answer says so; the guard that nothing is saved unless the message asks for a
reminder still comes first; what is saved is exactly what the answer says; and the one-off path is what it was before.
"""
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_config
import diya_intent
import diya_repeat
import diya_schedule
import diya_time
from fakes import FakeClient, text_reply, tool_reply

NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(diya_config.load_config(), db_path=str(tmp_path / "r.db"), profile_path=str(tmp_path / "p.txt"),
                               connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"))


def make_agent(config, *replies):
    return diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: NOW, action_kinds=())


def saying(config, message, **args):
    """Ask `message` with a scripted model that calls add_reminder(**args); return (agent, what the model was told)."""
    import json

    agent = make_agent(config, tool_reply("add_reminder", json.dumps(args)), text_reply("ok"))
    agent.ask([{"role": "user", "content": message}], thread_id=3, message_id=8)
    told = [m["content"] for m in agent.client.chat_calls[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"][-1]
    return agent, told


def ts(local):
    return diya_time.iso_of_local(local)


# ---- a repeat the person said -------------------------------------------------------------------------------

def test_a_repeat_the_person_said_is_saved_as_a_series_with_the_chat_and_message_it_answers(config):
    agent, told = saying(config, "Remind me every Monday at 9am to take out the bins", content="take out the bins", repeat="every Monday at 9am")
    (series,) = agent.schedule.series()
    assert (series["content"], series["rule"], series["said"], series["source"], series["thread_id"], series["message_id"]) == (
        "take out the bins", "weekly:0@09:00", "every Monday at 9am", "chat", 3, 8)
    assert series["next_ts"] == ts(datetime(2026, 10, 12, 9, 0))
    assert told == "Repeating reminder saved: take out the bins. Every Monday at 09:00. The first one is Monday 12 Oct 2026, 09:00."
    assert agent.store.reminders("all") == []  # nothing is due yet, and no one-off was saved beside it
    assert [(e["event"], e["actor"]) for e in agent.schedule.events()] == [("created", "model")]


def test_what_the_rule_filled_in_is_told_to_the_model(config):
    _, told = saying(config, "remind me every Friday to send the timesheet", content="send the timesheet", repeat="every Friday")
    assert told == ("Repeating reminder saved: send the timesheet. Every Friday at 09:00. The first one is Friday 16 Oct 2026, 09:00. "
                    "(no time was given, so 09:00)")


@pytest.mark.parametrize("message, repeat, rule", [
    ("Remind me on the 1st of every month to pay rent", "on the 1st of every month", "monthly:1@09:00"),
    ("Remind me every night at 10pm to lock up", "every night at 10pm", "daily@22:00"),
    ("remind me on weekdays at 7am to pack my lunch", "on weekdays at 7am", "weekdays@07:00"),
    ("Please remind me every Tuesday and Thursday at 6pm to water the plants", "every Tuesday and Thursday at 6pm", "weekly:1,3@18:00"),
    ("Remind me every 2 weeks at 10am to submit the report", "every 2 weeks at 10am", "every:14@10:00#2026-10-11"),
    ("REMIND ME EVERY DAY AT 8AM TO TAKE PILLS", "every day at 8am", "daily@08:00"),  # other capitals are the same words
    ("Remind me every day at 8am. to take pills", "Every day at 8am.", "daily@08:00"),  # and so is a full stop
])
def test_the_ways_of_saying_it_that_are_the_persons_own_words_are_kept(config, message, repeat, rule):
    agent, told = saying(config, message, content="x", repeat=repeat)
    assert [s["rule"] for s in agent.schedule.series()] == [rule] and told.startswith("Repeating reminder saved: x.")


def test_due_at_beside_a_repeat_is_ignored_and_the_answer_says_so(config):
    agent, told = saying(config, "Remind me every Monday at 9am to take out the bins", content="bins", repeat="every Monday at 9am", due_at="Monday 9am")
    assert agent.store.reminders("all") == [] and len(agent.schedule.series()) == 1
    assert told.endswith("The separate time (due_at) was ignored: the repeat carries the time.")


@pytest.mark.parametrize("due_at", [None, "", "   "])
def test_no_due_at_is_nothing_to_ignore(config, due_at):
    _, told = saying(config, "Remind me every Monday at 9am to take out the bins", content="bins", repeat="every Monday at 9am", due_at=due_at)
    assert "ignored" not in told


@pytest.mark.parametrize("repeat", ["", "   ", None])
def test_an_empty_repeat_is_no_repeat_and_the_reminder_is_a_one_off(config, repeat):
    agent, told = saying(config, "Remind me tomorrow at 5pm to call mum", content="call mum", due_at="tomorrow at 5pm", repeat=repeat)
    assert told.startswith("Reminder saved: call mum, for Sunday 11 Oct 2026, 17:00") and "repeat" not in told
    assert agent.schedule.series("all") == [] and len(agent.store.reminders("all")) == 1


# ---- a repeat the person did not say -------------------------------------------------------------------------

def test_a_repeat_the_person_did_not_say_is_left_out_and_the_reminder_is_a_one_off_and_the_model_is_told(config):
    agent, told = saying(config, "Remind me tomorrow at 5pm to call mum", content="call mum", due_at="tomorrow at 5pm", repeat="every day at 5pm")
    assert agent.schedule.series("all") == []
    (row,) = agent.store.reminders("all")
    assert (row["content"], row["due_ts"]) == ("call mum", ts(datetime(2026, 10, 11, 17, 0)))
    assert told == ("Reminder saved: call mum, for Sunday 11 Oct 2026, 17:00 "
                    "It does not repeat: 'every day at 5pm' was left out, because the user did not say it repeats.")


def test_with_nothing_else_a_repeat_that_was_not_said_leaves_a_reminder_with_no_time_and_says_both(config):
    agent, told = saying(config, "Remind me to renew my passport", content="renew my passport", repeat="every year")
    assert agent.schedule.series("all") == []
    assert told.startswith("Reminder saved: renew my passport. It has NO time") and told.endswith("because the user did not say it repeats.")


def test_a_repeat_the_model_changed_when_the_person_did_talk_about_repeating_is_not_saved_and_the_model_is_told_to_ask_again(config):
    # "every second Tuesday" is something the reader refuses, so there are no words of theirs to use: the model's own change is not accepted
    agent, told = saying(config, "Remind me to take out the bins every second Tuesday", content="bins", repeat="every 2 weeks on Tuesday")
    assert agent.schedule.series("all") == [] and agent.store.reminders("all") == []
    assert told == ("Not saved: the repeat 'every 2 weeks on Tuesday' is not the user's words. Pass the repeat exactly as the user said it "
                    "(their own words, nothing added or left out); if they did not say how often or when, ask them, then try again.")


def test_a_repeat_made_up_for_a_message_that_says_every_in_another_sense_is_refused_not_silently_dropped(config):
    agent, told = saying(config, "Remind me to give every kid their medicine tomorrow at 8am", content="give every kid their medicine",
                         due_at="tomorrow at 8am", repeat="every day at 8am")
    assert "is not the user's words" in told and agent.schedule.series("all") == [] and agent.store.reminders("all") == []


def test_what_the_person_said_but_cannot_be_read_saves_nothing_and_says_why(config):
    agent, told = saying(config, "Remind me every hour to stretch", content="stretch", repeat="every hour")
    assert agent.schedule.series("all") == [] and agent.store.reminders("all") == []
    assert told.startswith("Not saved: I could not read 'every hour' as a repeat (more often than once a day is not supported; give a time of day and 'every day').")
    assert told.endswith("or when, ask them, then try again.")


def test_a_repeat_that_is_not_words_is_refused(config):
    _, told = saying(config, "Remind me to take out the bins", content="bins", repeat=5)
    assert told == "Not saved: the repeat must be given in words, like 'every Monday at 9am'."


# ---- the person's own words are the rule (D7, as measured: the model splits the time off, paraphrases, or drops the repeat) ------------

def test_the_time_the_person_said_is_the_time_saved_even_when_the_model_split_it_off_into_due_at(config):
    # measured on qwen2.5:3b: repeat "every day" and due_at "8am" saved 09:00 while the answer to the person said 8 AM
    agent, told = saying(config, "Remind me every day at 8am to take my pills", content="take my pills", due_at="8am", repeat="every day")
    (series,) = agent.schedule.series()
    assert (series["rule"], series["said"]) == ("daily@08:00", "every day at 8am")
    assert told == ("Repeating reminder saved: take my pills. Every day at 08:00. The first one is Sunday 11 Oct 2026, 08:00. "
                    "The separate time (due_at) was ignored: the repeat carries the time.")
    assert agent.store.reminders("all") == []


def test_a_repeat_the_person_said_is_saved_even_when_the_model_passed_none(config):
    # measured on qwen2.5:3b: "every Monday at 9am" saved as a single reminder, and the model told the person it repeated
    agent, told = saying(config, "Remind me every Monday at 9am to take out the bins", content="take out the bins", due_at="9am Monday")
    (series,) = agent.schedule.series()
    assert (series["rule"], series["said"], series["source"]) == ("weekly:0@09:00", "every Monday at 9am", "chat")
    assert told.startswith("Repeating reminder saved: take out the bins. Every Monday at 09:00.") and agent.store.reminders("all") == []


def test_a_paraphrase_of_the_repeat_is_not_refused_because_the_rule_is_read_from_what_the_person_said(config):
    # measured on qwen3:4b-instruct: "daily at noon" passed as "every day at noon" was refused, and the person was asked to confirm their wording
    agent, told = saying(config, "Remind me daily at noon to drink water", content="drink water", repeat="every day at noon")
    (series,) = agent.schedule.series()
    assert (series["rule"], series["said"]) == ("daily@12:00", "daily at noon") and told.startswith("Repeating reminder saved: drink water. Every day at 12:00.")


@pytest.mark.parametrize("message, said, rule", [
    ("Remind me on the 1st of every month to pay rent", "on the 1st of every month", "monthly:1@09:00"),
    ("remind me on weekdays at 7am to pack my lunch", "on weekdays at 7am", "weekdays@07:00"),
    ("Remind me every evening at 7pm to call mum", "every evening at 7pm", "daily@19:00"),
    ("Please remind me every Tuesday and Thursday at 6pm to water the plants", "every Tuesday and Thursday at 6pm", "weekly:1,3@18:00"),
    ("Every Monday at 9am, remind me to take out the bins", "Every Monday at 9am", "weekly:0@09:00"),
    ("Remind me to stretch every morning.", "every morning", "daily@09:00"),
])
def test_the_forms_people_ask_in_are_each_read_from_their_own_words(config, message, said, rule):
    agent, _ = saying(config, message, content="the thing")
    (series,) = agent.schedule.series()
    assert (series["said"], series["rule"]) == (said, rule)


def test_when_the_model_names_a_different_repeat_the_persons_words_win(config):
    agent, _ = saying(config, "Remind me every Monday at 9am to take out the bins", content="bins", repeat="every Tuesday at 10am")
    (series,) = agent.schedule.series()
    assert (series["rule"], series["said"]) == ("weekly:0@09:00", "every Monday at 9am")


@pytest.mark.parametrize("message", [
    "Remind me to call mum tomorrow at 5pm, I do it every Sunday",  # the repeat is another clause
    "Remind me to call mum tomorrow at 5pm because I phone her every Sunday",
    "Remind me to call mum tomorrow at 5pm. I do it every Sunday",
])
def test_a_repeat_that_is_part_of_something_else_does_not_make_the_reminder_repeat(config, message):
    agent, told = saying(config, message, content="call mum", due_at="tomorrow at 5pm")
    assert agent.schedule.series("all") == [] and [r["content"] for r in agent.store.reminders("all")] == ["call mum"]
    assert told.startswith("Reminder saved: call mum")


@pytest.mark.parametrize("message", [
    "Remind me every Monday until June to take out the bins",
    "Remind me every day except Sunday to stretch",
    "Remind me every Monday and every Friday to send the report",
    "Remind me every second Tuesday to water the plants",
    "Remind me every hour to stretch",
])
def test_words_that_would_change_the_repeat_are_not_guessed_at_so_nothing_repeats_without_the_model_asking(config, message):
    agent, _ = saying(config, message, content="the thing", due_at="tomorrow at 9am")
    assert agent.schedule.series("all") == []


# ---- the rest of what is checked --------------------------------------------------------------------------------

def test_the_guard_comes_first_a_message_that_does_not_ask_for_a_reminder_saves_nothing_even_with_a_repeat(config):
    agent, told = saying(config, "I go to the gym every Monday at 9am", content="gym", repeat="every Monday at 9am")
    assert told == diya.REMINDER_NOT_ASKED and agent.schedule.series("all") == [] and agent.store.reminders("all") == []


@pytest.mark.parametrize("content, why", [("", "needs something"), ("   ", "needs something"), (None, "needs something"),
                                          ("x" * 301, "over 300 characters")])
def test_words_that_are_not_a_reminder_are_refused_with_or_without_a_repeat(config, content, why):
    agent, told = saying(config, "Remind me every day at 8am to take pills", content=content, repeat="every day at 8am")
    assert told.startswith("Not saved:") and why in told and agent.schedule.series("all") == []


def test_the_same_repeating_reminder_twice_is_refused_and_the_model_is_told_where_it_stands(config):
    agent, _ = saying(config, "Remind me every Monday at 9am to take out the bins", content="take out the bins", repeat="every Monday at 9am")
    agent.client.replies.extend([tool_reply("add_reminder", '{"content": "Take out the BINS", "repeat": "every Monday at 9am"}'), text_reply("ok")])
    agent.ask([{"role": "user", "content": "Remind me every Monday at 9am to take out the bins"}])
    told = [m["content"] for m in agent.client.chat_calls[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"][-1]
    assert told == "Not saved: that repeating reminder is already set. Do not set it again; tell the user it is already there."
    assert len(agent.schedule.series("all")) == 1


def test_too_many_repeating_reminders_is_told_to_the_model(config, monkeypatch):
    monkeypatch.setattr(diya_schedule, "MAX_ACTIVE", 1)
    agent, _ = saying(config, "Remind me every Monday at 9am to take out the bins", content="bins", repeat="every Monday at 9am")
    agent.client.replies.extend([tool_reply("add_reminder", '{"content": "other", "repeat": "every Tuesday at 9am"}'), text_reply("ok")])
    agent.ask([{"role": "user", "content": "Remind me every Tuesday at 9am to do the other thing"}])
    told = [m["content"] for m in agent.client.chat_calls[-1]["messages"] if isinstance(m, dict) and m.get("role") == "tool"][-1]
    assert told == "Not saved: 1 repeating reminders are already set; stop one before making another. Tell the user."


def test_a_hidden_character_in_the_words_is_refused_not_saved(config):
    agent, told = saying(config, "Remind me every day at 8am to take pills", content="take" + chr(7) + "pills", repeat="every day at 8am")
    assert told.startswith("Not saved:") and "cannot contain the character" in told and agent.schedule.series("all") == []


def test_outside_a_turn_nothing_is_judged_by_an_old_message_and_the_ids_are_empty(config):
    agent = make_agent(config)
    said = agent.add_reminder("take out the bins", repeat="every Monday at 9am")
    assert said.startswith("Repeating reminder saved: take out the bins.")
    series = agent.schedule.get(1)
    assert (series["thread_id"], series["message_id"]) == (None, None)
    assert agent.add_reminder("a", "tomorrow at 5pm", repeat="every day at 8am").startswith("Repeating reminder saved: a.")  # no message to judge by


def test_a_repeat_that_cannot_be_read_outside_a_turn_is_refused_too(config):
    assert make_agent(config).add_reminder("a", repeat="soon").startswith("Not saved: I could not read 'soon' as a repeat")


def test_the_series_is_read_against_the_agents_own_clock(config):
    agent = diya.Agent(config, client=FakeClient(), clock=lambda: datetime(2026, 12, 31, 23, 0), action_kinds=())
    agent.add_reminder("fireworks", repeat="every day at 11:30pm")
    assert agent.schedule.get(1)["next_ts"] == ts(datetime(2026, 12, 31, 23, 30))


def test_the_one_off_path_is_what_it_was(config):
    agent = make_agent(config)
    assert agent.add_reminder("call mum", "tomorrow at 5pm") == "Reminder saved: call mum, for Sunday 11 Oct 2026, 17:00"
    assert agent.add_reminder("water plants").startswith("Reminder saved: water plants. It has NO time")
    assert agent.add_reminder("x", "soonish").startswith("Not saved: I could not tell when 'soonish' is")
    assert agent.add_reminder("x", 5) == "Not saved: the time must be given in words, like 'Friday 5pm' or 'in 2 hours'."


def test_a_repeating_reminder_the_model_made_is_what_the_model_then_reads_back(config):
    agent, _ = saying(config, "Remind me every Monday at 9am to take out the bins", content="take out the bins", repeat="every Monday at 9am")
    assert agent.list_reminders().split("\n") == [
        "No pending reminders.", "Repeating reminders:",
        "repeat #1: take out the bins (every monday at 09:00; next Monday 12 Oct 2026, 09:00)",
    ]


# ---- the tool as the model sees it ---------------------------------------------------------------------------

def test_the_repeat_argument_is_optional_and_says_when_to_use_it_and_to_leave_due_at_out():
    spec = {t["function"]["name"]: t["function"] for t in diya.TOOLS}["add_reminder"]["parameters"]
    assert spec["required"] == ["content"] and set(spec["properties"]) == {"content", "due_at", "repeat"}
    said = spec["properties"]["repeat"]["description"]
    assert "ONLY if the user said" in said and "leave due_at out" in said and "every Monday at 9am" in said


def test_what_counts_as_talking_about_repeating():
    for text in ("every kid", "Each day", "DAILY", "weekly", "on weekdays", "a weekday", "hourly", "recurring", "repeats", "repeat it", "yearly", "annually"):
        assert diya_intent.mentions_repeat(text) is True, text
    for text in ("tomorrow at 5pm", "everyone", "everything", "never", "dailyish", "", "weekend"):
        assert diya_intent.mentions_repeat(text) is False, text
    for junk in (None, 5, ["every"], b"every"):
        assert diya_intent.mentions_repeat(junk) is False


# ---- is the repeat part of the request? (diya_intent.attached_repeat) -----------------------------------------------

@pytest.mark.parametrize("message, words", [
    ("Remind me every day at 8am to take my pills", "every day at 8am"),
    ("remind me on weekdays at 7am to pack my lunch", "on weekdays at 7am"),
    ("Can you remind me on the 1st of every month to pay rent", "on the 1st of every month"),
    ("Set a reminder every Saturday at 10am to clean the car", "every Saturday at 10am"),
    ("Set a reminder to water the plants every Saturday at 10am", "every Saturday at 10am"),  # the content first, the repeat after it
    ("Remind me to take pills every day at 8am", "every day at 8am"),
    ("remind me to stretch every morning.", "every morning"),
    ("Every Monday at 9am, remind me to take out the bins", "Every Monday at 9am"),  # the repeat first
    ("Every Monday at 9am please remind me to take out the bins", "Every Monday at 9am"),
    ("Every Monday at 9am and remind me to take out the bins", "Every Monday at 9am"),
    ("Don't let me forget to stretch every morning", "every morning"),
    ("Remind me every day at 8am about my pills", "every day at 8am"),
    ("Remind me every day at 8am that the bins go out", "every day at 8am"),
    ("Remind me every day at 8am", "every day at 8am"),  # no content at all: still what they asked
    ("Remind me every day at 8am please", "every day at 8am"),
])
def test_a_repeat_that_is_part_of_the_request_is_found_as_the_persons_words(message, words):
    assert diya_intent.attached_repeat(message, NOW) == words


@pytest.mark.parametrize("message", [
    "I go to the gym every Monday and Wednesday",  # no reminder asked for
    "What repeats every week?",
    "Remind me to call mum tomorrow, I do it every Sunday",  # a different clause
    "Remind me to call mum tomorrow because I phone her every Sunday",
    "Remind me to call mum tomorrow. I do it every Sunday",
    "Remind me to call mum tomorrow; she is out every Sunday",
    "Remind me to call mum tomorrow, but she is out every Sunday",
    "Remind me every day except Sunday to stretch",  # words after it that could change it
    "Remind me every Monday and every Friday to send the report",
    "Remind me every Monday until June to call",
    "Remind me every hour to stretch",
    "Remind me to give every kid their medicine tomorrow at 8am",
    "Remind me to stretch",
    "Every Monday at 9am I take out the bins and you should remind me",  # the request is far from the repeat
    "",
])
def test_a_repeat_that_is_not_part_of_the_request_is_not_found_to_be(message):
    assert diya_intent.attached_repeat(message, NOW) is None


@pytest.mark.parametrize("junk", [None, 5, ["remind me every day"], b"remind me every day", True])
def test_what_is_not_text_has_no_attached_repeat(junk):
    assert diya_intent.attached_repeat(junk, NOW) is None


def test_a_curly_apostrophe_in_the_request_is_read_as_a_straight_one_and_the_places_still_line_up():
    message = "Don’t let me forget to stretch every morning"
    assert diya_intent.attached_repeat(message, NOW) == "every morning"


def test_the_labelled_requests_are_each_attached_and_nothing_else_labelled_is():
    from labelled_repeats import NOT_A_REMINDER, ONE_OFF, REPEAT_ASKED, REPEAT_UNSUPPORTED

    for text, _ in REPEAT_ASKED:
        assert diya_intent.attached_repeat(text, NOW) is not None, text
    for text in REPEAT_UNSUPPORTED + ONE_OFF + NOT_A_REMINDER:
        assert diya_intent.attached_repeat(text, NOW) is None, text


# ---- what the mutation run found nothing checking (the intent helpers) -------------------------------------------------

@pytest.mark.parametrize("message, words", [
    ("Remind me every day at 8am, take my pills", "every day at 8am"),  # a pause, then the content
    ("Remind me every Monday at 9am for the bins", "every Monday at 9am"),
    ("Remind me every day at 8am thanks", "every day at 8am"),
    ("Every Monday at 9am then remind me to take out the bins", "Every Monday at 9am"),
    ("Every Monday at 9am just remind me to take out the bins", "Every Monday at 9am"),
    ("Every Monday at 9am, can you remind me to take out the bins", "Every Monday at 9am"),
    ("Every Monday at 9am could you remind me to take out the bins", "Every Monday at 9am"),
    ("Remind me every day at 8am about, um, my pills", "every day at 8am"),
])
def test_the_other_ways_a_repeat_is_part_of_a_request_are_found(message, words):
    assert diya_intent.attached_repeat(message, NOW) == words


@pytest.mark.parametrize("message", [
    "Remind me to call mum tomorrow while she is out every Sunday",
    "Remind me to call mum tomorrow whereas she is out every Sunday",
    "Remind me to call mum tomorrow although she is out every Sunday",
])
def test_a_repeat_after_a_conjunction_is_another_clause(message):
    assert diya_intent.attached_repeat(message, NOW) is None


@pytest.mark.parametrize("text", ["monthly", "a monthly report", "recurring", "yearly", "annually", "hourly", "repeats", "repeating"])
def test_the_words_that_mean_a_repeat_all_count_as_talking_about_one(text):
    assert diya_intent.mentions_repeat(text) is True


# ---- phrasings written after the reader was built, not while tuning it (29 of 30 behaved; the one that did not is below) -----

FRESH = [
    ("Hey, can you remind me every Sunday at 7pm to call my parents?", "weekly:6@19:00"),
    ("remind me to submit my timesheet every Friday at 4pm", "weekly:4@16:00"),
    ("Remind me each Wednesday to put the recycling out", "weekly:2@09:00"),
    ("Please set a reminder for every weekday at 6pm to log my hours", "weekdays@18:00"),
    ("Can you remind me daily at 9pm to charge my phone", "daily@21:00"),
    ("remind me on the 5th of every month to pay the electricity bill", "monthly:5@09:00"),
    ("Remind me every month on the 1st at 8am to back up my laptop", "monthly:1@08:00"),
    ("set a reminder every 3 days at noon to rotate the plants", "every:3@12:00"),
    ("remind me every weekday morning to check my email", "weekdays@09:00"),
    ("Every Saturday morning remind me to go to the market", "weekly:5@09:00"),
    ("Remind me every night at 11pm to turn off the heater", "daily@23:00"),
    ("don't let me forget to stretch every day at 3pm", "daily@15:00"),
    ("remind me every day to drink water", "daily@09:00"),
    ("Remind me weekly on Thursday at 5pm to send the report", "weekly:3@17:00"),
    ("Remind me monthly on the 20th to renew the parking permit", "monthly:20@09:00"),
    ("Remind me every Mon, Wed and Fri at 7am to go for a run", "weekly:0,2,4@07:00"),
]
FRESH_NOT_REPEATING = [
    "remind me every other Tuesday at 10am to water the ferns",  # "every other Tuesday" is the second-Tuesday kind of rule: refused
    "remind me every 2 weeks on Friday to review the budget",  # two readings: not guessed
    "Remind me tomorrow at 9am to call the dentist",
    "Remind me to take out the bins on Monday at 8am",
    "Remind me to water the plants, I do it every Sunday",
    "Remind me about my flight on Friday at 6pm",
    "Remind me to buy bread, we eat it every day",
    "remind me in 2 hours to check the oven, it usually takes every bit of that",
    "Remind me on the 3rd to pay rent",
    "Remind me to call every client by Friday",
    "Remind me every day until Friday to take the antibiotics",
    "Remind me every hour to drink water",
    "I need a reminder every morning at 7:30 to take my vitamins",  # not read: "a reminder" with no verb is not a phrase the request check knows, so it fails safe
]


@pytest.mark.parametrize("message, rule", FRESH)
def test_phrasings_written_after_the_reader_was_built_are_read_to_the_right_rule(message, rule):
    words = diya_intent.attached_repeat(message, NOW)
    assert words is not None and diya_repeat.parse_repeat(words, NOW).canonical().split("#")[0] == rule


@pytest.mark.parametrize("message", FRESH_NOT_REPEATING)
def test_phrasings_that_must_not_make_a_repeating_reminder_do_not(message):
    assert diya_intent.attached_repeat(message, NOW) is None
