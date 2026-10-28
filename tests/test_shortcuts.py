"""Shortcuts: a short phrase that stands for a longer request (diya_shortcuts.py; docs/STUDY_ATTICUS.md), added 2026-10-28.

What this proves: "when I say X, do Y" is read by code and kept; the phrase later stands for the request when it is the WHOLE message; the model is handed the request, not the phrase; a phrase that could be a
yes or a no, a request that is a yes, a teaching or another shortcut, a chain and a 51st shortcut are all refused; shortcuts can be listed and forgotten; and nothing is expanded inside a longer message.
"""
import pytest

import diya
import diya_config
import diya_shortcuts as sc
from diya_db import Store
from fakes import FakeClient, text_reply


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "s.db"))


@pytest.mark.parametrize("text, phrase, asked", [
    ("when I say morning check, show me my reminders and tasks", "morning check", "show me my reminders and tasks"),
    ('Whenever I say "focus mode": list my tasks for today', '"focus mode"', "list my tasks for today"),
    ("if I type night wrap then please remind me to charge my phone at 10pm", "night wrap", "remind me to charge my phone at 10pm"),
])
def test_teaching_is_read_by_code(text, phrase, asked):
    assert sc.parse_teaching(text) == (phrase, asked)


@pytest.mark.parametrize("text", ["what is on my calendar", "when I say", "tell me when it rains", "x" * 500, "", None, 5])
def test_anything_else_is_not_teaching(text):
    assert sc.parse_teaching(text) is None


def test_a_taught_phrase_stands_for_its_request_only_as_the_whole_message(store):
    ok, words = sc.learn(store, '"Morning Check"', "show me my reminders and tasks")
    assert ok and 'When you say "morning check"' in words and "show me my reminders and tasks" in words
    for same in ("morning check", "Morning Check!", "  morning   check  ", '"morning check".'):
        assert sc.expand(store, same) == "show me my reminders and tasks"
    for other in ("morning check please", "do the morning check", "morning", "what is my morning check", ""):
        assert sc.expand(store, other) is None


def test_teaching_the_same_phrase_again_replaces_it_and_says_so(store):
    sc.learn(store, "morning check", "show me my reminders")
    ok, words = sc.learn(store, "Morning check", "show me my tasks for today")
    assert ok and "replaces the old one" in words and sc.expand(store, "morning check") == "show me my tasks for today" and len(sc.load(store)) == 1


@pytest.mark.parametrize("phrase", ["hi", "ok", "yes", "Yes!", "go ahead", "never mind", "do it", "no thanks", "x" * 41, "one two three four five six seven", "1234", ""])
def test_a_phrase_that_is_too_short_too_long_or_could_be_a_yes_or_a_no_is_refused(store, phrase):
    assert sc.learn(store, phrase, "show me my reminders and tasks")[0] is False and sc.load(store) == {}


@pytest.mark.parametrize("asked", ["yes", "go ahead", "no thanks", "short", "x" * 301, "show me\x00 my tasks", "when I say other thing, show me my tasks"])
def test_a_request_that_is_a_yes_a_teaching_or_not_plain_is_refused(store, asked):
    assert sc.learn(store, "morning check", asked)[0] is False and sc.load(store) == {}


def test_no_chains_a_shortcut_cannot_stand_for_another_shortcut_or_itself(store):
    sc.learn(store, "morning check", "show me my reminders and tasks")
    assert sc.learn(store, "start my day", "morning check")[0] is False
    assert sc.learn(store, "start my day", "Start my day")[0] is False


def test_at_most_fifty_are_kept(store):
    for n in range(sc.MAX_SHORTCUTS):
        assert sc.learn(store, f"routine number {n}", "show me my reminders and tasks")[0]
    ok, words = sc.learn(store, "one more thing", "show me my reminders and tasks")
    assert ok is False and "at most 50" in words
    assert sc.learn(store, "routine number 3", "show me my tasks for today")[0] is True  # replacing one is always allowed


def test_shortcuts_are_listed_and_forgotten_by_code(store):
    assert "no shortcuts yet" in sc.reply_to(store, "what shortcuts do I have")
    sc.reply_to(store, "when I say morning check, show me my reminders and tasks")
    assert '- "morning check": show me my reminders and tasks' in sc.reply_to(store, "list my shortcuts")
    assert sc.reply_to(store, "forget the shortcut Morning Check") == 'Forgot the shortcut "morning check".'
    assert sc.expand(store, "morning check") is None and "no shortcut called" in sc.reply_to(store, "forget the shortcut morning check")
    assert sc.reply_to(store, "tell me a joke") is None


def test_a_damaged_store_is_read_as_empty(store):
    conn = store.connect()
    conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (sc.KEY, "{not json"))
    conn.commit()
    conn.close()
    assert sc.load(store) == {} and sc.expand(store, "morning check") is None


# ---- through the agent --------------------------------------------------------------------------------------------------------------------------


def test_teaching_is_answered_by_code_and_the_phrase_later_reaches_the_model_as_the_request():
    agent = diya.Agent(diya_config.load_config(), client=FakeClient([text_reply("Here is your day.")]))  # one scripted reply: teaching must not ask the model
    answer, tools = agent.ask([{"role": "user", "content": "when I say morning check, tell me what is on my plate today"}])
    assert answer.startswith('Okay. When you say "morning check"') and tools == [] and agent.client.chat_calls == []
    answer, _ = agent.ask([{"role": "user", "content": "Morning check!"}])
    assert answer == "Here is your day."
    sent = agent.client.chat_calls[-1]["messages"]
    assert [m["content"] for m in sent if m.get("role") == "user"][-1] == "tell me what is on my plate today"  # the request, not the phrase


def test_a_phrase_inside_a_longer_message_is_left_alone():
    agent = diya.Agent(diya_config.load_config(), client=FakeClient([text_reply("ok")]))
    agent.ask([{"role": "user", "content": "when I say morning check, tell me what is on my plate today"}])
    agent.ask([{"role": "user", "content": "I did my morning check already"}])
    assert [m["content"] for m in agent.client.chat_calls[-1]["messages"] if m.get("role") == "user"][-1] == "I did my morning check already"


def test_a_shortcut_cannot_be_used_to_answer_an_action_that_is_waiting():
    agent = diya.Agent(diya_config.load_config(), client=FakeClient([]))
    answer, _ = agent.ask([{"role": "user", "content": "when I say sounds right, yes"}])
    assert "Okay. When you say" not in answer and sc.load(agent.store) == {}  # refused, and nothing was kept
