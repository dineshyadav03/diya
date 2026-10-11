"""The questions Diya raises herself (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5): diya_questions.py.

What this proves: the quiet hours are read and applied as written (the start hour is quiet, the end hour is not, across midnight too); a fact is read for a day
only when it names an event and is not a habit, and only in words diya_time will commit to; questions are made from what is waiting, what has gone stale and what
is coming, in that order, at the pace of three open and two new a day, never twice for the same fact in the same way; a question shown and left for a day waits
three days and is dropped the second time without touching its fact; one whose fact was dealt with elsewhere is closed; the words are built from the fact; each
answer does exactly what it says and a refused one changes nothing and leaves the question open.
"""
from datetime import datetime, timedelta

import pytest

import diya_memory
import diya_questions as q
from diya_db import Store
from diya_memory import Memory

SUNDAY = datetime(2026, 10, 11, 9, 0)  # a Sunday, 09:00 local
CREATED = "2026-10-11T03:30:00+00:00"  # 09:00 in India; the facts below are "said" on Sunday morning, in any zone close to it, give or take a day


@pytest.fixture
def parts(tmp_path):
    store = Store(str(tmp_path / "q.db"))
    return Memory(store), q.Questions(store)


def waiting(memory, text, flags=(), position=0):
    fact_id = memory.add_candidate(text, batch_first=1, batch_last=1, position=position, model="m", extracted_at=CREATED, raw="- " + text)
    memory.set_flags(fact_id, list(flags), "system")
    return fact_id


def remembered(memory, text):
    return memory.add_manual(text, "api")


def kinds(questions):
    return [(item["fact_id"], item["kind"]) for item in questions]


# --- the quiet hours --------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("setting, expected", [
    ("22-07", (22, 7)), (" 22 - 7 ", (22, 7)), ("9-17", (9, 17)), ("0-6", (0, 6)), ("23-00", (23, 0)), ("OFF", None), ("off", None), ("none", None), ("", None), (None, None),
])
def test_the_quiet_hours_are_read_from_a_setting(setting, expected):
    assert q.parse_quiet(setting) == expected


@pytest.mark.parametrize("setting", ["22", "22:00-07:00", "25-3", "3-25", "7-7", "a-b", "22-07-08", "-1-5"])
def test_a_setting_that_is_not_two_hours_is_refused(setting):
    with pytest.raises(ValueError):
        q.parse_quiet(setting)


@pytest.mark.parametrize("hour, quiet", [(22, True), (23, True), (0, True), (6, True), (7, False), (12, False), (21, False)])
def test_the_start_hour_is_quiet_and_the_end_hour_is_not_across_midnight(hour, quiet):
    assert q.is_quiet(datetime(2026, 10, 11, hour, 30), (22, 7)) is quiet


@pytest.mark.parametrize("hour, quiet", [(8, False), (9, True), (12, True), (16, True), (17, False)])
def test_quiet_hours_inside_one_day_work_too(hour, quiet):
    assert q.is_quiet(datetime(2026, 10, 11, hour, 0), (9, 17)) is quiet


def test_with_no_quiet_hours_it_is_never_quiet():
    assert all(q.is_quiet(datetime(2026, 10, 11, hour, 0), None) is False for hour in range(24))


# --- reading a day from a fact's words --------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, when", [
    ("has a dentist appointment on Friday at 3pm", datetime(2026, 10, 16, 15, 0)),
    ("is leaving for Goa tomorrow", datetime(2026, 10, 12, 9, 0)),
    ("has an exam on 26 Oct at 5pm", datetime(2026, 10, 26, 17, 0)),
    ("has a flight on Friday at 17:30", datetime(2026, 10, 16, 17, 30)),
    ("has a call in 2 hours", datetime(2026, 10, 11, 11, 0)),
    ("Dentist appointment Friday 3pm", datetime(2026, 10, 16, 15, 0)),
])
def test_a_fact_that_names_an_event_and_a_day_has_that_day(text, when):
    assert q.horizon(text, SUNDAY).local == when


