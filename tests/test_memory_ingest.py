"""Getting facts into the store (docs/STAGE2_DESIGN.md, D2, D4, D8 and unit 2): cleaning a staged line,
copying the staged queue in as candidates, and importing the old `user_profile.txt`.

What this proves: a staged line becomes exactly one clean line or is skipped, never something a terminal
or a reviewer could be misled by; ingesting is idempotent and READ-ONLY toward the queue, the checkpoint,
the log and the profile (Dreaming finds its own staged records by scanning that file, so it must stay as
Dreaming wrote it); nothing malformed in the queue can crash the run or get past the sanitiser; and the
legacy import is all-or-nothing, never touches the file, never brings back a fact someone retired, and
never throws an existing profile away because a limit is new.

Characters that are invisible or that change how text is displayed are built with chr(), not typed, so
they stay visible in this file (tests/test_text_files.py enforces that).
"""
import dataclasses
import hashlib
import json
import os
import pathlib
import random
import sqlite3

import pytest

import diya_config
import diya_memory
from diya_db import Store
from diya_memory import (
    FLAG_PREAMBLE,
    FLAG_TOO_LONG,
    BudgetExceeded,
    ImportResult,
    IngestReport,
    InvalidFact,
    Memory,
    SourceUnreadable,
    check_text,
    import_legacy_profile,
    ingest_queue,
    normalise_fact,
    render_profile,
)
from dreaming import Dreamer
from fakes import FakeClient, text_reply

STAGED_AT = "2026-01-01T00:00:00+00:00"
BULLET = chr(0x2022)
BIDI_OVERRIDE, ISOLATE, ZERO_WIDTH, BOM, LINE_SEP, NBSP, PRIVATE = (
    chr(0x202E), chr(0x2066), chr(0x200B), chr(0xFEFF), chr(0x2028), chr(0x00A0), chr(0xE000),
)
FAMILY = "\U0001F468" + chr(0x200D) + "\U0001F469"  # two emoji joined: the joiner is legitimate


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(data / "memory.db"),
        profile_path=str(data / "profile.txt"),
        dream_state_path=str(data / "state.json"),
        dream_log_path=str(data / "dream.log"),
        dream_pending_path=str(data / "pending.jsonl"),
    )


@pytest.fixture
def memory(config):
    return Memory(Store(config.db_path))


def record(first, last, facts, **extra):
    base = {"timestamp": STAGED_AT, "first_message_id": first, "last_message_id": last, "model": "qwen2.5:3b", "facts": facts}
    base.update(extra)
    return base


def write_queue(config, *records):
    """Records as Dreaming writes them: one JSON object per line, UTF-8, LF."""
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in records]
    pathlib.Path(config.dream_pending_path).write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


# --- cleaning one staged line -----------------------------------------------------------------------

@pytest.mark.parametrize("line, expected", [
    ("- likes tea", "likes tea"),
    ("* likes tea", "likes tea"),
    (BULLET + " likes tea", "likes tea"),
    ("1. likes tea", "likes tea"),
    ("12) likes tea", "likes tea"),
    ("  -   likes    tea  ", "likes tea"),
    ("likes tea", "likes tea"),
    ("\t- tabbed in", "tabbed in"),
    ("- - nested", "- nested"),  # one marker, no more
    ("-5 degrees is cold here", "-5 degrees is cold here"),  # a minus sign is not a bullet
    ("1.5 million views", "1.5 million views"),
    ("2024 was a good year", "2024 was a good year"),
    ("a\tb\nc\r\nd", "a b c d"),
    ("- café owner", "café owner"),
    ("- has a cat named Pixel", "has a cat named Pixel"),
    ("- None of my messages say so", "None of my messages say so"),  # only the bare word NONE means "nothing"
    ("Nonetheless he likes tea", "Nonetheless he likes tea"),
])
def test_a_staged_line_becomes_one_clean_fact(line, expected):
    assert normalise_fact(line).text == expected


@pytest.mark.parametrize("line", [
    "", " ", "\n", "-", "- ", "*", "1.", BULLET, "NONE", "none", "None.", "- NONE", "  none  ",
    5, None, b"- likes tea", ["- likes tea"], {"fact": "x"}, True,
])
def test_a_line_with_nothing_to_keep_is_skipped(line):
    assert normalise_fact(line) is None


