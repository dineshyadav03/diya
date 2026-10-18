"""A correction that names the thing by a pronoun ("Actually his name is Hogg, not Hog"), added 2026-10-18 after the Hog regression (tests/test_hog_regression.py) showed it was never read.

What this proves: a correction of four words or more is read for facts even without "I" or "my" in it (and "no thanks" is not); capture gives the model the message before it, so "his" is somebody, and only
then; a correction that looks like what it corrects is no longer held up by the similar check, but only when the model clearly names the fact it replaces (anything else still waits for a question).
"""
import pytest

import diya_autonomy as auto
import diya_intent
from fakes import ByQuestionClient
from test_autonomy import NOW, stage, world  # noqa: F401 -- `world` is a fixture
from test_live_capture import chat_parts  # noqa: F401 -- a fixture


@pytest.mark.parametrize("text", ["Actually his name is Hogg, not Hog", "No, his name is Hogg", "Actually she works at a hospital now", "that's wrong, it moved to Pune last week"])
def test_a_correction_that_names_its_thing_by_a_pronoun_is_read_for_facts(text):
    assert diya_intent.is_worth_capturing(text)


@pytest.mark.parametrize("text", ["no thanks", "No way", "actually, what is his name?", "his name is Hogg", "Actually please remind me tomorrow"])
def test_a_short_no_a_question_a_plain_statement_with_no_first_person_and_a_request_are_not(text):
    assert not diya_intent.is_worth_capturing(text)


def test_the_model_is_given_the_message_before_a_pronoun_correction_and_only_then(chat_parts):
    client, agent, model = chat_parts(client=ByQuestionClient(extraction=["- has a dog named Hog", "- has a dog named Hogg"], replace=["1"]))
    client.post("/api/chat", json={"message": "I got another dog named Hog"})
    client.post("/api/chat", json={"message": "Actually his name is Hogg, not Hog"})
    first, second = [call["messages"][0]["content"] for call in model.asked("extraction")]
    assert "Hogg" not in first and "- I got another dog named Hog" in second and "- Actually his name is Hogg, not Hog" in second
    client.post("/api/chat", json={"message": "Actually I live in Pune now"})  # a correction with "I" in it needs no context
    assert len(model.asked("extraction")) == 3 and "dog named Hog" not in model.asked("extraction")[2]["messages"][0]["content"]


def test_a_correction_that_looks_like_the_fact_it_corrects_replaces_it_when_the_model_names_that_fact(world):
    _, memory, _ = world
    old = memory.add_manual("has a dog named Hog", "api")
    said = "Actually his name is Hogg, not Hog"
    fid = stage(world, said, "has a dog named Hogg")
    report = auto.apply(memory, now=NOW, replaces=lambda fact: auto.Replacement("replaces", old), corrects=lambda fact: diya_intent.is_correction(said))
    assert report.replaced == 1 and memory.get(fid)["status"] == "accepted" and memory.get(old)["status"] == "retired"


@pytest.mark.parametrize("answer", [auto.Replacement("none", None), auto.Replacement("unclear", None), auto.Replacement("failed", None)])
def test_when_the_model_does_not_clearly_name_what_it_replaces_the_look_alike_still_waits_for_a_question(world, answer):
    _, memory, _ = world
    old = memory.add_manual("has a dog named Hog", "api")
    said = "Actually his name is Hogg, not Hog"
    fid = stage(world, said, "has a dog named Hogg")
    report = auto.apply(memory, now=NOW, replaces=lambda fact: answer, corrects=lambda fact: True)
    assert report.replaced == 0 and memory.get(fid)["status"] == "candidate" and memory.get(old)["status"] == "accepted"
    assert any(flag.startswith("ask:conflict:similar:") for flag in memory.get(fid)["flags"])


def test_a_look_alike_that_is_not_said_to_be_a_correction_is_still_asked_about(world):
    _, memory, _ = world
    memory.add_manual("has a dog named Hog", "api")
    fid = stage(world, "I have a dog named Hogg", "has a dog named Hogg")
    assert auto.apply(memory, now=NOW, replaces=lambda fact: auto.Replacement("replaces", 1), corrects=lambda fact: False) == auto.Report(0, 1, 0, 0)
    assert memory.get(fid)["status"] == "candidate"
