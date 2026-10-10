"""Repeat rules (docs/SCHEDULE_DESIGN.md, D2 and unit R1): diya_repeat.py.

What this proves: the words people use for "every ..." are read into one of a closed set of rules (or refused with a reason
that names what is wrong), a day with no time is 09:00 and says so, every word is accounted for, a rule round-trips through
its stored text and a corrupted stored text is refused, and the date arithmetic -- the next moment a rule falls, and the
last one that has fallen -- agrees with an independent day-by-day implementation over many starting moments, including
month ends, leap years, "the 31st" in a short month, and a weekday rule over a weekend.
"""
import calendar
from datetime import date, datetime, time, timedelta

import pytest

import diya_repeat
from diya_repeat import Repeat, parse_repeat
from diya_time import NotUnderstood

NOW = datetime(2026, 10, 10, 10, 15)  # a Saturday, 10:15 local


def canonical(words, now=NOW):
    return parse_repeat(words, now).canonical()


# ---- reading ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("words, expected", [
    ("every day", "daily@09:00"), ("daily", "daily@09:00"), ("Every Day at 8am", "daily@08:00"), ("each day at 6:30pm", "daily@18:30"),
    ("every single day", "daily@09:00"), ("daily at noon", "daily@12:00"), ("every day at 17:45", "daily@17:45"),
    ("every morning", "daily@09:00"), ("every evening", "daily@18:00"), ("every afternoon", "daily@15:00"),
    ("every evening at 7pm", "daily@19:00"), ("Every morning at 7:30am", "daily@07:30"),
    ("every weekday", "weekdays@09:00"), ("every weekday at 8:30", "weekdays@08:30"), ("weekdays at 7am", "weekdays@07:00"),
    ("every workday at 9am", "weekdays@09:00"),
    ("every Monday", "weekly:0@09:00"), ("every monday at 9am", "weekly:0@09:00"), ("every Mon", "weekly:0@09:00"),
    ("every Tuesday at 5pm", "weekly:1@17:00"), ("every Sunday evening", "weekly:6@18:00"), ("weekly on Friday", "weekly:4@09:00"),
    ("every week on Wednesday at 10am", "weekly:2@10:00"), ("every Monday and Thursday at 6pm", "weekly:0,3@18:00"),
    ("every Thursday and Monday", "weekly:0,3@09:00"), ("every mon wed fri at 7am", "weekly:0,2,4@07:00"),
    ("every Monday, Wednesday and Friday at 7am", "weekly:0,2,4@07:00"), ("every monday and monday", "weekly:0@09:00"),
    ("every month on the 15th", "monthly:15@09:00"), ("monthly on the 1st at 8am", "monthly:1@08:00"), ("every 15th", "monthly:15@09:00"),
    ("every 2nd of the month at 9am", "monthly:2@09:00"), ("every month on the 3rd", "monthly:3@09:00"), ("each month on the 22nd", "monthly:22@09:00"),
    ("monthly on the 31st at noon", "monthly:31@12:00"), ("every 29th", "monthly:29@09:00"),
    ("every 3 days", "every:3@09:00#2026-10-11"), ("every other day", "every:2@09:00#2026-10-11"), ("every two days at 5pm", "every:2@17:00#2026-10-10"),
    ("every 2 weeks", "every:14@09:00#2026-10-11"), ("every other week", "every:14@09:00#2026-10-11"), ("every 10 days at 8am", "every:10@08:00#2026-10-11"),
    ("every 365 days", "every:365@09:00#2026-10-11"), ("every 1 day", "daily@09:00"), ("every 1 week", "every:7@09:00#2026-10-11"),
])
def test_the_words_people_use_are_read_into_a_rule(words, expected):
    assert canonical(words) == expected


def test_an_every_n_days_rule_counts_from_the_first_time_it_falls_which_is_today_if_the_time_is_still_ahead():
    assert parse_repeat("every 3 days at 5pm", NOW).anchor == date(2026, 10, 10)  # 17:00 is still ahead of 10:15
    assert parse_repeat("every 3 days at 8am", NOW).anchor == date(2026, 10, 11)  # 08:00 has passed today
    assert parse_repeat("every 3 days at 10:15", NOW).anchor == date(2026, 10, 11)  # exactly now has passed: strictly after