@pytest.mark.parametrize("text", [
    "plays badminton on Sunday", "is allergic to peanuts", "has a meeting every Monday", "usually has lunch at noon", "has a flight next Friday",
    "has a trip next week", "is visiting in May", "has an exam on the 14th", "has an appointment at 5", "has an appointment", "likes tea in the morning",
    "has a weekly call on Monday", "goes to class on weekdays", "always has dinner at 8pm tonight",
])
def test_a_habit_or_a_day_diya_will_not_guess_at_or_no_event_has_no_day(text):
    assert q.horizon(text, SUNDAY) is None


# --- making the questions ---------------------------------------------------------------------------------------------------

def test_a_waiting_fact_with_a_question_flag_becomes_a_question_of_that_kind(parts):
    memory, questions = parts
    doubt = waiting(memory, "might like tea", ["ask:doubt:ungrounded"], 0)
    private = waiting(memory, "takes metformin", ["ask:sensitive:model_private"], 1)
    conflict = waiting(memory, "works as a nurse", ["ask:conflict:similar:3"], 2)
    assert questions.refill(memory, SUNDAY) == 2  # the pace allows two new in a day
    assert kinds(questions.open()) == [(doubt, "doubt"), (private, "sensitive")]
    assert conflict not in [item["fact_id"] for item in questions.open()]


