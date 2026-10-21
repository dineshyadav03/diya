"""Time words read against the day they were said (diya_when.py; docs/TIME_DESIGN.md), added 2026-10-21 from Mem0's article on time in memory.

What this proves, with labelled phrases across the days of a week, month and year boundaries: "yesterday", "last weekend", "3 weeks ago", "last Friday", "next month" and the rest mean the days they should on the day
they were said, whatever day it is read later; a phrase that cannot be told (next Friday, next weekend, a bare Friday, this Monday said on a Wednesday) is left alone rather than guessed; the description keeps the
precision the person gave (a month stays a month, a week a week, "2 weeks ago" is "about"); annotation changes nothing but the phrases and does nothing for a text written today; the question helpers tell a
question about a time from one about a thing; the end of "until 31 Jan" and its kin is read, with the year worked out and a date already past ignored; and a stored moment becomes the person's own calendar
day (a message sent at 02:00 in Mumbai is that day, not the UTC day before). It does not read every way people write time, and it does not know the person's zone beyond this computer's.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

import diya_when as w

WED = date(2026, 10, 21)  # a Wednesday


def one(text, anchor=WED):
    spans = w.find(text, anchor)
    assert len(spans) == 1, (text, spans)
    return spans[0]


@pytest.mark.parametrize("text, start, end, kind", [
    ("yesterday", date(2026, 10, 20), date(2026, 10, 20), "day"),
    ("Yesterday evening", date(2026, 10, 20), date(2026, 10, 20), "day"),
    ("the day before yesterday", date(2026, 10, 19), date(2026, 10, 19), "day"),
    ("tomorrow", date(2026, 10, 22), date(2026, 10, 22), "day"),
    ("the day after tomorrow", date(2026, 10, 23), date(2026, 10, 23), "day"),
    ("last night", date(2026, 10, 20), date(2026, 10, 20), "night"),
    ("tonight", WED, WED, "night"),
    ("today", WED, WED, "day"),
    ("this morning", WED, WED, "day"),
    ("last weekend", date(2026, 10, 17), date(2026, 10, 18), "weekend"),
    ("this weekend", date(2026, 10, 24), date(2026, 10, 25), "weekend"),
    ("last week", date(2026, 10, 12), date(2026, 10, 18), "week"),
    ("this week", date(2026, 10, 19), date(2026, 10, 25), "week"),
    ("next week", date(2026, 10, 26), date(2026, 11, 1), "week"),
    ("last month", date(2026, 9, 1), date(2026, 9, 30), "month"),
    ("this month", date(2026, 10, 1), date(2026, 10, 31), "month"),
    ("next month", date(2026, 11, 1), date(2026, 11, 30), "month"),
    ("last year", date(2025, 1, 1), date(2025, 12, 31), "year"),
    ("next year", date(2027, 1, 1), date(2027, 12, 31), "year"),
    ("3 days ago", date(2026, 10, 18), date(2026, 10, 18), "day"),
    ("two weeks ago", date(2026, 10, 7), date(2026, 10, 7), "about"),
    ("3 months ago", date(2026, 7, 1), date(2026, 7, 31), "month"),
    ("a year ago", date(2025, 1, 1), date(2025, 12, 31), "year"),
    ("in 5 days", date(2026, 10, 26), date(2026, 10, 26), "day"),
    ("in 2 weeks", date(2026, 11, 4), date(2026, 11, 4), "about"),
    ("in 2 months", date(2026, 12, 1), date(2026, 12, 31), "month"),
    ("last Friday", date(2026, 10, 16), date(2026, 10, 16), "day"),
    ("last Thursday", date(2026, 10, 15), date(2026, 10, 15), "day"),
    ("last Wednesday", date(2026, 10, 14), date(2026, 10, 14), "day"),  # today is a Wednesday: last Wednesday is a week ago
    ("this Friday", date(2026, 10, 23), date(2026, 10, 23), "day"),
    ("this Wednesday", WED, WED, "day"),
])
def test_a_phrase_means_the_days_it_should_on_the_day_it_was_said(text, start, end, kind):
    span = one(text)
    assert (span.start, span.end, span.kind) == (start, end, kind)


def test_the_example_from_the_article_said_on_a_monday_in_june_means_the_weekend_before():
    span = one("I ran my first 10K last weekend and finished in 58 minutes.", date(2025, 6, 16))
    assert (span.start, span.end) == (date(2025, 6, 14), date(2025, 6, 15)) and w.describe(span) == "the weekend of 14-15 Jun 2025"


@pytest.mark.parametrize("anchor, text, start, end", [
    (date(2026, 10, 24), "last weekend", date(2026, 10, 17), date(2026, 10, 18)),  # a Saturday
    (date(2026, 10, 24), "this weekend", date(2026, 10, 24), date(2026, 10, 25)),
    (date(2026, 10, 25), "last weekend", date(2026, 10, 17), date(2026, 10, 18)),  # a Sunday
    (date(2026, 10, 25), "this weekend", date(2026, 10, 24), date(2026, 10, 25)),
    (date(2026, 10, 25), "last week", date(2026, 10, 12), date(2026, 10, 18)),
    (date(2026, 10, 19), "last week", date(2026, 10, 12), date(2026, 10, 18)),  # a Monday
    (date(2026, 1, 5), "last week", date(2025, 12, 29), date(2026, 1, 4)),  # over New Year
    (date(2026, 1, 15), "last month", date(2025, 12, 1), date(2025, 12, 31)),
    (date(2026, 12, 20), "next month", date(2027, 1, 1), date(2027, 1, 31)),
    (date(2026, 3, 31), "last month", date(2026, 2, 1), date(2026, 2, 28)),
    (date(2028, 3, 31), "last month", date(2028, 2, 1), date(2028, 2, 29)),  # a leap year
    (date(2026, 1, 31), "in 1 month", date(2026, 2, 1), date(2026, 2, 28)),
    (date(2026, 10, 18), "last Friday", date(2026, 10, 16), date(2026, 10, 16)),  # a Sunday: two days ago
    (date(2026, 10, 19), "last Friday", date(2026, 10, 16), date(2026, 10, 16)),  # a Monday: three days ago
    (date(2026, 10, 23), "last Friday", date(2026, 10, 16), date(2026, 10, 16)),  # a Friday: a week ago
])
def test_across_the_days_of_the_week_and_the_edges_of_months_and_years(anchor, text, start, end):
    span = one(text, anchor)
    assert (span.start, span.end) == (start, end)


@pytest.mark.parametrize("text", ["next Friday", "next weekend", "on Friday", "this Monday", "in March", "last Monday morning is fine, but next Monday is not", "I will see you soon", "", None, 5])
def test_what_cannot_be_told_is_left_alone(text):
    spans = w.find(text, WED)
    assert all(s.phrase.lower() not in ("next friday", "next weekend", "this monday") for s in spans)
    assert not any(s.phrase.lower() == "friday" for s in spans)


def test_a_bad_anchor_finds_nothing_and_raises_nothing():
    assert w.find("yesterday", None) == [] and w.find("yesterday", "2026-10-21") == []


@pytest.mark.parametrize("text, expected", [
    ("yesterday", "Tue 20 Oct 2026"), ("last night", "the night of Tue 20 Oct 2026"), ("last weekend", "the weekend of 17-18 Oct 2026"), ("last week", "the week of 12-18 Oct 2026"),
    ("last month", "September 2026"), ("last year", "2025"), ("two weeks ago", "about Wed 7 Oct 2026"), ("3 days ago", "Sun 18 Oct 2026"),
])
def test_the_description_keeps_the_precision_the_person_gave(text, expected):
    assert w.describe(one(text)) == expected


def test_a_week_over_new_year_names_both_years():
    assert w.describe(one("last week", date(2026, 1, 5))) == "the week of 29 Dec 2025-4 Jan 2026"
    assert w.describe(one("last weekend", date(2026, 5, 4))) == "the weekend of 2-3 May 2026"
    assert w.describe(one("last weekend", date(2026, 6, 3))) == "the weekend of 30 May-31 May 2026".replace("30 May-31 May", "30-31 May")


def test_annotation_adds_what_a_phrase_meant_and_nothing_else():
    text = "ran a 10K last weekend and started the new meds yesterday"
    out = w.annotate(text, date(2025, 6, 16), date(2026, 10, 21))
    assert out == "ran a 10K last weekend (that was the weekend of 14-15 Jun 2025) and started the new meds yesterday (that was Sun 15 Jun 2025)"
    assert w.annotate(text, WED, WED) == text  # said today: still about now
    assert w.annotate("likes tea", date(2025, 6, 16), WED) == "likes tea" and w.annotate("next Friday", date(2025, 6, 16), WED) == "next Friday"
    many = "yesterday, last week, last month and last year"
    assert w.annotate(many, date(2025, 1, 10), WED).count("(that was") == w.MAX_ANNOTATIONS


def test_a_datetime_is_taken_as_its_day():
    assert w.find("yesterday", datetime(2026, 10, 21, 23, 59))[0].start == date(2026, 10, 20)


@pytest.mark.parametrize("question, expected", [
    ("what did I say last week?", (date(2026, 10, 12), date(2026, 10, 18))),
    ("anything from yesterday?", (date(2026, 10, 20), date(2026, 10, 20))),
    ("what did I eat last night?", (date(2026, 10, 20), date(2026, 10, 20))),
    ("between last week and today", (date(2026, 10, 12), date(2026, 10, 21))),
    ("when is my exam?", None),
])
def test_the_window_a_question_asks_about(question, expected):
    assert w.window(question, WED) == expected


@pytest.mark.parametrize("question, only", [
    ("what did I say last week?", True), ("anything from yesterday?", True), ("tell me what we talked about last month", True),
    ("what did I struggle with last week?", False), ("what did I eat last night?", False), ("when is my exam?", False), ("last week", True),
])
def test_a_question_about_when_is_told_from_one_about_a_thing(question, only):
    assert w.time_only(question, WED) is only


@pytest.mark.parametrize("text, expected", [
    ("has a gym membership until 31 Jan", date(2027, 1, 31)),
    ("is doing Dry January, through January 31st", date(2027, 1, 31)),
    ("the trial ends on 15 Nov", date(2026, 11, 15)),
    ("the trial ends Nov 15", date(2026, 11, 15)),
    ("is on antibiotics until the end of October", date(2026, 10, 31)),
    ("is living at the hostel until March", date(2027, 3, 31)),
    ("has a library card that expires 2027-03-03", date(2027, 3, 3)),
    ("has a pass valid until 5 Dec 2026", date(2026, 12, 5)),
    ("has a pass valid until 21 Oct", WED),  # today is still inside it
])
def test_the_last_day_a_fact_says_it_lasts_to(text, expected):
    assert w.ends_on(text, WED) == expected


@pytest.mark.parametrize("text", ["lived in Pune until 2019", "studied there until March 2019", "likes tea", "worked there until 10 Oct", "", None, 5, "until 32 Jan", "until 30 Feb"])
def test_a_date_already_past_or_not_a_date_ends_nothing(text):
    assert w.ends_on(text, WED) is None


def test_a_stored_moment_becomes_the_persons_own_day_not_the_utc_day():
    mumbai = timezone(timedelta(hours=5, minutes=30))
    assert w.local_date("2026-08-09T20:30:00+00:00", mumbai) == date(2026, 8, 10)  # 02:00 on the 10th in Mumbai, "this morning" for the person
    assert w.local_date("2026-08-09T20:30:00Z", timezone.utc) == date(2026, 8, 9)
    assert w.local_date("2026-08-09T20:30:00", mumbai) == date(2026, 8, 10)  # a stored moment with no zone is UTC, as Diya stores them
    assert w.local_date(datetime(2026, 8, 9, 20, 30, tzinfo=timezone.utc), mumbai) == date(2026, 8, 10)
    assert isinstance(w.local_date("2026-08-09T20:30:00+00:00"), date)  # (this computer's zone)


def test_the_hint_is_cheap_and_right_about_what_could_hold_a_relative_word():
    assert w.has_relative("ran last weekend") and w.has_relative("3 weeks ago") and not w.has_relative("likes tea") and not w.has_relative(None)
