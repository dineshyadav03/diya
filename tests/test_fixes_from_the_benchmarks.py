"""Faults the 2026-10-26 benchmark run found, fixed and kept as tests (docs/BENCHMARK_2026-10-26.md; docs/HELDOUT_BENCH.md).

* The capture-gate benchmark: the code decided "this is a reminder request" for a refusal ("please don't set a reminder for that"), for a question about the phrase ("what does 'remind me' mean in spanish", "how do i
  set a reminder on my phone") and for a habit ("i remember to lock the door every night"). A real request is still one, including "remind me how to work the thermostat at 6", which holds the question words.
* The memory question-and-answer benchmark: "I switched to tea, I stopped drinking coffee" was held back as ungrounded (the fact's wording "The user no longer drinks coffee and now drinks tea" has words the person
  never says). The boilerplate words of a fact are not evidence against it; a fact that names something the person never mentioned is still ungrounded.
* The held-out benchmark: plain statements typed as a person types them ("i switched from physics to computer science", "my favourite subject is organic chemistry but i hate the labs", "also my roommate moved out on
  the 2nd...") were answered with a paragraph; and a folder that is not there ("my notes folder") sent the model away to ask the person. Needs, questions and requests are still never statements.
"""
import pytest

import diya
import diya_checks as checks
import diya_intent as intent


@pytest.mark.parametrize("text", [
    "Please don't set a reminder for that", "never remind me about that again", "do not remind me", "no need to set a reminder",
    "What does 'remind me' mean in Spanish?", "How do I set a reminder on my phone?", "what is a reminder app", "I remember to lock the door every night", "i always remember to call my mum",
])
def test_a_refusal_a_question_about_reminders_and_a_habit_are_not_requests_for_one(text):
    assert not intent.is_reminder_request(text)


@pytest.mark.parametrize("text", [
    "remind me to call mom tomorrow at 5", "set a reminder for the dentist on friday", "dont let me forget my passport on friday morning", "Remember to buy milk", "never let me forget the rent",
    "remind me how to work the thermostat at 6pm", "can you remind me to submit the report", "please set an alarm for 7", "add a reminder to renew my pass", "remind me every monday to take the bins out",
])
def test_a_real_request_for_a_reminder_still_is_one(text):
    assert intent.is_reminder_request(text)


def test_the_boilerplate_of_a_facts_wording_is_not_evidence_against_it():
    assert not ({"user", "now", "longer", "currently"} & set(checks.content_words("The user no longer drinks coffee and now currently drinks tea")))
    score, _ = checks.grounding("The user no longer drinks coffee and now drinks tea.", [(1, "I always drink coffee in the morning."), (2, "Actually I switched to tea, I stopped drinking coffee.")])
    assert score >= checks.GROUNDED_MIN
    # a fact that names what the person never mentioned is still not grounded
    assert checks.grounding("The user owns a parrot called Max", [(1, "I like tea and long walks")])[0] < checks.GROUNDED_MIN


@pytest.mark.parametrize("text", [
    "i switched from physics to computer science this semester", "my favourite subject is organic chemistry but i hate the labs", "also my roommate moved out on the 2nd so rent is split two ways now",
    "I enrolled in a pottery class", "i joined the debate club", "i bought a new laptop", "i am studying law", "oh and my sister lives in Pune now",
])
def test_plain_statements_typed_the_way_people_type_are_recognised(text):
    assert intent.is_fact_share(text)


@pytest.mark.parametrize("text", [
    "i feel terrible today", "i switched to the new app, can you help me log in", "which phone should i switch to", "i want to switch to computer science", "also remind me to call mom on the 5th",
    "also can you check my favourite recipe", "i need to buy a bought bread", "i have a problem with my enrolled courses", "what is my favourite subject?", "ugh i still have to clean my room",
])
def test_a_feeling_a_question_a_need_a_request_or_a_chore_is_still_never_a_statement(text):
    assert not intent.is_fact_share(text)


def test_a_folder_that_is_not_there_says_so_and_shows_what_the_main_folder_holds_never_a_path_on_this_computer(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "plans.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / "server.pem").write_text("k", encoding="utf-8")
    said = diya.list_files("notes", roots=(str(tmp_path),))
    assert said.startswith("There is no folder called 'notes' here.") and "docs/" in said and "plans.txt" in said  # a folder is marked, so that it is not taken for a file
    assert str(tmp_path) not in said and ".env" not in said and "server.pem" not in said  # no path on this computer, no secret-shaped name
    assert diya.list_files(".", roots=(str(tmp_path),)).split("\n").count("plans.txt") == 1  # a real folder works as before
    assert diya.list_files("docs", roots=(str(tmp_path),)) == ""
    assert diya.list_files("../..", roots=(str(tmp_path),)).startswith("Can't list")  # an escape is still refused, not explained
    assert diya.list_files("plans.txt", roots=(str(tmp_path),)).startswith("There is no folder called 'plans.txt' here.")  # a file is not a folder


def test_a_missing_folder_in_an_empty_or_a_long_main_folder(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert diya.list_files("notes", roots=(str(empty),)) == "There is no folder called 'notes' here. The main folder is empty."
    long = tmp_path / "long"
    long.mkdir()
    for number in range(diya.MISSING_FOLDER_LISTED + 7):
        (long / f"f{number:03d}.txt").write_text("x", encoding="utf-8")
    said = diya.list_files("notes", roots=(str(long),))
    assert "f000.txt" in said and f"f{diya.MISSING_FOLDER_LISTED - 1:03d}.txt" in said and f"f{diya.MISSING_FOLDER_LISTED:03d}.txt" not in said and "(and 7 more)" in said
