"""A greeting, thank-you or goodbye is made right in code after the model has written it (diya_intent.tidy_small_talk; docs/SPEED_DESIGN.md, "Greetings are tidied").

Measured first, with the real chat model, a greeting each time: with nothing in memory 11 of 12 replies addressed the person by a name nobody had given (Alex, or Diya, the assistant's own name), with
"Priya" in memory the right name was used 0 times and a wrong one 11, "Good morning" was said in the afternoon, and the prompt's "no emoji" and "never offer to assist" were not kept.

What this proves: a name that is not the person's is taken out and theirs is kept; the part of the day is the real one unless the person named one; pictures and an offer to assist are taken out; nothing
else the model wrote is touched; the person's name is only ever one a fact says; a bare "morning" is a greeting; and in the chat the reply is told whole (not streamed first), tidied, and never changes any
other kind of answer.

Hidden characters and pictures are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses
from datetime import datetime

import pytest

import diya
import diya_config
import diya_intent
import diya_memory
from fakes import FakeClient, text_reply

SMILE, SUN, HEART = chr(0x1F60A), chr(0x1F31E), chr(0x2764)


@pytest.mark.parametrize("reply, user, name, hour, expected", [
    (f"Good morning, Alex! {SMILE}", "hi", None, 14, "Good afternoon!"),
    ("Hi Alex, how's it going?", "hey", None, 9, "Hi, how's it going?"),
    ("Good morning, Priya. Glad you're feeling grateful.", "thanks", "Priya", 20, "Good evening, Priya. Glad you're feeling grateful."),
    ("Good morning, priya!", "hello", "Priya", 8, "Good morning, priya!"),
    (f"Good morning, Diya! {SMILE}", "hey diya", None, 10, "Good morning!"),
    ("Hello again, Diya.", "hey diya", None, 10, "Hello again."),
    ("Hi there, Alex! Hope you're well.", "hi", None, 10, "Hi there! Hope you're well."),
    ("Good evening Alex. How was your day?", "good evening", None, 9, "Good evening. How was your day?"),
    ("Hi Maya, how are you?", "hi", "Priya", 10, "Hi, how are you?"),
    ("Thanks Alex!", "thanks", None, 10, "Thanks!"),
    ("You're welcome, Alex. Good morning!", "thanks", None, 15, "You're welcome. Good morning!"),
])
def test_a_name_that_is_not_the_persons_is_taken_out_and_theirs_is_kept(reply, user, name, hour, expected):
    assert diya_intent.tidy_small_talk(reply, user, name, hour) == expected


@pytest.mark.parametrize("reply", ["Hi, how are you?", "Good morning, How are you?", "Hi there, how's your day?", "Hello! I'm glad to hear it.", "Thanks, Glad to help.", "Morning! Hope you slept well.",
                                   "Hello, hello", "Bye for now, take care.", "Hi. What are you up to?"])
def test_words_that_only_look_like_a_name_after_a_greeting_are_left_alone(reply):
    assert diya_intent.tidy_small_talk(reply, "hi", None, 10) == reply


@pytest.mark.parametrize("hour, part", [(0, None), (4, None), (5, "Good morning"), (11, "Good morning"), (12, "Good afternoon"), (16, "Good afternoon"), (17, "Good evening"), (21, "Good evening"), (22, None), (23, None)])
def test_the_part_of_the_day_is_the_real_one(hour, part):
    assert diya_intent.part_of_day(hour) == part
    got = diya_intent.tidy_small_talk("Good morning!", "hi", None, hour)
    assert got == (part + "!" if part else "Hi!")


def test_a_part_of_the_day_the_person_named_is_left_as_the_model_answered_it_and_good_night_is_never_touched():
    assert diya_intent.tidy_small_talk("Good evening!", "good evening", None, 9) == "Good evening!"
    assert diya_intent.tidy_small_talk("Good morning!", "morning", None, 15) == "Good morning!"
    assert diya_intent.tidy_small_talk("Good night!", "bye", None, 15) == "Good night!"


def test_only_the_opening_words_are_corrected_not_a_later_sentence():
    assert diya_intent.tidy_small_talk("Hello! Have a good morning tomorrow.", "hi", None, 15) == "Hello! Have a good morning tomorrow."
    assert diya_intent.tidy_small_talk("good morning, friend", "hi", None, 15) == "good afternoon, friend"


@pytest.mark.parametrize("reply, expected", [
    (f"Good morning! How can I assist you today? {SUN}", "Good morning!"),
    ("Hello. How may I help you? Hope you are well.", "Hello. Hope you are well."),
    ("What can I do for you today?", "Hi."),
    ("Hi! Is there anything else I can help with?", "Hi!"),
    (f"Hey {HEART}{chr(0xFE0F)} how are you", "Hey how are you"),
    (f"{SMILE}", "Hi."), ("", "Hi."), (None, "Hi."), (5, "Hi."),
])
def test_pictures_and_an_offer_to_assist_are_taken_out(reply, expected):
    assert diya_intent.tidy_small_talk(reply, "hi", None, 10) == expected


@pytest.mark.parametrize("texts, name", [
    (["Name is Priya."], "Priya"), (["my name is priya"], "Priya"), (["Favorite color is teal.", "Name is Sam"], "Sam"), (["name is Dr Rao"], None), (["My dog's name is Rocky"], None),
    (["Sister's name is Maya"], None), ([], None), ([5, None], None), (["name is X"], None), (["I know someone whose name is Priya"], None),
])
def test_the_persons_name_is_only_ever_one_a_fact_says(texts, name):
    assert diya_intent.known_name(texts) == name


@pytest.mark.parametrize("text", ["morning", "Evening!", "afternoon", "good morning", "hey"])
def test_a_bare_part_of_the_day_is_a_greeting(text):
    assert diya_intent.is_small_talk(text)


@pytest.mark.parametrize("text", ["morning plan my day", "afternoon tea recipes", "evening", "evening news at 9"])
def test_but_not_when_there_is_more(text):
    assert diya_intent.is_small_talk(text) == (text == "evening")


# --- in the chat ----------------------------------------------------------------------------------------------------------------


def make_agent(tmp_path, replies, hour=14, name=None):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "g.db"), profile_path=str(tmp_path / "p.txt"), lookup=False)
    agent = diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: datetime(2026, 10, 11, hour, 20))
    if name:
        diya_memory.open_memory(agent.store, config).add_manual(f"name is {name}", "api")
    return agent


def test_a_greeting_is_told_whole_and_tidied_even_when_the_page_is_listening(tmp_path):
    agent = make_agent(tmp_path, [text_reply(f"Good morning, Alex! {SMILE}")])
    events = []
    answer, tools = agent.ask([{"role": "user", "content": "hi"}], on_event=lambda kind, detail: events.append((kind, detail)))
    assert answer == "Good afternoon!" and tools == []
    assert "stream" not in agent.client.chat_calls[0]["options"] and not [e for e in events if e[0] == "delta"]


def test_the_name_in_memory_is_kept_and_a_different_one_is_not(tmp_path):
    agent = make_agent(tmp_path, [text_reply("Good afternoon, Priya!"), text_reply("Good afternoon, Maya!")], name="Priya")
    assert agent.ask([{"role": "user", "content": "hey"}])[0] == "Good afternoon, Priya!"
    assert agent.ask([{"role": "user", "content": "hey"}])[0] == "Good afternoon!"


def test_a_thank_you_and_a_goodbye_are_tidied_too(tmp_path):
    agent = make_agent(tmp_path, [text_reply(f"You're welcome, Alex! {SMILE}"), text_reply("Bye Alex, see you soon.")])
    assert agent.ask([{"role": "user", "content": "thanks"}])[0] == "You're welcome!"
    assert agent.ask([{"role": "user", "content": "bye"}])[0] == "Bye, see you soon."


def test_the_greeting_prompt_no_longer_invites_a_guessed_name():
    assert "Use their name if it is given" not in diya.SMALL_TALK_PROMPT
    assert "otherwise use no name at all" in diya.SMALL_TALK_PROMPT and "you are Diya, they are not" in diya.SMALL_TALK_PROMPT


def test_nothing_else_is_tidied_an_answer_with_a_picture_or_a_name_stays_as_the_model_wrote_it(tmp_path):
    agent = make_agent(tmp_path, [text_reply(f"Sure! Hi Alex {SMILE} the capital is Paris."), text_reply("Got it.")])
    assert agent.ask([{"role": "user", "content": "what is the capital of France?"}])[0] == f"Sure! Hi Alex {SMILE} the capital is Paris."
    assert agent.ask([{"role": "user", "content": "my flight is on Friday at 6"}])[0] == "Got it."
