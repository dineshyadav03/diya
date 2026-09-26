"""Reading a person's words for a moment (docs/PROACTIVITY_DESIGN.md, D2 and unit P1): diya_time.py.

What this proves: every phrase in the hand-written labelled set is read as the moment it should be, or refused
with a reason that can be relayed to the person, and none is half-accepted (a phrase with something extra in it
is refused whole); what the parser filled in that the person did not say is reported; the result is always
after `now` and never more than five years away, whatever is fed to it (a seeded fuzz run); daylight saving is
the converter's, applied to the wall-clock time it worked out and to nothing else; the phrases a person would
understand that it cannot are measured and stay refused; and importing it reads no clock and needs no database
or model.

Hidden characters are built with chr() (tests/test_text_files.py).
"""
import random
from datetime import datetime, timedelta, timezone

import pytest

import diya_time
import labelled_times as lt
from diya_time import NotUnderstood, When, parse_when

NOW = lt.NOW
IST = timezone(timedelta(hours=5, minutes=30))


def stamp(when):
    return when.local.strftime("%Y-%m-%d %H:%M")


# --- the labelled set --------------------------------------------------------------------------------

def test_the_labelled_now_is_the_wednesday_the_cases_were_written_for():
    assert NOW.strftime("%A %Y-%m-%d %H:%M") == "Wednesday 2026-09-23 10:15"


@pytest.mark.parametrize("words, moment, assumed", lt.ACCEPT, ids=[c[0].strip().replace("\n", " ")[:40] or "empty" for c in lt.ACCEPT])
def test_a_phrase_is_read_as_the_moment_it_says_and_what_was_assumed_is_reported(words, moment, assumed):
    when = parse_when(words, NOW)
    assert stamp(when) == moment
    for phrase in assumed:
        assert any(phrase in item for item in when.assumed), (phrase, when.assumed)
    if not assumed:
        assert when.assumed == ()  # nothing was guessed, so nothing is reported


@pytest.mark.parametrize("words, reason", lt.REFUSE, ids=[repr(c[0])[:40] for c in lt.REFUSE])
def test_a_phrase_that_cannot_be_read_is_refused_with_a_reason_that_can_be_relayed(words, reason):
    with pytest.raises(NotUnderstood) as refused:
        parse_when(words, NOW)
    assert reason in refused.value.reason
    assert str(refused.value) == refused.value.reason


def test_a_refusal_never_repeats_a_hidden_character_back_as_one():
    """The reason is relayed to the model and shown to the person, and may quote their words: it must be safe to show."""
    for words in ("friday " + chr(27) + "[2J 5pm", "friday" + chr(0) + "5pm", "friday 5pm " + chr(0x202E) + "x"):
        with pytest.raises(NotUnderstood) as refused:
            parse_when(words, NOW)
        assert all(ch.isprintable() for ch in refused.value.reason), ascii(refused.value.reason)


def test_the_phrases_a_person_would_understand_and_it_cannot_are_refused_and_counted():
    refused = 0
    for words in lt.LIMITS:
        with pytest.raises(NotUnderstood):
            parse_when(words, NOW)
        refused += 1
    assert refused == len(lt.LIMITS) == 13  # a limit that starts working is a visible change to this number


def test_the_size_of_the_labelled_set_is_pinned():
    assert (len(lt.ACCEPT), len(lt.REFUSE), len(lt.LIMITS)) == (79, 65, 13)


# --- how the answer is shaped --------------------------------------------------------------------------

def test_the_answer_carries_the_wall_clock_time_the_utc_moment_and_the_words():
    when = parse_when("  Friday   5pm ", NOW, to_utc=lambda naive: (naive - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc))
    assert isinstance(when, When)
    assert when.local == datetime(2026, 9, 25, 17, 0) and when.local.tzinfo is None
    assert when.utc == datetime(2026, 9, 25, 11, 30, tzinfo=timezone.utc)
    assert when.iso() == "2026-09-25T11:30:00Z"
    assert when.words == "Friday 5pm"  # whitespace collapsed, otherwise as given
    assert when.describe() == "Friday 25 Sep 2026, 17:00"
    with pytest.raises(Exception):
        when.local = NOW  # frozen