@pytest.mark.parametrize("line, expected", [
    ("- esc " + chr(27) + "[31mred", "esc [31mred"),
    ("a" + BIDI_OVERRIDE + "b", "ab"),
    ("a" + ISOLATE + "b", "ab"),
    ("a" + ZERO_WIDTH + "b", "ab"),
    (BOM + "- starts with a byte order mark", "starts with a byte order mark"),
    ("nul" + chr(0) + "byte", "nulbyte"),
    ("bell" + chr(7) + "ring", "bellring"),
    ("del" + chr(0x7F) + "ete", "delete"),
    ("private" + PRIVATE + "use", "privateuse"),
    ("two" + LINE_SEP + "words", "two words"),  # whitespace of every kind is a space, not deleted
    ("non" + NBSP + "breaking", "non breaking"),
    ("hidden " + ZERO_WIDTH + " gap", "hidden gap"),  # deleting can leave a double space; it is closed up
    ("a family " + FAMILY + " photo", "a family " + FAMILY + " photo"),  # a joiner inside an emoji stays
])
def test_nothing_invisible_or_display_altering_survives_and_words_are_not_glued_together(line, expected):
    assert normalise_fact(line).text == expected


def test_whatever_comes_out_is_always_a_valid_fact():
    """Seeded fuzz over every kind of character the sanitiser has to deal with."""
    pool = list("abc XYZ019-*.):\t\r\n") + [BULLET, BIDI_OVERRIDE, ISOLATE, ZERO_WIDTH, BOM, LINE_SEP, NBSP, PRIVATE,
                                            chr(27), chr(0), chr(0x7F), chr(0x85), chr(0x200D), "\U0001F468", "é", "山"]
    rng = random.Random(20260925)
    kept = 0
    for _ in range(3000):
        line = "".join(rng.choice(pool) for _ in range(rng.randint(0, 24)))
        fact = normalise_fact(line)
        if fact is None:
            continue
        kept += 1
        check_text(fact.text)  # never raises
        assert fact.text and fact.text == " ".join(fact.text.split())
    assert kept > 1000  # the fuzz really did produce facts, not just nothing


@pytest.mark.parametrize("line", [
    "Here are the new facts:", "here is one", "New facts", "new fact about the user", "The following facts were found",
    "Facts:", "Things I learned about the user:", "ends with a colon:",
])
def test_a_line_that_introduces_a_list_is_kept_and_flagged_not_dropped(line):
    fact = normalise_fact(line)
    assert fact is not None and fact.flags == (FLAG_PREAMBLE,)
    assert fact.text == line


@pytest.mark.parametrize("line", ["- Hereford is a nice town", "- likes new facts and figures", "- has a cat named Pixel", "- the tea is hot"])
def test_ordinary_facts_carry_no_flags(line):
    assert normalise_fact(line).flags == ()


def test_a_line_over_the_length_limit_is_kept_and_flagged():
    limit = diya_memory.MAX_FACT_CHARS
    assert normalise_fact("x" * limit).flags == ()
    over = normalise_fact("- " + "x" * (limit + 1))
    assert over.flags == (FLAG_TOO_LONG,) and len(over.text) == limit + 1
    assert normalise_fact("y" * (limit + 1) + ":").flags == (FLAG_PREAMBLE, FLAG_TOO_LONG)


# --- copying the staged queue in --------------------------------------------------------------------

def stage_with_dreaming(config, memory, *replies):
    """The real producer: messages in the database, a scripted model, one real dream cycle each."""
    store = Store(config.db_path)
    threads = store.list_threads()
    thread = threads[0][0] if threads else store.create_thread()
    for n, reply in enumerate(replies):
        store.add_message(thread, "user", f"something the user said, number {n}")
        Dreamer(config, client=FakeClient([text_reply(reply)]), store=store).dream_cycle()


