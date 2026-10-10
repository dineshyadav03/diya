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
    ("on the 1st of every month", "monthly:1@09:00"), ("the 15th of each month at 8am", "monthly:15@08:00"),
    ("1st every month at noon", "monthly:1@12:00"), ("on the 31st of every month", "monthly:31@09:00"),
    ("every night at 10pm", "daily@22:00"), ("each night at 9:30pm", "daily@21:30"), ("every night at 23:15", "daily@23:15"),
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
    ("on the 32nd of every month", "not a day of the month"), ("the 0th of each month", "not a day of the month"),
    ("every night", "needs a time"), ("each night", "needs a time"), ("every night at 5", "could be morning or evening"),
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


# ---- finding a repeat in a person's message ---------------------------------------------------------------------

def found(text, now=NOW):
    return diya_repeat.find_repeat(text, now)


def rule_without_anchor(rule):
    return rule.canonical().split("#")[0]


def test_every_labelled_request_has_its_repeat_found_in_the_words_of_the_message():
    from labelled_repeats import REPEAT_ASKED

    for text, expected in REPEAT_ASKED:
        result = found(text)
        assert result is not None, text
        assert rule_without_anchor(result.rule) == expected, text
        assert text[result.start:result.end] == result.words and result.words in text, text


def test_none_of_the_messages_with_a_repeat_this_will_not_read_or_none_at_all_has_one_found():
    from labelled_repeats import ONE_OFF, REPEAT_UNSUPPORTED

    for text in REPEAT_UNSUPPORTED + ONE_OFF:
        assert found(text) is None, text


@pytest.mark.parametrize("text, words", [
    ("Remind me every day at 8am to take my pills", "every day at 8am"),
    ("Remind me every Tuesday and Thursday at 6pm to water the plants", "every Tuesday and Thursday at 6pm"),  # the longest run, not the first word
    ("Remind me on the 1st of every month to pay rent", "on the 1st of every month"),
    ("remind me on weekdays at 7am to pack my lunch", "on weekdays at 7am"),
    ("Remind me to stretch every morning.", "every morning"),  # the full stop is not part of it
    ("Every Monday at 9am, remind me to take out the bins", "Every Monday at 9am"),
    ("remind me every 2 weeks at 10am to submit the report", "every 2 weeks at 10am"),
    ("Remind me   daily   at  noon to drink water", "daily   at  noon"),  # spacing is the person's own
    ("Remind me EVERY MONDAY AT 9AM to bin it", "EVERY MONDAY AT 9AM"),
])
def test_the_words_found_are_the_longest_run_that_reads_as_a_repeat_exactly_as_the_person_wrote_them(text, words):
    result = found(text)
    assert result.words == words and text[result.start:result.end] == words


def test_the_first_repeat_in_a_message_is_the_one_found_and_it_is_read_against_the_clock_given():
    result = found("Remind me every 3 days at 8pm to water the cactus", NOW)
    assert result.rule.canonical() == "every:3@20:00#2026-10-10"  # 20:00 is still ahead on the 10th
    assert found("Remind me every 3 days at 8am to water the cactus", NOW).rule.canonical() == "every:3@08:00#2026-10-11"


@pytest.mark.parametrize("text", [
    "Remind me every Monday and every Friday to send the report",  # two repeats: it will not guess between them
    "Remind me every day at 8am and every evening at 7pm to take my pills",
    "Remind me every Monday until June to call",  # what it would silently drop
    "Remind me every hour to stretch",
    "Remind me every second Tuesday to water the plants",
    "Remind me every weekend to rest",
    "Remind me every year on 3 March to call mum",
    "Remind me every day for 5 days to stretch",
])
def test_a_message_that_says_more_than_this_reads_has_no_repeat_found_rather_than_a_part_of_it(text):
    assert found(text) is None


@pytest.mark.parametrize("text", ["", "   ", "Remind me to call mum", "every", "every person on the list", "each", "Remind me tomorrow at 5pm"])
def test_a_message_with_no_repeat_in_it_has_none_found(text):
    assert found(text) is None