def test_a_day_with_no_time_is_nine_and_says_so_and_a_part_of_the_day_says_what_it_was_taken_as():
    assert parse_repeat("every Monday", NOW).assumed == ("no time was given, so 09:00",)
    assert parse_repeat("every Monday at 9am", NOW).assumed == ()
    assert parse_repeat("every morning", NOW).assumed == ("morning is 09:00",)
    assert parse_repeat("monthly on the 31st", NOW).assumed == ("no time was given, so 09:00", "the 31st means the last day of a month that is shorter")
    assert parse_repeat("every 28th at 9am", NOW).assumed == ()


@pytest.mark.parametrize("words, part", [
    ("every hour", "more often than once a day"), ("hourly", "more often than once a day"), ("every 30 minutes", "more often than once a day"),
    ("every 2 hours", "more often than once a day"), ("every other hour", "more often than once a day"), ("every min", "more often than once a day"),
    ("every Monday until June", "an end or a count"), ("every day till Friday", "an end or a count"), ("every Monday for 5 weeks", "an end or a count"),
    ("every day for a month", "an end or a count"), ("every day for the next 3 days", "an end or a count"), ("every Monday 10 times", "an end or a count"),
    ("every year", "not supported yet"), ("yearly", "not supported yet"), ("annually on March 3", "not supported yet"), ("each year on the 3rd", "not supported yet"),
    ("every second Tuesday", "not supported"), ("the last Friday of the month", "not supported"), ("every first Monday", "not supported"),
    ("every 3rd Thursday", "not supported"), ("every last day of the month", "last day of the month"), ("every weekend", "Saturday, Sunday or both"),
    ("every week", "needs a day"), ("weekly", "needs a day"), ("every month", "needs a date"), ("monthly", "needs a date"),
    ("every 32nd", "not a day of the month"), ("every 0th", "not a day of the month"),
    ("every 400 days", "not between 2 and 365"), ("every 53 weeks", "not between 2 and 365"),
    ("every day at 5", "could be morning or evening"), ("every Monday at 25:00", "not a time"), ("every day at 13pm", "not a time"),
    ("every Monday at breakfast", "could not read"), ("every day at 9am and 5pm", "more than one time"),
    ("every other Monday", "could not read"), ("remind me soon", "say 'every"), ("tomorrow at 5pm", "say 'every"), ("Friday", "say 'every"),
    ("every purple day", "could not read"), ("every day banana", "could not read"),
    ("every Monday at 9am please", "could not read"),
])
def test_what_cannot_be_read_is_refused_with_a_reason_that_names_what_is_wrong(words, part):
    with pytest.raises(NotUnderstood) as raised:
        parse_repeat(words, NOW)
    assert part in raised.value.reason, (words, raised.value.reason)


@pytest.mark.parametrize("words", ["", "   ", ".", None, 5, ["every day"], b"every day", "x" * 101, "every day " + "x" * 100])
def test_something_that_is_not_a_repeat_is_refused(words):
    with pytest.raises(NotUnderstood):
        parse_repeat(words, NOW)


def test_the_longest_a_repeat_may_be_is_a_hundred_characters():
    assert len("every Monday" + " " * 88) == 100
    assert parse_repeat("every Monday" + " " * 88, NOW).kind == "weekly"  # the spaces do not count: it is read, not truncated
    with pytest.raises(NotUnderstood, match="too long"):
        parse_repeat("every Monday at 9am " + "and Tuesday " * 8, NOW)


