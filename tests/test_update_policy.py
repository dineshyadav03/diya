"""Updates and additions in Diya's memory, after the question-and-answer measurement (docs/MEMORY_BENCH.md), added 2026-10-16.

The measurement showed four answers wrong for one reason: the memory had noticed the change ("I started a new job at a bank", "I just bought an iPhone") and then waited for a question to be answered while the
old fact went on being told, and a second dog whose name looked like the first's was held up as a copy. What this proves: ordinary ways of saying something changed now count as a change (the model must still
name the fact it replaces, so a word alone replaces nothing); things said to be IN ADDITION ("another dog") are not held up for looking like a known fact, except when they are held up for another reason (they are
private); and an update still waits for a question when the person's words do not say it is one.
"""
import pytest

import diya_autonomy as auto
import diya_intent
from test_autonomy import NOW, stage, world  # noqa: F401 -- `world` is a fixture


@pytest.mark.parametrize("text", [
    "Good news: I started a new job at a bank last week.", "I just bought an iPhone.", "I bought a new laptop", "I got a new phone", "I just moved flats", "I upgraded to a new plan",
    "Actually I switched to tea, I stopped drinking coffee.", "I started working at a bank", "I replaced my old bike", "I just joined a new gym", "I landed a new role at a startup",
])
def test_the_ordinary_ways_of_saying_something_changed_count_as_a_change(text):
    assert diya_intent.is_correction(text) is True


@pytest.mark.parametrize("text", [
    "I got a new puppy named Max", "I got another dog named Hog", "I also started learning the violin", "I have a new job", "I like my new neighbours", "I started a new book club with friends",
    "Did I just buy an iPhone?", "I love new phones",
])
def test_adding_or_asking_or_liking_something_new_is_not_a_change(text):
    assert diya_intent.is_correction(text) is False


def test_a_second_dog_that_looks_like_the_first_is_remembered_when_the_person_said_it_is_another(world):
    _, memory, _ = world
    memory.add_manual("has a dog named Rocky", "api")
    fid = stage(world, "I got another dog named Hog", "has a dog named Hog")
    report = auto.apply(memory, now=NOW, adds=lambda fact: True)
    assert report == auto.Report(1, 0, 0, 0) and memory.get(fid)["status"] == "accepted"
    assert not any(f.startswith(("similar:", "ask:conflict:similar:")) for f in memory.get(fid)["flags"]) or memory.get(fid)["status"] == "accepted"


def test_the_same_fact_with_no_word_of_addition_is_still_asked_about(world):
    _, memory, _ = world
    memory.add_manual("has a dog named Rocky", "api")
    fid = stage(world, "I have a dog named Hog", "has a dog named Hog")
    assert auto.apply(memory, now=NOW, adds=lambda fact: False) == auto.Report(0, 1, 0, 0)
    assert any(f.startswith("ask:conflict:similar:") for f in memory.get(fid)["flags"])
    fid2 = stage(world, "I have a dog named Max", "has a dog named Max", position=9)
    assert auto.apply(memory, now=NOW) == auto.Report(0, 2, 0, 0)  # and with no judge at all, as before (both are waiting)
    assert memory.get(fid2)["status"] == "candidate"


def test_a_word_of_addition_does_not_get_a_private_fact_past_the_question(world):
    _, memory, _ = world
    memory.add_manual("has a cat named Pixel", "api")
    fid = stage(world, "I also have diabetes", "has diabetes")
    report = auto.apply(memory, now=NOW, adds=lambda fact: True)
    assert report == auto.Report(0, 1, 0, 0) and memory.get(fid)["status"] == "candidate"


def test_an_update_in_the_persons_own_words_replaces_the_old_fact_at_once_and_is_theirs_to_undo(world):
    _, memory, _ = world
    old = memory.add_manual("works at a bakery", "api")
    said = "Good news: I started a new job at a bank last week."
    fid = stage(world, said, "started a new job at a bank last week")
    report = auto.apply(
        memory, now=NOW, replaces=lambda fact: auto.Replacement("replaces", old), corrects=lambda fact: diya_intent.is_correction(said),
    )
    assert report.replaced == 1 and memory.get(fid)["status"] == "accepted" and memory.get(old)["status"] == "retired"


def test_an_update_whose_words_do_not_say_it_is_one_still_waits_for_a_question(world):
    _, memory, _ = world
    old = memory.add_manual("works at a bakery", "api")
    said = "I have a job at a bank"
    fid = stage(world, said, "has a job at a bank")
    report = auto.apply(memory, now=NOW, replaces=lambda fact: auto.Replacement("replaces", old), corrects=lambda fact: diya_intent.is_correction(said))
    assert report.replaced == 0 and memory.get(fid)["status"] == "candidate" and memory.get(old)["status"] == "accepted"