def test_what_the_real_producer_staged_arrives_as_candidates_with_where_it_came_from(config, memory):
    stage_with_dreaming(config, memory, "- has a cat named Pixel\n- likes tea")
    queued = json.loads(pathlib.Path(config.dream_pending_path).read_text(encoding="utf-8"))

    report = ingest_queue(memory, config)

    assert report == IngestReport(records=1, bad_records=0, new=2, already=0, skipped=0)
    first, second = memory.facts()
    assert (first["text"], first["position"], first["raw"]) == ("has a cat named Pixel", 0, "- has a cat named Pixel")
    assert (second["text"], second["position"], second["raw"]) == ("likes tea", 1, "- likes tea")
    for fact in (first, second):
        assert (fact["status"], fact["source"], fact["model"], fact["extracted_at"], fact["flags"]) == (
            "candidate", "dreaming", "qwen2.5:3b", queued["timestamp"], [])
        assert (fact["batch_first"], fact["batch_last"]) == (queued["first_message_id"], queued["last_message_id"])
        (event, actor, _at, _detail), = memory.events(fact["id"])
        assert (event, actor) == ("ingested", "cli")
    assert memory.verify_integrity() == []


def test_a_staged_fact_is_not_something_the_model_is_told(config, memory):
    stage_with_dreaming(config, memory, "- has a cat named Pixel")
    ingest_queue(memory, config)
    assert memory.accepted_texts() == [] and memory.render() == ""


def test_ingesting_again_adds_nothing_and_a_grown_queue_adds_only_the_new(config, memory):
    stage_with_dreaming(config, memory, "- has a cat named Pixel\n- likes tea")
    ingest_queue(memory, config)
    before = (memory.facts(), [memory.events(f["id"]) for f in memory.facts()])

    again = ingest_queue(memory, config)
    assert again == IngestReport(records=1, bad_records=0, new=0, already=2, skipped=0)
    assert (memory.facts(), [memory.events(f["id"]) for f in memory.facts()]) == before

    stage_with_dreaming(config, memory, "- works in the evenings")
    grown = ingest_queue(memory, config)
    assert grown == IngestReport(records=2, bad_records=0, new=1, already=2, skipped=0)
    assert [f["text"] for f in memory.facts()] == ["has a cat named Pixel", "likes tea", "works in the evenings"]


def test_ingesting_never_touches_the_queue_the_checkpoint_the_log_or_the_profile(config, memory):
    stage_with_dreaming(config, memory, "- has a cat named Pixel")
    pathlib.Path(config.profile_path).write_bytes(b"- an existing trusted fact\n")
    pathlib.Path(config.dream_log_path).write_bytes(b"--- dream cycle ---\n")
    paths = [config.dream_pending_path, config.dream_state_path, config.profile_path, config.dream_log_path]
    before = {p: sha(p) for p in paths}
    listing = sorted(os.listdir(pathlib.Path(config.dream_pending_path).parent))

    ingest_queue(memory, config)
    ingest_queue(memory, config)

    assert {p: sha(p) for p in paths} == before
    assert sorted(os.listdir(pathlib.Path(config.dream_pending_path).parent)) == listing  # and it made no new file


def test_dreaming_still_finds_what_it_staged_after_the_queue_has_been_ingested(config, memory):
    """The reason the queue is never edited (design doc P1): Dreaming spots a batch it staged but did
    not checkpoint by scanning this file. Simulate the crash between the two, ingest, then let Dreaming
    run: it must only move the checkpoint, and must not ask the model or stage the messages again."""
    stage_with_dreaming(config, memory, "- has a cat named Pixel")
    os.remove(config.dream_state_path)  # died after staging, before the checkpoint moved
    ingest_queue(memory, config)

    client = FakeClient()  # any call to the model would be recorded (and would fail: it has no replies)
    Dreamer(config, client=client).dream_cycle()

    assert client.chat_calls == []
    assert json.loads(pathlib.Path(config.dream_state_path).read_text()) == {"last_message_id": 1}
    assert len(pathlib.Path(config.dream_pending_path).read_text(encoding="utf-8").strip().split("\n")) == 1


def test_a_skipped_line_still_takes_its_position_so_slots_never_shift(config, memory):
    write_queue(config, record(1, 3, ["- a", "", "- b", "NONE", "  - ", 5, None, {"x": 1}, "- c"]))
    report = ingest_queue(memory, config)
    assert report == IngestReport(records=1, bad_records=0, new=3, already=0, skipped=6)
    assert [(f["text"], f["position"]) for f in memory.facts()] == [("a", 0), ("b", 2), ("c", 8)]