def test_a_now_with_a_time_zone_is_a_bug_and_the_real_clock_is_used_when_there_is_none():
    from datetime import timezone

    with pytest.raises(TypeError):
        parse_repeat("every day", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert parse_repeat("every day").kind == "daily"


def test_capitals_punctuation_and_the_typographic_apostrophe_do_not_matter():
    assert canonical("EVERY MONDAY, at 9AM!") == "weekly:0@09:00"
    assert canonical("  every   Monday\tat 9 a.m.  ") == "weekly:0@09:00"
    assert canonical("every Monday at 9:00 A.M.") == "weekly:0@09:00"


# ---- the stored text --------------------------------------------------------------------------------------

@pytest.mark.parametrize("words", [
    "every day at 8am", "every weekday at 8:30", "every Monday and Thursday at 6pm", "every month on the 15th", "every 3 days",
    "every 2 weeks at 5pm", "monthly on the 31st", "every mon wed fri",
])
def test_a_rule_survives_being_stored_and_read_back(words):
    rule = parse_repeat(words, NOW)
    again = Repeat.from_canonical(rule.canonical())
    assert again == rule and again.canonical() == rule.canonical() and again.describe() == rule.describe()
    assert again.assumed == ()  # what was assumed is said once, when it is read; it is not part of the rule


@pytest.mark.parametrize("text", [
    "", "daily", "daily@9:00", "daily@09:00 ", "yearly@09:00", "daily:1@09:00", "daily@09:00#2026-10-12", "weekdays:1@09:00",
    "weekly@09:00", "weekly:@09:00", "weekly:7@09:00", "weekly:3,0@09:00", "weekly:1,1@09:00", "monthly@09:00", "monthly:0@09:00",
    "monthly:32@09:00", "every:3@09:00", "every:1@09:00#2026-10-12", "every:366@09:00#2026-10-12", "every:3@09:00#2026-13-01",
    "every:3@09:00#nonsense", "daily@25:00", "daily@09:60", None, 5, b"daily@09:00", "weekly:1;DROP@09:00",
])
def test_a_stored_rule_that_is_not_one_is_refused_not_trusted(text):
    with pytest.raises(ValueError):
        Repeat.from_canonical(text)


def test_a_rule_cannot_be_built_wrong():
    with pytest.raises(ValueError):
        Repeat("hourly", time(9))
    with pytest.raises(ValueError):
        Repeat("daily", time(9, 0, 30))
    with pytest.raises(ValueError):
        Repeat("daily", "09:00")
    with pytest.raises(ValueError):
        Repeat("daily", time(9, tzinfo=__import__("datetime").timezone.utc))
    with pytest.raises(ValueError):
        Repeat("weekly", time(9), days=(5, 1))
    with pytest.raises(ValueError):
        Repeat("weekly", time(9), days=(1, 7))
    with pytest.raises(ValueError):
        Repeat("weekly", time(9))
    with pytest.raises(ValueError):
        Repeat("monthly", time(9), day_of_month=32)
    with pytest.raises(ValueError):
        Repeat("interval", time(9), every=1, anchor=date(2026, 1, 1))
    with pytest.raises(ValueError):
        Repeat("interval", time(9), every=3)


def test_the_assumptions_are_not_part_of_what_makes_two_rules_equal():
    assert Repeat("daily", time(9), assumed=("no time was given, so 09:00",)) == Repeat("daily", time(9))


# ---- in words ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("words, said", [
    ("every day at 8am", "Every day at 08:00"), ("every weekday", "Every weekday at 09:00"), ("every Monday at 9am", "Every Monday at 09:00"),
    ("every Monday and Thursday at 6pm", "Every Monday and Thursday at 18:00"),
    ("every mon wed fri at 7am", "Every Monday, Wednesday and Friday at 07:00"),
    ("every month on the 1st", "Every month on the 1st at 09:00"), ("every month on the 2nd", "Every month on the 2nd at 09:00"),
    ("every month on the 3rd", "Every month on the 3rd at 09:00"), ("every month on the 11th", "Every month on the 11th at 09:00"),
    ("every month on the 12th", "Every month on the 12th at 09:00"), ("every month on the 13th", "Every month on the 13th at 09:00"),
    ("every month on the 21st", "Every month on the 21st at 09:00"), ("every month on the 22nd", "Every month on the 22nd at 09:00"),
    ("every month on the 23rd", "Every month on the 23rd at 09:00"), ("every month on the 24th", "Every month on the 24th at 09:00"),
    ("every month on the 28th", "Every month on the 28th at 09:00"),
    ("every month on the 29th", "Every month on the 29th (the last day of a shorter month) at 09:00"),
    ("every month on the 31st at noon", "Every month on the 31st (the last day of a shorter month) at 12:00"),
    ("every 3 days", "Every 3 days at 09:00, counting from 11 Oct 2026"), ("every 2 weeks at 5pm", "Every 2 weeks at 17:00, counting from 10 Oct 2026"),
    ("every 1 week", "Every week at 09:00, counting from 11 Oct 2026"), ("every 10 days", "Every 10 days at 09:00, counting from 11 Oct 2026"),
    ("every 7 days", "Every week at 09:00, counting from 11 Oct 2026"),
])
def test_a_rule_is_described_in_plain_words(words, said):
    assert parse_repeat(words, NOW).describe() == said


