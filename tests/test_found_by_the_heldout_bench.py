"""Faults the held-out benchmark found on 2026-10-26, now fixed and kept as development tests (docs/HELDOUT_BENCH.md).

The benchmark's rule: a case that led to a fix is moved out of the held-out set (it has been looked at) and a new one is written there. These three were:
* "put 'email professor sharma' on my to-do list" was answered "Gmail is not connected": the mail check saw the word email and the word list. A message about a to-do list, a task or a reminder is not a look through the mailbox.
* "btw my exam got moved to the 14th of march, its at 2pm in hall B" and "ive been using a 2019 macbook air with 8gb ram" were not taken as statements of fact (and so got a paragraph back instead of one
  sentence): "btw" was not a lead-in like "fyi", and "ive" without its apostrophe was not read as "i've". Questions and requests are still never statements, however they are typed.
"""
import pytest

import diya_intent as intent


@pytest.mark.parametrize("text", [
    "put 'email professor sharma' on my to-do list", "todo: email professor sharma", "add a task to email the landlord", "add to my tasks: email the landlord about the lease",
    "remind me to email mom after the list is done", "put email the registrar on my task list",
])
def test_a_message_about_a_to_do_list_a_task_or_a_reminder_is_not_a_question_about_the_mailbox(text):
    assert not intent.asks_about_mail(text)


@pytest.mark.parametrize("text", [
    "did anyone email me about the exam", "any email from the bank?", "check my inbox", "what did the bank email say", "list my latest emails", "show me unread mail from the college",
])
def test_a_real_question_about_the_mailbox_still_is(text):
    assert intent.asks_about_mail(text)


@pytest.mark.parametrize("text", [
    "btw my exam got moved to the 14th of march, its at 2pm in hall B", "by the way my sister lives in Pune", "ive been using a 2019 macbook air with 8gb ram", "im allergic to peanuts",
    "ive got a flight on 3 march", "BTW my dentist moved to the 9th",
])
def test_phone_style_statements_of_fact_are_recognised(text):
    assert intent.is_fact_share(text)


@pytest.mark.parametrize("text", [
    "btw can you check the weather in pune", "btw remind me about the exam on 3 march", "im looking for a pizza place near 5th street", "ive no idea what my password is",
    "btw what time is my exam on 14 march?", "ive lost my ticket for the 3 march flight", "by the way i need to book a flight for 12 march", "im stuck on question 4",
    "ive got a problem with my login 123", "btw please add a task to call mom on the 5th",
])
def test_a_question_a_request_a_need_or_a_problem_is_still_never_a_statement_however_it_is_typed(text):
    assert not intent.is_fact_share(text)


def test_putting_the_apostrophe_back_touches_only_those_two_words():
    assert intent._NO_APOSTROPHE.sub(lambda m: f"{m.group(1)}'{m.group(2)}", "what time is it, im here, ive come, swim, hive, Im ok, I'm fine") == "what time is it, i'm here, i've come, swim, hive, I'm ok, I'm fine"