def test_a_bare_daily_is_a_repeat_every_day_at_nine():
    assert found("daily").rule.canonical() == "daily@09:00"


@pytest.mark.parametrize("junk", [None, 5, ["every day"], b"every day", True])
def test_what_is_not_text_has_none_found(junk):
    assert found(junk) is None


def test_only_the_start_of_a_long_message_is_searched():
    long_message = "Remind me " + "to do a lot of things " * 40 + "every day at 8am"
    assert len(long_message) > diya_repeat.MAX_SCAN_CHARS and found(long_message) is None
    assert found("Remind me every day at 8am " + "and more words " * 100).words == "every day at 8am"


def test_a_run_is_at_most_twelve_words_long_so_the_caller_must_look_at_what_follows_it():
    words = "every Monday and Tuesday and Wednesday and Thursday and Friday and Saturday and Sunday at 9am"
    result = found(words)
    assert result.words == "every Monday and Tuesday and Wednesday and Thursday and Friday and Saturday"  # twelve words, Sunday cut off
    assert len(result.words.split()) == diya_repeat.MAX_RUN_WORDS == 12 and words[result.end:].strip().startswith("and Sunday")


def test_what_is_found_is_a_frozen_value_with_where_it_sits():
    result = found("Remind me every day at 8am to take my pills")
    assert (result.start, result.end) == (10, 26)
    with pytest.raises(Exception):
        result.start = 0


@pytest.mark.parametrize("text, words", [
    ("Remind me every day at 8am about my pills", "every day at 8am"),  # "about" is a filler the reader skips; it belongs to what follows
    ("Remind me every Monday at 9am for the bins", "every Monday at 9am"),
    ("Remind me every day at 8am at the office", "every day at 8am"),
    ("Remind me on the 1st of every month of the year to pay rent", "on the 1st of every month"),
])
def test_filler_words_that_end_a_run_are_not_part_of_the_repeat(text, words):
    result = found(text)
    assert result.words == words and text[result.start:result.end] == words


# ---- what the mutation run found nothing checking ----------------------------------------------------------------------

@pytest.mark.parametrize("word, n", [("two", 2), ("three", 3), ("four", 4), ("five", 5), ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10)])
def test_every_number_word_is_its_number(word, n):
    assert canonical(f"every {word} days") == f"every:{n}@09:00#2026-10-11"
    assert canonical(f"every {n} days") == f"every:{n}@09:00#2026-10-11"


@pytest.mark.parametrize("words", ["every Monday for 3 years", "every Monday for 2 years", "every day for a year"])
def test_a_span_of_years_is_an_end_not_something_unreadable(words):
    with pytest.raises(NotUnderstood, match="an end or a count"):
        parse_repeat(words, NOW)


@pytest.mark.parametrize("words", ["every last day of the month", "on the last day of every month"])
def test_the_last_day_of_the_month_is_refused_with_its_own_reason(words):
    with pytest.raises(NotUnderstood, match="the last day of the month' is not supported"):
        parse_repeat(words, NOW)


@pytest.mark.parametrize("words", ["on weekends at 9am", "every weekend", "every weekends"])
def test_weekends_in_either_number_are_refused_with_their_own_reason(words):
    with pytest.raises(NotUnderstood, match="'weekend' could mean Saturday, Sunday or both"):
        parse_repeat(words, NOW)


@pytest.mark.parametrize("make", [
    lambda: Repeat("daily", time(9, 0, 0, 5)),
    lambda: Repeat("weekly", time(9), days=(-1,)),
    lambda: Repeat("weekly", time(9), days=(1.5,)),
    lambda: Repeat("monthly", time(9), day_of_month=15.5),
    lambda: Repeat("interval", time(9), every=2.5, anchor=date(2026, 1, 1)),
])
def test_a_rule_made_by_hand_is_checked_as_closely_as_one_read_from_words(make):
    with pytest.raises(ValueError):
        make()