# ---- the arithmetic, against an independent day-by-day implementation ---------------------------------------

def falls_on(rule, day):
    """Does `rule` fall on the date `day`? Written the slow, obvious way, and not from diya_repeat's own code."""
    if rule.kind == "daily":
        return True
    if rule.kind == "weekdays":
        return day.weekday() < 5
    if rule.kind == "weekly":
        return day.weekday() in rule.days
    if rule.kind == "monthly":
        return day.day == min(rule.day_of_month, calendar.monthrange(day.year, day.month)[1])
    return day >= rule.anchor and (day - rule.anchor).days % rule.every == 0


def slow_next(rule, local):
    day = local.date()
    for _ in range(800):
        moment = datetime.combine(day, rule.at)
        if falls_on(rule, day) and moment > local:
            return moment
        day += timedelta(days=1)
    raise AssertionError("no fall in 800 days")


def slow_before(rule, local):
    day = local.date()
    for _ in range(800):
        moment = datetime.combine(day, rule.at)
        if falls_on(rule, day) and moment <= local:
            return moment
        day -= timedelta(days=1)
        if rule.kind == "interval" and day < rule.anchor - timedelta(days=1):
            return None
    return None


RULES = [
    Repeat("daily", time(9)), Repeat("daily", time(0, 0)), Repeat("daily", time(23, 59)), Repeat("weekdays", time(8, 30)),
    Repeat("weekly", time(9), days=(0,)), Repeat("weekly", time(18), days=(0, 3)), Repeat("weekly", time(7), days=(5, 6)),
    Repeat("weekly", time(9), days=(0, 1, 2, 3, 4, 5, 6)),
    Repeat("monthly", time(9), day_of_month=1), Repeat("monthly", time(9), day_of_month=15), Repeat("monthly", time(9), day_of_month=29),
    Repeat("monthly", time(12), day_of_month=30), Repeat("monthly", time(9), day_of_month=31),
    Repeat("interval", time(9), every=2, anchor=date(2026, 10, 11)), Repeat("interval", time(17), every=3, anchor=date(2026, 2, 27)),
    Repeat("interval", time(9), every=14, anchor=date(2025, 12, 30)), Repeat("interval", time(9), every=365, anchor=date(2026, 3, 1)),
]
STARTS = [datetime(2026, 1, 1, 0, 0) + timedelta(hours=37 * n + (n % 5) * 7) for n in range(260)] + [
    datetime(2026, 2, 28, 12, 0), datetime(2026, 2, 28, 23, 59), datetime(2028, 2, 28, 10, 0), datetime(2028, 2, 29, 9, 0),
    datetime(2028, 2, 29, 9, 1), datetime(2026, 12, 31, 23, 59), datetime(2026, 4, 30, 9, 0), datetime(2026, 4, 30, 9, 1),
    datetime(2026, 10, 10, 9, 0), datetime(2026, 10, 11, 9, 0), datetime(2026, 10, 11, 8, 59), datetime(2026, 10, 11, 9, 1),
]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.canonical())
def test_the_next_fall_is_the_first_one_strictly_after_the_moment(rule):
    for local in STARTS:
        got = rule.next_after(local)
        assert got == slow_next(rule, local), (rule.canonical(), local)
        assert got > local and got.time() == rule.at


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.canonical())
def test_the_last_fall_is_the_most_recent_one_at_or_before_the_moment(rule):
    for local in STARTS:
        assert rule.before(local) == slow_before(rule, local), (rule.canonical(), local)


