"""diya_intent.is_task_request: did the person ask for a task to be added? (docs/ACTIONS_DESIGN.md, D6 and unit A4.)

The guard decides whether a task may even be PROPOSED on a turn: only if the latest message asks for one. It exists
because a small model proposes tasks nobody asked for. The labelled messages were written by the author of the guard
(tests/labelled_task_requests.py), so they show what it does, NOT how it does on the way a real person phrases things;
the two LIMITS lists keep the known failures on purpose, so a change that fixes one has to say so. A false refusal is the
safe direction (the person can say "add a task to ..."); a false allowance is the behaviour before the guard existed.
"""
import pytest

import diya_intent
from diya_intent import is_task_request
from labelled_task_requests import AMBIGUOUS, ASKED, NOT_ASKED, all_not_asked

# Asked for, in phrasings the guard does not know: it refuses them (safe direction).
LIMITS_MISSED = [
    "Jot 'call mum' in Todoist",
    "Stick 'renew passport' on my to-do list",
    "Throw 'email Sam' onto my Todoist",
    "Can you track 'renew passport' in my Todoist?",
    "Queue up a task to call the bank",
    "Open a task for the boiler repair",
]
# Not asked for, but the guard cannot tell: it allows them (the status quo before the guard).
LIMITS_ALLOWED = [
    "I should add a task for that at some point",
    "She asked me to add a task to the board",
    "The add task button is broken",
    "Add task button",
]


@pytest.mark.parametrize("text", ASKED)
def test_a_message_that_asks_for_a_task_is_allowed(text):
    assert is_task_request(text), text


@pytest.mark.parametrize("category, text", [(c, t) for c, texts in NOT_ASKED.items() for t in texts])
def test_a_message_that_does_not_ask_for_one_is_refused(category, text):
    assert not is_task_request(text), (category, text)


@pytest.mark.parametrize("text", LIMITS_MISSED)
def test_known_limit_an_unusual_way_of_asking_is_refused(text):
    assert not is_task_request(text)


@pytest.mark.parametrize("text", LIMITS_ALLOWED)
def test_known_limit_a_message_that_only_mentions_adding_a_task_is_allowed(text):
    assert is_task_request(text)


@pytest.mark.parametrize("text, allowed", [
    ("Add milk to my shopping list", False), ("Put milk on the list", False), ("Remember to buy milk", False),
    ("todo: call the bank", True), ("I need to remember to call mum, can you help?", False),
    ("Please note that I need to call Sam", False),
])
def test_the_ambiguous_messages_are_decided_the_way_this_pins(text, allowed):
    assert is_task_request(text) is allowed
    assert text in AMBIGUOUS


@pytest.mark.parametrize("text", [
    "Don't add a task for that", "Please don't add anything to my to-do list", "do not add a task to my Todoist",
    "Never add tasks to my list without asking", "Stop adding tasks to my to-do list", "Add a task without a due date, not to forget it",
    "Add a task, no need to tell me when it is done",
])
def test_telling_diya_not_to_add_a_task_is_not_a_request_for_one(text):
    assert not is_task_request(text)


@pytest.mark.parametrize("text", ["Don" + chr(0x2019) + "t add a task for that", "DON'T ADD A TASK"])
def test_a_curly_apostrophe_or_capitals_do_not_hide_a_negation(text):
    assert not is_task_request(text)


@pytest.mark.parametrize("text", [
    "How do I add a task in Todoist?", "What happens if I add a task twice?", "Why did you add a task?", "Did you add a task?",
    "Is it possible to add a task?", "Does Todoist add a task for me?", "Do I add a task here?", "Where do I add a task?",
    "When can I add a task?", "Who can add a task?", "Which project do I add a task to?", "Are tasks easy to add to my Todoist?",
    "Can I add a task to someone else's project?", "could i add a task offline",
])
def test_a_question_about_adding_a_task_is_not_a_request_for_one(text):
    assert not is_task_request(text)


@pytest.mark.parametrize("text", [
    "Can you add a task: send the invoice by Friday?", "Could you put finish the report on my task list?",
    "Would you add a task to buy milk", "Please add a task", "Hey Diya, add a todo to order printer ink",
])
def test_a_polite_request_in_question_form_is_still_a_request(text):
    assert is_task_request(text)