def test_describe_does_not_depend_on_the_machines_language():
    assert parse_when("sunday 8:05am", NOW).describe() == "Sunday 27 Sep 2026, 08:05"
    assert parse_when("oct 3 2027 8am", NOW).describe() == "Sunday 3 Oct 2027, 08:00"


def test_a_time_is_read_from_the_minute_the_clock_shows_not_from_its_seconds():
    assert parse_when("in 5 minutes", datetime(2026, 9, 23, 10, 15, 59, 999999)).local == datetime(2026, 9, 23, 10, 20)  # exactly
    assert parse_when("10:16", datetime(2026, 9, 23, 10, 15, 59)).local == datetime(2026, 9, 23, 10, 16)


def test_a_time_that_is_exactly_now_has_passed():
    with pytest.raises(NotUnderstood, match="already passed"):
        parse_when("10:15 today", NOW)
    assert stamp(parse_when("10:16 today", NOW)) == "2026-09-23 10:16"


def test_tonight_after_eight_has_passed_unless_a_time_is_given():
    late = datetime(2026, 9, 23, 21, 0)
    with pytest.raises(NotUnderstood, match="already passed"):
        parse_when("tonight", late)
    assert stamp(parse_when("tonight at 11pm", late)) == "2026-09-23 23:00"


def test_a_weekday_on_that_weekday_is_today_only_while_the_time_is_ahead():
    friday_morning, friday_evening = datetime(2026, 9, 25, 8, 0), datetime(2026, 9, 25, 18, 0)
    assert stamp(parse_when("friday 5pm", friday_morning)) == "2026-09-25 17:00"
    later = parse_when("friday 5pm", friday_evening)
    assert stamp(later) == "2026-10-02 17:00" and any("next week" in item for item in later.assumed)


def test_across_a_month_and_a_year_end():
    assert stamp(parse_when("tomorrow 9am", datetime(2026, 12, 31, 23, 0))) == "2027-01-01 09:00"
    assert stamp(parse_when("in 2 days", datetime(2026, 2, 27, 12, 0))) == "2026-03-01 09:00"  # 2026 is not a leap year
    assert stamp(parse_when("in 2 days", datetime(2028, 2, 27, 12, 0))) == "2028-02-29 09:00"


# --- the converter, and daylight saving ---------------------------------------------------------------------

def test_the_converter_is_given_the_naive_wall_clock_time_once_and_its_answer_is_used_as_it_is():
    seen = []

    def to_utc(naive):
        seen.append(naive)
        return datetime(2000, 1, 1, tzinfo=timezone.utc)

    when = parse_when("friday 5pm", NOW, to_utc=to_utc)
    assert seen == [datetime(2026, 9, 25, 17, 0)] and seen[0].tzinfo is None
    assert when.utc == datetime(2000, 1, 1, tzinfo=timezone.utc) and stamp(when) == "2026-09-25 17:00"


def test_daylight_saving_is_the_converters_so_the_same_wall_clock_time_is_a_different_moment_across_the_change():
    def us_like(naive):  # UTC-4 from 8 March to 1 November 2026, UTC-5 otherwise
        summer = datetime(2026, 3, 8) <= naive < datetime(2026, 11, 1)
        return (naive + timedelta(hours=4 if summer else 5)).replace(tzinfo=timezone.utc)

    autumn = datetime(2026, 10, 30, 8, 0)
    before, after = parse_when("31 oct 9am", autumn, to_utc=us_like), parse_when("2 nov 9am", autumn, to_utc=us_like)
    assert (before.local.hour, after.local.hour) == (9, 9)  # the wall clock said 9 both times
    assert before.iso() == "2026-10-31T13:00:00Z" and after.iso() == "2026-11-02T14:00:00Z"


def test_the_default_converter_is_the_operating_systems():
    when = parse_when("in 2 hours", NOW)
    assert when.utc == when.local.astimezone(timezone.utc) and when.utc.tzinfo == timezone.utc