def test_a_queue_full_of_malformed_records_ingests_what_is_sound_and_crashes_on_nothing(config, memory):
    write_queue(
        config,
        record(1, 1, ["- good one"]),
        '{"first_message_id": 2, "last_message_id": 2, "facts": ["- torn',  # a torn line, as after a crash
        "[1, 2, 3]",  # valid JSON, not a record
        "not json at all",
        record(True, 5, ["- boolean id"]),  # True == 1 in Python, but is no message id
        record(9, 4, ["- last before first"]),
        record(10, 10, "- facts is a string"),
        record(11, 11, None),
        record(12, 12, {"a": "- facts is an object"}),
        {"first_message_id": 13, "last_message_id": 13},  # no facts key at all
        {"first_message_id": 14, "last_message_id": 14, "facts": ["- no model or time recorded"]},
        record(15, 15, ["- esc " + chr(27) + "[2Jhidden " + BIDI_OVERRIDE + "text", "- " + "z" * 1_000_000]),
    )
    report = ingest_queue(memory, config)

    assert (report.bad_records, report.new, report.skipped) == (4, 4, 0)
    texts = {f["text"][:30] for f in memory.facts()}
    assert texts == {"good one", "no model or time recorded", "esc [2Jhidden text", "z" * 30}
    bare = next(f for f in memory.facts() if f["text"].startswith("no model"))
    assert (bare["model"], bare["extracted_at"]) == ("", "")
    huge = next(f for f in memory.facts() if f["text"].startswith("zzzz"))
    assert huge["flags"] == [FLAG_TOO_LONG]
    assert memory.verify_integrity() == []  # everything stored is a clean, consistent fact


def test_a_second_record_that_starts_at_the_same_message_is_ignored_the_first_wins(config, memory):
    write_queue(config, record(1, 1, ["- the original"]), record(1, 1, ["- a later duplicate", "- and another"]))
    report = ingest_queue(memory, config)
    assert report.records == 2 and report.new == 2 and report.already == 1  # position 0 was taken; position 1 is a new slot
    assert [f["text"] for f in memory.facts()] == ["the original", "and another"]


def test_the_same_words_in_two_records_are_two_candidates_and_a_staged_fact_can_repeat_an_accepted_one(config, memory):
    """Spotting repeats is a check that annotates (unit 3); ingesting does not decide for anyone."""
    memory.add_manual("likes tea", "cli")
    write_queue(config, record(1, 1, ["- likes tea"]), record(2, 2, ["- Likes Tea"]))
    assert ingest_queue(memory, config).new == 2
    assert [f["status"] for f in memory.facts()] == ["accepted", "candidate", "candidate"]


def test_flags_from_cleaning_are_recorded_with_the_candidate(config, memory):
    write_queue(config, record(1, 1, ["- Here are the facts:", "- " + "w" * 250, "- plain"]))
    ingest_queue(memory, config)
    assert [f["flags"] for f in memory.facts()] == [[FLAG_PREAMBLE], [FLAG_TOO_LONG], []]


def test_the_actor_is_recorded(config, memory):
    write_queue(config, record(1, 1, ["- a fact"]))
    ingest_queue(memory, config, actor="api")
    (fact,) = memory.facts()
    assert memory.events(fact["id"])[0][1] == "api"
    with pytest.raises(ValueError):
        ingest_queue(memory, config, actor="somebody")


def test_no_queue_file_means_nothing_to_ingest_and_no_file_is_made(config, memory):
    assert ingest_queue(memory, config) == IngestReport()
    assert not os.path.exists(config.dream_pending_path)


def test_an_unreadable_queue_ingests_nothing_and_says_so(config, memory):
    os.mkdir(config.dream_pending_path)  # a directory where the file should be
    with pytest.raises(SourceUnreadable):
        ingest_queue(memory, config)
    os.rmdir(config.dream_pending_path)
    pathlib.Path(config.dream_pending_path).write_bytes(json.dumps(record(1, 1, ["- ok"])).encode() + b"\n\xff\xfe not utf-8\n")
    with pytest.raises(SourceUnreadable):
        ingest_queue(memory, config)
    assert memory.facts() == []