@pytest.mark.parametrize("text", [
    "ADD A TASK TO BUY MILK", "add a task", "Add a Task", "Create task: x", "create a todoist task for the boiler",
    "New task: pay the bill", "new task - pay the bill", "Task: pay the bill", "todo - call Sam", "To-do: call Sam",
    "Add 'buy milk' to Todoist please", "Todoist, add a task called laundry", "Add a Todoist task", "add a to-do",
    "Add a todo", "add one more task", "Log a task to fix the bike", "Enter a task for Friday", "record a task: x",
    "Save a task to call mum", "Make a new task: renew licence", "Jot down a task to call mum",
    "Add the boiler repair to my Todoist", "Add this to my to-do list: call Sam", "put x on my task list",
    "Add that to my tasks", "save it in my todo", "add it onto my to-dos", "Add to my to-do list: take the bins out",
])
def test_the_ways_of_asking_the_guard_knows(text):
    assert is_task_request(text), text


@pytest.mark.parametrize("text", [
    "", "   ", "Add", "task", "to-do", "Add a", "add to", "list my tasks", "show my to-do list", "tasks",
    "What tasks do I have", "I added a task yesterday", "Task added!", "Adding a task takes me ages",
    "Todoist is where I add tasks", "I like my to-do list",
])
def test_things_that_are_not_requests_are_refused(text):
    assert not is_task_request(text)


@pytest.mark.parametrize("value", [None, 5, 1.5, ["add a task"], {"text": "add a task"}, b"add a task", True])
def test_anything_that_is_not_text_is_refused(value):
    assert is_task_request(value) is False


def test_the_search_for_the_destination_does_not_run_away_on_a_long_message():
    import time

    started = time.perf_counter()
    for text in ("add " + "word " * 5000 + "to my todoist", "add " + "x" * 5000, "add a " + "task " * 3000, "put " + "a " * 4000):
        is_task_request(text)
    assert time.perf_counter() - started < 2.0  # the gap between the verb and the place is bounded, so no runaway backtracking
    assert diya_intent._TASK_REQUEST.search("add " + "x" * 5000) is None
    assert is_task_request("add " + "word " * 5000 + "to my todoist") is False  # too far apart to be the same request


def test_the_labelled_sets_are_what_the_benchmark_scores():
    assert len(ASKED) == 25 and len(all_not_asked()) == 51 and len(AMBIGUOUS) == 6
    assert not set(ASKED) & set(all_not_asked())


@pytest.mark.parametrize("text", [
    "Put a task for Friday: send the report", "add another task", "Add this task: renew the licence", "Add that task",
    "add the task: renew", "Add me a task to call mum", "Create us a task for the trip", "make us a to-do",
    "Add 'finish the quarterly report for the finance team' to my Todoist",
    "Put it into my Todoist", "Add it to the todoist", "put it on your task list", "add it to my tasklist", "add it to my todo list",
    "add it to my to-dos", "Save a todo", "Enter a to-do", "Record a task", "jot  down a task", "add a TODOIST task",
    "Log it in my Todoist", "Enter it into my Todoist", "Record it on my task list", "Save it to my Todoist", "Put it in my Todoist",
    "TODO: call the bank", "todo - call Sam", "to-do: call Sam", "Todoist - add stamps",
])
def test_more_of_the_ways_of_asking_the_guard_knows(text):
    assert is_task_request(text), text


@pytest.mark.parametrize("text", [
    "Add a task, not to forget milk", "put it on my list not to forget", "Add a task and don't tell me", "Add a task, do not remind me",
    "Add a task, no need to tell me", "Add a task, never mind the date", "Add a task, stop me if it is wrong", "Add a task without any date",
])
def test_each_word_that_means_not_is_enough_on_its_own_to_refuse(text):
    assert not is_task_request(text), text


def test_a_destination_too_far_from_the_verb_is_not_the_same_request():
    near = "add " + "x" * 100 + " to my todoist"
    far = "add " + "x" * 200 + " to my todoist"
    assert is_task_request(near) and not is_task_request(far)