def test_a_converter_that_cannot_place_the_time_is_a_refusal_not_a_crash():
    def broken(naive):
        raise OSError("out of range")

    with pytest.raises(NotUnderstood, match="cannot be worked out"):
        parse_when("friday 5pm", NOW, to_utc=broken)


# --- the clock, and what may be passed --------------------------------------------------------------------

def test_without_a_now_the_real_clock_is_used():
    before = datetime.now().replace(second=0, microsecond=0)
    when = parse_when("in 2 hours")
    after = datetime.now()
    assert before + timedelta(hours=2) <= when.local <= after + timedelta(hours=2)


def test_a_now_with_a_time_zone_is_a_programming_error():
    with pytest.raises(TypeError, match="now must be a naive local datetime"):
        parse_when("friday 5pm", datetime(2026, 9, 23, 10, 15, tzinfo=timezone.utc))


def test_parsing_does_not_change_what_it_was_given():
    words, now = "Friday 5pm", datetime(2026, 9, 23, 10, 15, 30)
    parse_when(words, now)
    assert (words, now) == ("Friday 5pm", datetime(2026, 9, 23, 10, 15, 30))


# --- whatever is fed to it -----------------------------------------------------------------------------------

VOCABULARY = ["today", "tomorrow", "friday", "next", "in", "5pm", "17:30", "at", "9", "hours", "minutes", "sep", "26", "2026", "noon",
              "midnight", "morning", "and", "the", "of", "1", "2", "half", "an", "a", "week", "days", "am", "pm", "10:00", "3/4",
              "2026-09-26", "t", "tonight", "evening", "day", "after", "on", "by", "for", "this", "yesterday", "mon", "dec", "31"]


def test_a_seeded_fuzz_run_only_ever_gives_a_future_moment_within_five_years_or_a_refusal():
    rng = random.Random(20260925)
    read = refused = 0
    limit = NOW + timedelta(days=366 * diya_time.MAX_YEARS)
    for _ in range(4000):
        words = " ".join(rng.choice(VOCABULARY) for _ in range(rng.randint(1, 5)))
        try:
            when = parse_when(words, NOW)
        except NotUnderstood as exc:
            assert exc.reason and isinstance(exc.reason, str)
            refused += 1
            continue
        read += 1
        assert NOW < when.local <= limit, (words, when)
        assert when.utc.tzinfo is not None and when.iso().endswith("Z")
    assert read > 100 and refused > 100  # the run really did exercise both


def test_random_characters_are_refused_and_never_crash():
    rng = random.Random(7)
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789 :/-.,;'\"()!?" + chr(0) + chr(27) + chr(0x202E) + chr(0xFF15) + chr(0x0663)
    for _ in range(3000):
        words = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30)))
        try:
            when = parse_when(words, NOW)
        except NotUnderstood:
            continue
        assert when.local > NOW


def test_huge_and_odd_numbers_are_refused_not_overflowed():
    for words in ("in " + "9" * 5000 + " days", "9" * 500 + "pm", "2026-" + "9" * 300, "in 9999 weeks", "31 dec 9999", "year " + "1" * 90):
        with pytest.raises(NotUnderstood):
            parse_when(words, NOW)


# --- what importing it does --------------------------------------------------------------------------------------

def test_importing_it_reads_no_clock_and_needs_no_database_or_model(run_python):
    code = (
        "import sys\nimport diya_time\n"
        "print(sorted(name for name in ('sqlite3', 'openai', 'chromadb', 'httpx', 'fastapi') if name in sys.modules))\n"
    )
    result = run_python(code)
    assert result.returncode == 0 and result.stdout.strip() == "[]", result.stdout + result.stderr


# --- did the model change the person's words? (disagreement) ----------------------------------------------------------