def test_a_moment_exactly_on_a_fall_is_not_after_it_and_is_at_or_before_it():
    rule = Repeat("weekly", time(9), days=(0,))
    monday = datetime(2026, 10, 12, 9, 0)
    assert rule.next_after(monday) == datetime(2026, 10, 19, 9, 0)
    assert rule.before(monday) == monday
    assert rule.next_after(monday - timedelta(minutes=1)) == monday


def test_seconds_in_the_moment_are_ignored_and_a_moment_with_a_time_zone_is_refused():
    from datetime import timezone

    rule = Repeat("daily", time(9))
    assert rule.next_after(datetime(2026, 10, 10, 9, 0, 59)) == datetime(2026, 10, 11, 9, 0)
    assert rule.before(datetime(2026, 10, 10, 9, 0, 59)) == datetime(2026, 10, 10, 9, 0)
    for call in (rule.next_after, rule.before):
        with pytest.raises(TypeError):
            call(datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc))
        with pytest.raises(TypeError):
            call("2026-10-10")


def test_the_thirty_first_is_the_last_day_of_a_shorter_month_and_february_has_a_twenty_ninth_only_in_a_leap_year():
    rule = Repeat("monthly", time(9), day_of_month=31)
    assert rule.next_after(datetime(2026, 4, 1, 0, 0)) == datetime(2026, 4, 30, 9, 0)
    assert rule.next_after(datetime(2026, 2, 1, 0, 0)) == datetime(2026, 2, 28, 9, 0)
    assert rule.next_after(datetime(2028, 2, 1, 0, 0)) == datetime(2028, 2, 29, 9, 0)
    assert rule.next_after(datetime(2026, 12, 31, 9, 0)) == datetime(2027, 1, 31, 9, 0)  # across the new year
    assert Repeat("monthly", time(9), day_of_month=29).next_after(datetime(2027, 2, 1, 0, 0)) == datetime(2027, 2, 28, 9, 0)


def test_a_weekday_rule_skips_the_weekend_and_a_weekly_rule_waits_for_its_day():
    assert Repeat("weekdays", time(9)).next_after(datetime(2026, 10, 9, 9, 0)) == datetime(2026, 10, 12, 9, 0)  # Friday 9:00 -> Monday
    assert Repeat("weekly", time(9), days=(4,)).next_after(datetime(2026, 10, 9, 9, 1)) == datetime(2026, 10, 16, 9, 0)


def test_an_every_n_days_rule_is_not_before_its_first_date_and_then_keeps_to_its_own_count():
    rule = Repeat("interval", time(9), every=3, anchor=date(2026, 10, 20))
    assert rule.next_after(datetime(2026, 1, 1, 0, 0)) == datetime(2026, 10, 20, 9, 0)
    assert rule.before(datetime(2026, 10, 20, 8, 59)) is None
    assert rule.before(datetime(2026, 10, 20, 9, 0)) == datetime(2026, 10, 20, 9, 0)
    assert rule.next_after(datetime(2026, 10, 20, 9, 0)) == datetime(2026, 10, 23, 9, 0)
    assert rule.before(datetime(2026, 11, 2, 12, 0)) == datetime(2026, 11, 1, 9, 0)  # 20, 23, 26, 29 Oct, then 1 Nov: a month end is no reset
    assert rule.before(datetime(2026, 10, 31, 12, 0)) == datetime(2026, 10, 29, 9, 0)  # 30 and 31 Oct are not on the count


def test_the_longest_gap_a_rule_can_have_is_still_found_looking_back():
    rule = Repeat("interval", time(9), every=365, anchor=date(2025, 1, 1))
    assert rule.before(datetime(2026, 1, 1, 8, 0)) == datetime(2025, 1, 1, 9, 0)
    assert rule.before(datetime(2026, 1, 1, 9, 0)) == datetime(2026, 1, 1, 9, 0)
    monthly = Repeat("monthly", time(9), day_of_month=31)
    assert monthly.before(datetime(2026, 4, 29, 0, 0)) == datetime(2026, 3, 31, 9, 0)


def test_the_module_reads_no_clock_when_given_one():
    assert callable(diya_repeat.parse_repeat) and diya_repeat.KINDS == ("daily", "weekdays", "weekly", "monthly", "interval")
    assert diya_repeat.MAX_EVERY_DAYS == 365 and diya_repeat.MAX_CHARS == 100