def test_a_waiting_fact_that_may_replace_another_remembers_which(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    new = waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    assert (item["fact_id"], item["kind"], item["detail"]) == (new, "conflict", {"replaces": old})


def test_a_waiting_fact_with_no_question_flag_is_not_asked_about_and_neither_is_one_with_an_unknown_kind(parts):
    memory, questions = parts
    waiting(memory, "plain candidate", ["ungrounded"], 0)
    waiting(memory, "odd", ["ask:mystery:x"], 1)
    assert questions.refill(memory, SUNDAY) == 0 and questions.open() == []


def test_never_more_than_two_new_in_a_day_and_three_open_at_once(parts):
    memory, questions = parts
    for n in range(6):
        waiting(memory, f"private thing number {n}", ["ask:sensitive:model_private"], n)
    assert questions.refill(memory, SUNDAY) == 2 and questions.refill(memory, SUNDAY + timedelta(hours=3)) == 0
    assert questions.refill(memory, SUNDAY + timedelta(hours=25)) == 1  # a day on: two more are allowed, but only one fits beside the two open
    assert len(questions.open()) == 3
    assert questions.refill(memory, SUNDAY + timedelta(hours=50)) == 0  # three are open; nothing more until one is dealt with


def test_the_next_day_brings_the_next_two_once_there_is_room(parts):
    memory, questions = parts
    ids = [waiting(memory, f"private thing number {n}", ["ask:sensitive:model_private"], n) for n in range(4)]
    questions.refill(memory, SUNDAY)
    for item in questions.open():
        questions.answer(memory, item["id"], "no", SUNDAY)
    assert questions.refill(memory, SUNDAY + timedelta(hours=1)) == 0  # two were made in the last day
    assert questions.refill(memory, SUNDAY + timedelta(hours=25)) == 2
    assert [item["fact_id"] for item in questions.open()] == ids[2:]


def test_the_waiting_and_private_come_before_what_has_gone_stale_before_offers(parts):
    memory, questions = parts
    waiting_fact = waiting(memory, "private thing", ["ask:sensitive:model_private"])
    old = remembered(memory, "has a dentist appointment on Friday at 3pm")  # made now: its Friday is still ahead
    memory.decide(old, "retire", "api")
    memory.decide(old, "restore", "api")
    gone = remembered(memory, "has an exam on 20 Oct")
    later = SUNDAY + timedelta(days=30)  # by then both of the others have gone stale; the waiting one still comes first
    questions.refill(memory, later)
    assert kinds(questions.open())[0] == (waiting_fact, "sensitive") and len(questions.open()) == 2


def test_a_fact_is_never_asked_about_twice_in_the_same_way(parts):
    memory, questions = parts
    fact = waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    questions.answer(memory, item["id"], "no", SUNDAY)
    memory.decide(fact, "reopen", "api")  # the person changed their mind about rejecting it
    questions.refill(memory, SUNDAY + timedelta(days=2))
    assert len(questions._rows("")) == 1 and questions.open() == []


def test_one_fact_can_have_one_question_of_each_kind(parts):
    memory, questions = parts
    fact = remembered(memory, "has an exam on 20 Oct")
    questions.refill(memory, datetime(2026, 10, 21, 10, 0))
    assert kinds(questions.open()) == [(fact, "stale")]


def test_a_discarded_secret_has_no_question_because_it_has_no_text_and_no_flag(parts):
    memory, questions = parts
    fact = waiting(memory, "my password is hunter2", ["ask:sensitive:model_private"])
    memory.discard_secret(fact, "password", "auto")
    assert questions.refill(memory, SUNDAY) == 0


# --- stale and offers -------------------------------------------------------------------------------------------------------

def made_at_sunday(memory, text):
    """An accepted fact made on Sunday morning, as the clock of these tests has it."""
    fact_id = memory.add_manual(text, "api")
    conn = memory.store.connect()
    conn.execute("UPDATE facts SET created_at = ? WHERE id = ?", (q._iso(SUNDAY).replace("Z", "+00:00").replace("T", "T"), fact_id))
    conn.commit()
    conn.close()
    return fact_id


def test_a_remembered_event_whose_day_has_gone_is_asked_about_once_and_not_before(parts):
    memory, questions = parts
    fact = made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    assert questions.refill(memory, datetime(2026, 10, 16, 14, 0)) == 1 and kinds(questions.open()) == [(fact, "offer")]  # still ahead: an offer, not a question about the past
    for item in questions.open():
        questions.answer(memory, item["id"], "no", SUNDAY)
    assert questions.refill(memory, datetime(2026, 10, 17, 10, 0)) == 1 and kinds(questions.open()) == [(fact, "stale")]
    assert questions.open()[0]["detail"]["was"] == "Friday 16 Oct 2026, 15:00"


def test_an_offer_is_made_an_hour_before_when_a_time_was_given_and_at_nine_when_only_a_day_was(parts):
    memory, questions = parts
    timed = made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    dated = made_at_sunday(memory, "has an exam on 20 Oct")
    questions.refill(memory, SUNDAY + timedelta(hours=1))
    by_fact = {item["fact_id"]: item for item in questions.open()}
    assert by_fact[timed]["detail"]["due_text"] == "Friday 16 Oct 2026, 14:00" and by_fact[dated]["detail"]["due_text"] == "Tuesday 20 Oct 2026, 09:00"
    assert by_fact[timed]["detail"]["event"] == "Friday 16 Oct 2026, 15:00"


def test_no_offer_when_the_moment_to_remind_has_gone_by(parts):
    memory, questions = parts
    made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    assert questions.refill(memory, datetime(2026, 10, 16, 15, 30)) == 1  # the appointment is over: that is a stale question, never an offer
    assert [item["kind"] for item in questions.open()] == ["stale"]


def test_a_habit_has_neither_a_stale_question_nor_an_offer(parts):
    memory, questions = parts
    made_at_sunday(memory, "plays badminton on Sunday")
    made_at_sunday(memory, "has a meeting every Monday")
    assert questions.refill(memory, SUNDAY + timedelta(days=30)) == 0


def test_a_candidate_is_not_offered_a_reminder_until_it_is_remembered(parts):
    memory, questions = parts
    waiting(memory, "has a dentist appointment on Friday at 3pm")
    assert questions.refill(memory, SUNDAY + timedelta(hours=1)) == 0


# --- ignoring ---------------------------------------------------------------------------------------------------------------

def test_a_question_that_is_shown_and_left_for_a_day_waits_three_days(parts):
    memory, questions = parts
    fact = waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.visible(SUNDAY)
    questions.seen([item["id"]], SUNDAY)
    questions.refill(memory, SUNDAY + timedelta(hours=23))
    assert len(questions.visible(SUNDAY + timedelta(hours=23))) == 1  # not yet a day
    questions.refill(memory, SUNDAY + timedelta(hours=25))
    assert questions.visible(SUNDAY + timedelta(hours=26)) == [] and questions.get(item["id"])["ignores"] == 1
    assert len(questions.visible(SUNDAY + timedelta(hours=25) + timedelta(days=3, minutes=1))) == 1
    assert memory.get(fact)["status"] == "candidate"


def test_a_question_ignored_twice_is_dropped_and_its_fact_is_left_as_it_was(parts):
    memory, questions = parts
    fact = waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.visible(SUNDAY)
    questions.seen([item["id"]], SUNDAY)
    questions.refill(memory, SUNDAY + timedelta(hours=25))
    second = SUNDAY + timedelta(days=5)
    assert len(questions.visible(second)) == 1
    questions.seen([item["id"]], second)
    questions.refill(memory, second + timedelta(hours=25))
    dropped = questions.get(item["id"])
    assert dropped["state"] == "dropped" and dropped["answer"] == "ignored" and dropped["ignores"] == 2
    assert memory.get(fact)["status"] == "candidate"  # never accepted by silence


def test_a_question_never_shown_is_never_ignored(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    questions.refill(memory, SUNDAY + timedelta(days=30))
    assert questions.open()[0]["ignores"] == 0


def test_seeing_a_question_again_does_not_start_its_day_again(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    questions.seen([item["id"]], SUNDAY)
    questions.seen([item["id"]], SUNDAY + timedelta(hours=20))
    assert questions.get(item["id"])["shown_at"] == q._iso(SUNDAY)


def test_questions_are_not_visible_in_the_quiet_hours_but_are_still_there(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    night = datetime(2026, 10, 11, 23, 0)
    questions.refill(memory, night)
    assert questions.visible(night) == [] and len(questions.open()) == 1
    assert len(questions.visible(datetime(2026, 10, 12, 8, 0))) == 1


def test_with_no_quiet_hours_a_question_is_visible_at_night(parts):
    memory, _ = parts
    questions = q.Questions(memory.store, quiet=None)
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    night = datetime(2026, 10, 11, 23, 0)
    questions.refill(memory, night)
    assert len(questions.visible(night)) == 1


def test_a_question_whose_fact_was_dealt_with_elsewhere_is_closed(parts):
    memory, questions = parts
    fact = waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    memory.decide(fact, "accept", "api")  # on the Memory page
    questions.refill(memory, SUNDAY + timedelta(hours=1))
    (item,) = questions._rows("")
    assert item["state"] == "answered" and item["answer"] == "handled elsewhere" and questions.open() == []


def test_a_stale_question_is_closed_when_its_fact_is_forgotten_elsewhere(parts):
    memory, questions = parts
    fact = made_at_sunday(memory, "has an exam on 20 Oct")
    questions.refill(memory, datetime(2026, 10, 21, 10, 0))
    memory.decide(fact, "retire", "api")
    questions.refill(memory, datetime(2026, 10, 21, 11, 0))
    assert questions.open() == []


# --- the words --------------------------------------------------------------------------------------------------------------

def one(memory, questions, now=SUNDAY):
    questions.refill(memory, now)
    (item,) = questions.open()
    return item


def test_each_kind_of_question_is_put_in_its_own_words_with_its_own_answers(parts):
    memory, questions = parts
    waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    assert questions.describe(memory, one(memory, questions)) == {
        "id": 1, "kind": "doubt", "fact_id": 1, "text": "I am not sure about this: “might like tea”. Is it right?",
        "options": [{"answer": "yes", "label": "Yes, remember it"}, {"answer": "no", "label": "No"}, {"answer": "edit", "label": "Edit it"}]}


def test_a_private_fact_is_asked_about_with_its_own_words_and_two_answers(parts):
    memory, questions = parts
    waiting(memory, "takes metformin", ["ask:sensitive:model_private"])
    shown = questions.describe(memory, one(memory, questions))
    assert shown["text"] == "“takes metformin” looks private, so I did not keep it without asking. May I remember it?"
    assert [o["answer"] for o in shown["options"]] == ["yes", "no"]


def test_a_possible_replacement_names_the_fact_it_may_replace_and_offers_to_keep_both(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    shown = questions.describe(memory, one(memory, questions))
    assert shown["text"] == "Does “works as a nurse” replace what I knew: “works as a teacher”?"
    assert [o["answer"] for o in shown["options"]] == ["yes", "keep", "no"]


def test_a_possible_replacement_whose_old_fact_is_gone_is_asked_as_a_near_copy(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    item = one(memory, questions)
    memory.decide(old, "retire", "api")
    shown = questions.describe(memory, item)
    assert shown["text"] == "“works as a nurse” is close to something I already know. Should I remember it too?" and [o["answer"] for o in shown["options"]] == ["keep", "no"]


def test_a_stale_question_and_an_offer_say_when(parts):
    memory, questions = parts
    made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    offer = questions.describe(memory, one(memory, questions, SUNDAY + timedelta(hours=1)))
    assert offer["text"] == "“has a dentist appointment on Friday at 3pm” is on Friday 16 Oct 2026, 15:00. Want a reminder at Friday 16 Oct 2026, 14:00?"
    assert [o["answer"] for o in offer["options"]] == ["yes", "no"]


def test_a_long_fact_is_cut_in_the_words_of_a_question(parts):
    memory, questions = parts
    waiting(memory, "x" * 190, ["ask:doubt:ungrounded"])
    shown = questions.describe(memory, one(memory, questions))
    assert shown["text"] == "I am not sure about this: “" + "x" * 160 + "...”. Is it right?"  # cut at 160 characters, and says so


# --- answering --------------------------------------------------------------------------------------------------------------

def test_yes_to_a_doubt_remembers_the_fact_and_closes_the_question(parts):
    memory, questions = parts
    fact = waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    item = one(memory, questions)
    closed = questions.answer(memory, item["id"], "yes", SUNDAY)
    assert memory.get(fact)["status"] == "accepted" and (closed["state"], closed["answer"]) == ("answered", "yes")
    assert memory.events(fact)[-1][1] == "api"


def test_no_to_a_doubt_rejects_the_fact(parts):
    memory, questions = parts
    fact = waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    questions.answer(memory, one(memory, questions)["id"], "no", SUNDAY)
    assert memory.get(fact)["status"] == "rejected"


def test_edit_rewords_the_fact_and_remembers_it(parts):
    memory, questions = parts
    fact = waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    questions.answer(memory, one(memory, questions)["id"], "edit", SUNDAY, text="  - likes green tea  ")
    got = memory.get(fact)
    assert got["status"] == "accepted" and got["text"] == "likes green tea"


@pytest.mark.parametrize("text", [None, "", "   ", "-"])
def test_an_edit_with_nothing_to_say_changes_nothing_and_leaves_the_question_open(parts, text):
    memory, questions = parts
    fact = waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    item = one(memory, questions)
    with pytest.raises(diya_memory.InvalidFact):
        questions.answer(memory, item["id"], "edit", SUNDAY, text=text)
    assert memory.get(fact)["status"] == "candidate" and questions.get(item["id"])["state"] == "open"


@pytest.mark.parametrize("answer", ["maybe", "keep", "edit", "", "YES"])
def test_an_answer_the_question_does_not_offer_is_refused_and_changes_nothing(parts, answer):
    memory, questions = parts
    fact = waiting(memory, "takes metformin", ["ask:sensitive:model_private"])
    item = one(memory, questions)
    with pytest.raises(diya_memory.InvalidFact):
        questions.answer(memory, item["id"], answer, SUNDAY)
    assert memory.get(fact)["status"] == "candidate" and questions.get(item["id"])["state"] == "open"


def test_yes_to_a_possible_replacement_replaces_and_keep_both_keeps_both(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    new = waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    questions.answer(memory, one(memory, questions)["id"], "yes", SUNDAY)
    assert memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired" and memory.replaced(new) == old


def test_keeping_both_accepts_the_new_fact_beside_the_old(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    new = waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    questions.answer(memory, one(memory, questions)["id"], "keep", SUNDAY)
    assert memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "accepted"


def test_no_to_a_possible_replacement_rejects_the_new_fact_and_keeps_the_old(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    new = waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    questions.answer(memory, one(memory, questions)["id"], "no", SUNDAY)
    assert memory.get(new)["status"] == "rejected" and memory.get(old)["status"] == "accepted"


def test_an_answer_that_the_memory_refuses_leaves_the_question_open(parts):
    memory, questions = parts
    remembered(memory, "might like tea")
    fact = waiting(memory, "Might like tea", ["ask:doubt:ungrounded"])  # the same words as an accepted fact: accepting it is a repeat
    item = one(memory, questions)
    with pytest.raises(diya_memory.DuplicateFact):
        questions.answer(memory, item["id"], "yes", SUNDAY)
    assert memory.get(fact)["status"] == "candidate" and questions.get(item["id"])["state"] == "open"


def test_still_true_changes_nothing_and_no_longer_forgets_the_fact(parts):
    memory, questions = parts
    still = made_at_sunday(memory, "has an exam on 20 Oct")
    gone = made_at_sunday(memory, "has a flight on 19 Oct at 6pm")
    questions.refill(memory, datetime(2026, 10, 21, 10, 0))
    by_fact = {item["fact_id"]: item for item in questions.open()}
    questions.answer(memory, by_fact[still]["id"], "yes", SUNDAY)
    questions.answer(memory, by_fact[gone]["id"], "no", SUNDAY)
    assert memory.get(still)["status"] == "accepted" and memory.get(gone)["status"] == "retired"


def test_yes_to_an_offer_makes_the_reminder_at_the_time_that_was_said_and_no_does_not(parts):
    memory, questions = parts
    made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    item = one(memory, questions, SUNDAY + timedelta(hours=1))
    made = []
    questions.answer(memory, item["id"], "yes", SUNDAY, add_reminder=lambda content, due_text, due_ts: made.append((content, due_text, due_ts)))
    assert made == [("has a dentist appointment on Friday at 3pm", "Friday 16 Oct 2026, 14:00", item["detail"]["due"])]


def test_no_to_an_offer_makes_no_reminder(parts):
    memory, questions = parts
    made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    item = one(memory, questions, SUNDAY + timedelta(hours=1))
    made = []
    questions.answer(memory, item["id"], "no", SUNDAY, add_reminder=lambda *a: made.append(a))
    assert made == [] and questions.get(item["id"])["answer"] == "no"


def test_an_offer_accepted_with_no_way_to_make_a_reminder_is_refused_and_stays_open(parts):
    memory, questions = parts
    made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    item = one(memory, questions, SUNDAY + timedelta(hours=1))
    with pytest.raises(diya_memory.InvalidFact):
        questions.answer(memory, item["id"], "yes", SUNDAY)
    assert questions.get(item["id"])["state"] == "open"


def test_an_offer_for_a_fact_that_has_since_been_forgotten_makes_no_reminder(parts):
    memory, questions = parts
    fact = made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    item = one(memory, questions, SUNDAY + timedelta(hours=1))
    memory.decide(fact, "retire", "api")
    made = []
    with pytest.raises(diya_memory.IllegalTransition):
        questions.answer(memory, item["id"], "yes", SUNDAY, add_reminder=lambda *a: made.append(a))
    assert made == []


def test_a_question_answered_twice_is_refused_the_second_time(parts):
    memory, questions = parts
    waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    item = one(memory, questions)
    questions.answer(memory, item["id"], "no", SUNDAY)
    with pytest.raises(diya_memory.IllegalTransition, match="only an open question"):
        questions.answer(memory, item["id"], "no", SUNDAY)


def test_a_question_that_is_not_there_is_not_found(parts):
    _, questions = parts
    with pytest.raises(diya_memory.UnknownFact):
        questions.get(99)


# --- the edges: each of these is a way the code above could be wrong without any test above noticing -------------------------

def test_twenty_four_is_not_an_hour_of_the_day():
    for setting in ("22-24", "24-3", "24-24"):
        with pytest.raises(ValueError):
            q.parse_quiet(setting)


def test_a_comma_after_a_day_does_not_hide_it():
    assert q.horizon("has a dentist appointment on Friday, 3pm", SUNDAY).local == datetime(2026, 10, 16, 15, 0)
    assert q.horizon("has an exam on Friday; 5pm", SUNDAY).local == datetime(2026, 10, 16, 17, 0)


@pytest.mark.parametrize("text", ["has a flight Next Friday", "has a flight NEXT Friday", "has a flight next: Friday", "has a flight next. Friday", "has a flight after Friday at 3pm",
                                  "has a flight before Friday at 3pm", "has a flight until Friday at 3pm", "has a flight following Friday at 3pm"])
def test_a_word_that_changes_which_day_is_meant_is_noticed_whatever_its_capitals_and_punctuation(text):
    assert q.horizon(text, SUNDAY) is None


def test_a_relative_time_is_counted_from_when_the_fact_was_made_not_from_greenwich(parts):
    memory, questions = parts
    fact = made_at_sunday(memory, "has a call in 2 hours")
    assert questions.refill(memory, SUNDAY + timedelta(hours=1)) == 1 and kinds(questions.open()) == [(fact, "offer")]
    assert questions.open()[0]["detail"]["event"] == "Sunday 11 Oct 2026, 11:00"


def test_a_day_is_twenty_four_hours_for_the_pace(parts):
    memory, questions = parts
    for n in range(6):
        waiting(memory, f"private thing number {n}", ["ask:sensitive:model_private"], n)
    assert questions.refill(memory, SUNDAY) == 2
    for item in questions.open():
        questions.answer(memory, item["id"], "no", SUNDAY)
    assert questions.refill(memory, SUNDAY + timedelta(hours=21)) == 0 and questions.refill(memory, SUNDAY + timedelta(hours=23, minutes=59)) == 0
    assert questions.refill(memory, SUNDAY + timedelta(hours=24, minutes=1)) == 2


def test_a_fact_with_two_question_flags_is_asked_about_once(parts):
    memory, questions = parts
    waiting(memory, "odd thing", ["ask:doubt:ungrounded", "ask:sensitive:model_private"])
    assert questions.refill(memory, SUNDAY) == 1 and [item["kind"] for item in questions.open()] == ["doubt"]


def test_an_unknown_kind_of_flag_first_means_the_fact_is_not_asked_about_at_all(parts):
    memory, questions = parts
    waiting(memory, "odd thing", ["ask:mystery:x", "ask:doubt:ungrounded"])
    assert questions.refill(memory, SUNDAY) == 0


def test_the_day_itself_has_gone_when_its_minute_has_come(parts):
    memory, questions = parts
    made_at_sunday(memory, "has a dentist appointment on Friday at 3pm")
    assert questions.refill(memory, datetime(2026, 10, 16, 15, 0)) == 1 and [item["kind"] for item in questions.open()] == ["stale"]


def test_asking_again_after_a_stale_question_or_an_offer_was_made_does_not_make_it_again(parts):
    memory, questions = parts
    made_at_sunday(memory, "has an exam on 20 Oct")
    assert questions.refill(memory, SUNDAY + timedelta(hours=1)) == 1  # an offer
    assert questions.refill(memory, SUNDAY + timedelta(hours=2)) == 0 and len(questions._rows("")) == 1
    assert questions.refill(memory, datetime(2026, 10, 21, 10, 0)) == 1  # a day on: the stale question, and not the offer again
    assert questions.refill(memory, datetime(2026, 10, 21, 11, 0)) == 0 and sorted(item["kind"] for item in questions._rows("")) == ["offer", "stale"]


def test_a_question_that_waits_waits_three_days_not_one_or_two(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    questions.seen([item["id"]], SUNDAY)
    questions.refill(memory, SUNDAY + timedelta(hours=25))
    wake = SUNDAY + timedelta(hours=25) + timedelta(days=3)
    assert questions.visible(wake - timedelta(days=1)) == [] and questions.visible(wake - timedelta(minutes=1)) == []
    assert len(questions.visible(wake)) == 1  # at the very moment it is due it is shown


def test_a_question_that_was_answered_is_never_aged_into_anything_else(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    questions.seen([item["id"]], SUNDAY)
    questions.answer(memory, item["id"], "no", SUNDAY + timedelta(hours=1))
    for hours in (25, 100, 400):
        questions.refill(memory, SUNDAY + timedelta(hours=hours))
    closed = questions.get(item["id"])
    assert (closed["state"], closed["answer"], closed["ignores"]) == ("answered", "no", 0)


def test_an_ignored_question_is_not_ignored_again_until_it_has_been_shown_again(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    questions.seen([item["id"]], SUNDAY)
    questions.refill(memory, SUNDAY + timedelta(hours=25))
    questions.refill(memory, SUNDAY + timedelta(hours=26))
    questions.refill(memory, SUNDAY + timedelta(hours=60))
    again = questions.get(item["id"])
    assert (again["ignores"], again["state"], again["shown_at"]) == (1, "open", None)


def test_a_question_that_has_been_answered_is_not_marked_as_shown_later(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    (item,) = questions.open()
    questions.answer(memory, item["id"], "no", SUNDAY)
    questions.seen([item["id"]], SUNDAY + timedelta(hours=1))
    assert questions.get(item["id"])["shown_at"] is None


def test_a_question_open_for_a_fact_that_was_deleted_is_closed(parts):
    memory, questions = parts
    fact = waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    conn = memory.store.connect()
    conn.execute("DELETE FROM facts WHERE id = ?", (fact,))
    conn.commit()
    conn.close()
    questions.refill(memory, SUNDAY + timedelta(hours=1))
    assert questions.open() == [] and questions.get(1)["answer"] == "handled elsewhere"


def test_a_stale_question_or_an_offer_stays_open_while_its_fact_is_remembered(parts):
    memory, questions = parts
    made_at_sunday(memory, "has an exam on 20 Oct")
    questions.refill(memory, SUNDAY + timedelta(hours=1))
    questions.refill(memory, SUNDAY + timedelta(hours=2))
    assert [item["kind"] for item in questions.open()] == ["offer"]
    questions.answer(memory, questions.open()[0]["id"], "no", SUNDAY)
    questions.refill(memory, datetime(2026, 10, 21, 10, 0))
    questions.refill(memory, datetime(2026, 10, 21, 11, 0))
    assert [item["kind"] for item in questions.open()] == ["stale"]


def test_telling_the_person_is_recorded_once_and_the_first_time_is_kept(parts):
    memory, questions = parts
    waiting(memory, "private thing", ["ask:sensitive:model_private"])
    questions.refill(memory, SUNDAY)
    questions.mark_notified([1], SUNDAY)
    questions.mark_notified([1], SUNDAY + timedelta(hours=3))
    assert questions.get(1)["notified_at"] == q._iso(SUNDAY) and questions.unnotified(SUNDAY + timedelta(hours=4)) == []


def test_a_long_fact_that_may_be_replaced_is_cut_in_the_question_too(parts):
    memory, questions = parts
    old = remembered(memory, "o" * 190)
    waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    shown = questions.describe(memory, one(memory, questions))
    assert shown["text"] == "Does “works as a nurse” replace what I knew: “" + "o" * 160 + "...”?"


def test_a_possible_replacement_whose_old_fact_was_deleted_is_asked_as_a_near_copy(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    item = one(memory, questions)
    conn = memory.store.connect()
    conn.execute("DELETE FROM facts WHERE id = ?", (old,))
    conn.commit()
    conn.close()
    assert questions.describe(memory, item)["text"] == "“works as a nurse” is close to something I already know. Should I remember it too?"
    assert [o["answer"] for o in questions.describe(memory, item)["options"]] == ["keep", "no"]


def test_yes_to_a_possible_replacement_that_has_since_lost_its_old_fact_is_not_offered_and_keep_works(parts):
    memory, questions = parts
    old = remembered(memory, "works as a teacher")
    new = waiting(memory, "works as a nurse", [f"ask:conflict:replaces:{old}"])
    item = one(memory, questions)
    memory.decide(old, "retire", "api")
    with pytest.raises(diya_memory.InvalidFact):
        questions.answer(memory, item["id"], "yes", SUNDAY)
    questions.answer(memory, item["id"], "keep", SUNDAY)
    assert memory.get(new)["status"] == "accepted" and memory.get(old)["status"] == "retired"