@pytest.mark.parametrize("said, words, why", lt.CHANGED, ids=[f"{c[1] or 'blank'} | {c[0][:30]}" for c in lt.CHANGED])
def test_a_time_that_adds_or_drops_something_the_person_said_is_caught_and_says_what(said, words, why):
    reason = diya_time.disagreement(words, said)
    assert reason is not None and why in reason, (words, said, reason)


@pytest.mark.parametrize("said, words", lt.THEIRS, ids=[f"{str(c[1]) or 'blank'} | {c[0][:30]}" for c in lt.THEIRS])
def test_the_persons_own_words_pass_however_they_are_written(said, words):
    assert diya_time.disagreement(words, said) is None


def test_what_the_check_cannot_see_is_measured_not_hidden():
    for said, words in lt.NOT_CAUGHT:
        assert diya_time.disagreement(words, said) is None  # a wrong time it cannot tell from a right one
    assert (len(lt.CHANGED), len(lt.THEIRS), len(lt.NOT_CAUGHT)) == (22, 31, 2)


def test_facets_are_the_days_and_times_a_text_mentions_in_a_canonical_form():
    def read(text):
        return [(f.kind, f.value) for f in diya_time.facets(text)]

    assert read("3rd of October at 2pm") == [("date", (None, 10, 3)), ("clock", (14, 0))]
    assert read("Oct 3 2027 5:30 pm") == [("date", (2027, 10, 3)), ("clock", (17, 30))]  # one clock, not two
    assert read("2026-10-03T14:05") == [("date", (2026, 10, 3)), ("clock", (14, 5))]
    assert read("in half an hour") == [("relative", (30, "minutes"))] and read("in an hour") == [("relative", (1, "hours"))]
    assert read("in 2 weeks") == [("relative", (2, "weeks"))] and read("in 90 mins") == [("relative", (90, "minutes"))]
    assert read("fri and tomorrow and tonight") == [("day", ("weekday", 4)), ("day", ("tomorrow",)), ("day", ("tonight",))]
    assert read("noon") == [("clock", (12, 0))] and read("this evening") == [("part", ("evening",))]
    assert read("9 sep") == [("date", (None, 9, 9))]


def test_facets_ignore_what_they_do_not_understand_and_refuse_nothing():
    assert diya_time.facets("call the vet after lunch, soonish") == []
    assert diya_time.facets("2026-13-01 25pm 13:75 3/4") == []  # impossible dates and times are not facets, and not errors
    for value in (None, 5, [], b"friday", {"a": 1}):
        assert diya_time.facets(value) == []
    assert diya_time.facets("x" * 5000 + " friday 5pm") == []  # only the start of a very long text is read


def test_a_date_without_a_year_matches_the_same_date_in_any_year_and_a_different_year_does_not():
    assert diya_time.disagreement("3 October 2026", "on 3 October") is None  # they gave no year, so any year is theirs
    assert diya_time.disagreement("3 October", "on 3 October 2027") is None
    assert "2027" in diya_time.disagreement("3 October 2027", "on 3 October 2026")


def test_a_text_always_agrees_with_itself_and_nothing_ever_raises():
    rng = random.Random(4242)
    for _ in range(3000):
        text = " ".join(rng.choice(VOCABULARY) for _ in range(rng.randint(0, 6)))
        assert diya_time.disagreement(text, text) is None, text
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789 :/-.,;'\"()!?" + chr(0) + chr(27) + chr(0x202E) + chr(0xFF15)
    for _ in range(3000):
        a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40)))
        reason = diya_time.disagreement(a, b)
        assert reason is None or (isinstance(reason, str) and all(ch.isprintable() for ch in reason)), (a, b, reason)


def test_the_reasons_read_as_sentences_to_the_model():
    both = diya_time.disagreement("Friday 4pm", "Remind me on Friday at 3pm to send the report")
    assert both == "the time you gave includes '4pm', which the user did not say, and leaves out '3pm', which they did"
    assert diya_time.disagreement("", "call mum tomorrow") == "you gave no time, but the user's message mentions 'tomorrow'"
    assert diya_time.disagreement("friday", "call mum on friday at 3pm and at 4pm") is None  # two times said: not held to either