def test_importing_the_module_does_not_load_the_model_client(run_python):
    result = run_python("import sys, diya_memory; print('openai' in sys.modules)")
    assert result.returncode == 0 and result.stdout.strip() == "False", result.stderr


# --- importing the old profile ----------------------------------------------------------------------

def write_profile(config, content):
    pathlib.Path(config.profile_path).write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def test_the_old_profile_comes_in_as_accepted_facts_and_renders_exactly_as_it_was(config, memory):
    body = "- likes tea\n- has a cat named Pixel\n- works in the evenings\n"
    write_profile(config, body)

    result = import_legacy_profile(memory, config)

    assert result == ImportResult(imported=3, already=0, duplicates=0, chars_used=len(body.strip()), over_budget=False)
    assert memory.render() == body.strip()  # what the model is told does not change
    for fact in memory.facts():
        assert (fact["status"], fact["source"]) == ("accepted", "legacy_profile")
        (event, actor, _at, _detail), = memory.events(fact["id"])
        assert (event, actor) == ("imported", "import")
    assert memory.facts()[0]["raw"] == "- likes tea"
    assert memory.verify_integrity() == []


def test_importing_never_modifies_the_profile_or_makes_another_file(config, memory):
    write_profile(config, "- likes tea\r\n- café owner\n")
    memory.counts()  # the database is made on first use, so make it before looking at the folder
    before, listing = sha(config.profile_path), sorted(os.listdir(pathlib.Path(config.profile_path).parent))
    import_legacy_profile(memory, config)
    import_legacy_profile(memory, config)
    assert sha(config.profile_path) == before
    assert sorted(os.listdir(pathlib.Path(config.profile_path).parent)) == listing


def test_importing_twice_imports_once(config, memory):
    write_profile(config, "- likes tea\n- has a cat named Pixel\n")
    import_legacy_profile(memory, config)
    again = import_legacy_profile(memory, config)
    assert (again.imported, again.already, again.duplicates) == (0, 2, 0)
    assert memory.accepted_texts() == ["likes tea", "has a cat named Pixel"]


def test_a_fact_someone_retired_does_not_come_back_when_the_import_is_run_again(config, memory):
    write_profile(config, "- likes tea\n- has a cat named Pixel\n")
    import_legacy_profile(memory, config)
    tea = memory.facts()[0]["id"]
    memory.decide(tea, "retire", "cli")

    again = import_legacy_profile(memory, config)

    assert (again.imported, again.already) == (0, 2)
    assert memory.accepted_texts() == ["has a cat named Pixel"]
    assert memory.get(tea)["status"] == "retired"


@pytest.mark.parametrize("name, content, expected", [
    ("crlf", b"- likes tea\r\n- has a cat\r\n", ["likes tea", "has a cat"]),
    ("bom", "\ufeff- likes tea\n".encode("utf-8"), ["likes tea"]),
    ("no bullets", b"Likes guitar.\nPlays in the evenings\n", ["Likes guitar.", "Plays in the evenings"]),
    ("blank lines and padding", b"\n\n  - likes tea   \n\n\n- has a cat\n\n", ["likes tea", "has a cat"]),
    ("non-ascii", "- café owner\n- 山田 lives in Osaka\n".encode("utf-8"), ["café owner", "山田 lives in Osaka"]),
    ("a stray invalid byte", b"- fine fact\n- bad \xff byte\n", ["fine fact", "bad \ufffd byte"]),
    ("a lone marker and NONE", b"- likes tea\n-\nNONE\n- has a cat\n", ["likes tea", "has a cat"]),
    ("no trailing newline", b"- likes tea", ["likes tea"]),
])
def test_the_profile_is_read_the_way_the_model_has_always_read_it(config, memory, name, content, expected):
    write_profile(config, content)
    import_legacy_profile(memory, config)
    assert memory.accepted_texts() == expected