def test_an_interval_with_no_count_is_not_a_stored_rule():
    with pytest.raises(ValueError, match="not a repeat rule"):
        Repeat.from_canonical("every@09:00#2026-10-12")


@pytest.mark.parametrize("stored", [
    "weekly:@09:00", "weekly:7@09:00", "weekly:1,1@09:00", "weekly:2,1@09:00", "monthly:0@09:00", "monthly:32@09:00", "monthly:99999999999999999999@09:00",
    "daily:1@09:00", "daily@09:00#2026-10-12", "every:1@09:00#2026-10-12", "every:2@09:00#2026-02-30", "every:2@09:00", "every:366@09:00#2026-10-12",
    "daily@24:00", "daily@09:60", "weekdays:1@09:00", "weekly@09:00", "monthly@09:00",
])
def test_whatever_is_stored_that_is_not_a_rule_is_a_value_error_and_never_another_kind_of_error(stored):
    with pytest.raises(ValueError):
        Repeat.from_canonical(stored)


def test_a_repeat_of_exactly_the_longest_length_is_read_and_one_character_more_is_not():
    longest = "every Monday" + " and Monday" * 7 + " at 9:00 am"
    assert len(longest) == diya_repeat.MAX_CHARS == 100
    assert canonical(longest) == "weekly:0@09:00"
    assert canonical(longest.replace("9:00 am", "9:00   am")) == "weekly:0@09:00"  # spacing is not counted
    with pytest.raises(NotUnderstood, match="too long"):
        parse_repeat(longest + "x", NOW)


def test_nothing_but_filler_words_is_no_repeat_given_at_all():
    with pytest.raises(NotUnderstood, match="no repeat was given"):
        parse_repeat("the", NOW)
    with pytest.raises(NotUnderstood, match="no repeat was given"):
        parse_repeat("at the of", NOW)


def test_a_time_the_reader_cannot_return_is_a_refusal_with_a_reason_not_a_rule_without_a_time(monkeypatch):
    monkeypatch.setattr(diya_repeat.diya_time, "_time_of_day", lambda rest, assumed: None)
    with pytest.raises(NotUnderstood, match="could not read '8am' as a time of day"):
        parse_repeat("every day at 8am", NOW)


def test_the_29th_to_the_31st_say_they_mean_the_last_day_of_a_shorter_month_and_the_28th_does_not():
    for ordinal in ("29th", "30th", "31st"):
        assert f"the {ordinal} means the last day of a month that is shorter" in parse_repeat(f"every month on the {ordinal}", NOW).assumed
    assert not [a for a in parse_repeat("every month on the 28th", NOW).assumed if "last day" in a]


def test_a_longer_gap_than_a_year_is_refused_and_a_year_is_not():
    assert canonical("every 365 days") == "every:365@09:00#2026-10-11"
    with pytest.raises(NotUnderstood, match="every 366 days is not between 2 and 365 days"):
        parse_repeat("every 366 days", NOW)


def test_the_search_stops_at_the_documented_number_of_characters_exactly():
    limit = 600
    assert diya_repeat.MAX_SCAN_CHARS == limit

    def ending_at(length):
        return "a" * (length - len("every day") - 1) + " every day"

    assert len(ending_at(limit)) == limit and found(ending_at(limit)).words == "every day"  # the last character searched is the last of the repeat
    assert len(ending_at(limit + 1)) == limit + 1 and found(ending_at(limit + 1)) is None  # one more and it is cut: "every da"


def test_a_filler_with_punctuation_still_ends_the_run_and_is_left_to_what_follows():
    assert found("Remind me every day at 8am about, um, my pills").words == "every day at 8am"


def test_only_real_text_is_searched_not_whatever_it_prints_as():
    class Printing:
        def __str__(self):
            return "Remind me every day at 8am"

    assert found(Printing()) is None