def test_no_profile_or_an_empty_one_imports_nothing_and_is_not_an_error(config, memory):
    assert import_legacy_profile(memory, config) == ImportResult(0, 0, 0, 0, False)
    assert not os.path.exists(config.profile_path)  # and it was not created
    write_profile(config, b"")
    assert import_legacy_profile(memory, config).imported == 0
    write_profile(config, b"\n  \n\n")
    assert import_legacy_profile(memory, config).imported == 0
    assert memory.facts() == []


def test_an_unreadable_profile_imports_nothing_and_says_so(config, memory):
    os.mkdir(config.profile_path)
    with pytest.raises(SourceUnreadable):
        import_legacy_profile(memory, config)
    assert memory.facts() == []


def test_repeats_are_skipped_not_errors(config, memory):
    memory.add_manual("works in the evenings", "cli")
    write_profile(config, "- likes tea\n- Likes Tea\n- LIKES TEA\n- Works In The Evenings\n- has a cat\n")
    result = import_legacy_profile(memory, config)
    assert (result.imported, result.duplicates) == (2, 3)
    assert memory.accepted_texts() == ["works in the evenings", "likes tea", "has a cat"]


def test_the_import_is_all_or_nothing(config, memory):
    """A failure on the third line leaves none of the first two behind."""
    write_profile(config, "- one\n- two\n- three\n- four\n")
    conn = Store(config.db_path).connect()
    conn.execute(
        "CREATE TRIGGER stop_the_third BEFORE INSERT ON fact_events WHEN NEW.event = 'imported' "
        "AND (SELECT COUNT(*) FROM fact_events WHERE event = 'imported') >= 2 "
        "BEGIN SELECT RAISE(ABORT, 'the third line could not be written'); END"
    )
    conn.commit()
    conn.close()
    with pytest.raises(sqlite3.DatabaseError):
        import_legacy_profile(memory, config)
    assert memory.facts() == []


def test_the_store_itself_refuses_a_line_that_is_not_clean_and_imports_none_of_the_batch(memory):
    with pytest.raises(InvalidFact):
        memory.import_legacy([("fine", "- fine", ()), ("not\nclean", "x", ())])
    assert memory.facts() == []


def test_a_profile_over_the_limit_is_imported_whole_but_stops_new_facts_until_it_is_under(config, memory, monkeypatch):
    """An existing profile is not thrown away because a limit is new; it only stops NEW facts."""
    lines = ["- " + "a" * 30, "- " + "b" * 30, "- " + "c" * 30]
    write_profile(config, "\n".join(lines) + "\n")
    monkeypatch.setattr(diya_memory, "MAX_PROFILE_CHARS", 50)

    result = import_legacy_profile(memory, config)

    assert result.imported == 3 and result.over_budget is True and result.chars_used == len(render_profile(["a" * 30, "b" * 30, "c" * 30]))
    assert len(memory.accepted_texts()) == 3  # all of it, not what fits
    with pytest.raises(BudgetExceeded):
        memory.add_manual("one more", "cli")
    first, second, third = [f["id"] for f in memory.facts()]
    memory.decide(first, "retire", "cli")
    with pytest.raises(BudgetExceeded):  # still over: two of them are 65 characters
        memory.add_manual("one more", "cli")
    memory.decide(second, "retire", "cli")
    memory.add_manual("one more", "cli")  # now it fits
    assert memory.accepted_texts() == ["c" * 30, "one more"]
    assert third


def test_a_long_or_odd_legacy_line_is_kept_as_it_was_flagged_but_not_refused(config, memory):
    write_profile(config, "- " + "L" * 300 + "\n- Here are the facts:\n")
    result = import_legacy_profile(memory, config)
    assert result.imported == 2
    long_fact, preamble = memory.facts()
    assert (long_fact["flags"], preamble["flags"]) == ([FLAG_TOO_LONG], [FLAG_PREAMBLE])
    assert long_fact["status"] == preamble["status"] == "accepted"  # faithful: it is what the model has been told


def test_the_import_reports_the_actor_and_refuses_an_unknown_one(config, memory):
    write_profile(config, "- likes tea\n")
    with pytest.raises(ValueError):
        import_legacy_profile(memory, config, actor="somebody")
    assert memory.facts() == []
    import_legacy_profile(memory, config, actor="cli")
    assert memory.events(memory.facts()[0]["id"])[0][1] == "cli"
