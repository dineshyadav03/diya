"""The scorecard (diya_scorecard.py; docs/SCORECARD.md; task DIYA-224), added 2026-10-21.

What this proves, with a real database in a temporary folder: the middle and the slow end of the answers are said only when there are enough answers for them to mean anything, and are the right
numbers when there are; failures and tool calls are counted; the scorecard holds counts and times and never a word the person wrote; what is recomputed by code (the labelled messages the category rules place,
and place right) agrees with the test that guards it; a baseline can be kept and compared, and only what is clearly worse is flagged (a rise in failures, a slower slow end, fewer labelled messages placed
right, fewer tests), not noise and not a first run with nothing to compare with; every recorded measurement points at a document that exists; and the commands never touch the real database in these tests.
"""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import diya_config
import diya_scorecard as sc
from diya_db import Store

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "s.db"))


def add_turns(store, times_ms, ok=True, days_ago=1):
    conn = store.connect()
    try:
        at = (NOW - timedelta(days=days_ago)).isoformat()
        conn.executemany("INSERT INTO turn_stats (at, route, ms, ok, tools) VALUES (?, 'chat', ?, ?, 0)", [(at, ms, 1 if ok else 0) for ms in times_ms])
        conn.commit()
    finally:
        conn.close()


def test_too_few_answers_give_a_count_but_no_middle_or_slow_end(store):
    add_turns(store, [1000] * (sc.MIN_TURNS - 1))
    found = sc.measure_live(store, NOW)
    assert found["turns"] == sc.MIN_TURNS - 1 and found["p50_ms"] is None and found["p95_ms"] is None


def test_enough_answers_give_the_middle_and_the_slow_end(store):
    add_turns(store, list(range(1000, 21000, 1000)))  # 20 answers: 1 s ... 20 s
    found = sc.measure_live(store, NOW)
    assert found["turns"] == 20 and found["failed"] == 0
    assert found["p50_ms"] == 11000 and found["p95_ms"] == 20000


def test_failures_are_counted_and_do_not_count_toward_the_middle(store):
    add_turns(store, [2000] * 25)
    add_turns(store, [90000] * 5, ok=False)
    found = sc.measure_live(store, NOW)
    assert found["turns"] == 30 and found["failed"] == 5 and found["p50_ms"] == 2000 and found["p95_ms"] == 2000


def test_answers_older_than_the_window_are_left_out(store):
    add_turns(store, [1000] * 30, days_ago=sc.WINDOW_DAYS + 3)
    assert sc.measure_live(store, NOW)["turns"] == 0


def test_the_oldest_message_waiting_to_be_read_is_measured_in_hours(store):
    assert sc.measure_live(store, NOW)["oldest_wait_hours"] is None  # nothing queued: nothing waiting
    message = store.add_message(store.main_thread(), "user", "I got a new dog named Hog today")
    conn = store.connect()
    try:
        conn.execute("DELETE FROM capture_queue")
        conn.execute("INSERT INTO capture_queue (message_id, state, created_at) VALUES (?, 'pending', ?)", (message, (NOW - timedelta(hours=3, minutes=30)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    assert sc.measure_live(store, NOW)["oldest_wait_hours"] == 3.5


def test_the_scorecard_holds_numbers_and_never_a_word_the_person_wrote(store):
    thread = store.main_thread()
    store.add_message(thread, "user", "my secret dentist appointment is on Thursday")
    store.add_message(thread, "assistant", "Noted, the dentist is on Thursday.")
    add_turns(store, [1500] * 25)
    live, code = sc.measure_live(store, NOW), {"rules": {"labelled": 48, "placed": 13, "right": 13}, "tests": 100}
    text = sc.render(live, code, [{"label": "Memory", "status": "ok", "text": "270 messages and 12 remembered facts."}], NOW)
    assert "dentist" not in text and "Thursday" not in text and "secret" not in text
    assert "| Answers timed | 25 |" in text and "| Half of answers took | 1.5 s |" in text


def test_a_scorecard_with_few_answers_says_so_instead_of_inventing_a_speed(store):
    add_turns(store, [108000])
    live = sc.measure_live(store, NOW)
    text = sc.render(live, {"rules": {"labelled": 1, "placed": 1, "right": 1}, "tests": 1}, [], NOW)
    assert "Too few answers have been timed" in text and "| Half of answers took | - |" in text


def test_what_code_recomputes_agrees_with_the_test_that_guards_it(monkeypatch):
    monkeypatch.setattr(sc, "count_tests", lambda: 1)  # (counting tests starts pytest, which a test must not do)
    from labelled_categories import LETTERS, MESSAGES

    import diya_categories

    placed = [(t, letters, diya_categories.by_code(t)) for t, letters in MESSAGES]
    placed = [item for item in placed if item[2]]
    right = [item for item in placed if item[2] in {LETTERS[letter] for letter in item[1]}]
    code = sc.measure_code()
    assert code["rules"] == {"labelled": len(MESSAGES), "placed": len(placed), "right": len(right)} and len(placed) >= 10 and len(right) == len(placed)


def test_the_test_count_is_read_from_pytests_own_last_line(monkeypatch):
    class Done:
        stdout = "tests/a.py::test_x\n\n8157 tests collected in 13.48s\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    assert sc.count_tests() == 8157

    def broken(*a, **k):
        raise subprocess.TimeoutExpired("pytest", 120)

    monkeypatch.setattr(subprocess, "run", broken)
    assert sc.count_tests() is None


BASE = {"turns": 40, "failed": 2, "p50_ms": 5000, "p95_ms": 20000, "category_right": 13, "tests": 8000, "date": "2026-10-20"}
SAME = {"turns": 40, "failed": 2, "p50_ms": 5000, "p95_ms": 20000, "category_labelled": 48, "category_placed": 13, "category_right": 13, "tests": 8100}


def test_nothing_is_flagged_without_a_baseline_or_when_nothing_is_worse():
    assert sc.regressions(SAME, None) == []
    assert sc.regressions(SAME, BASE) == []
    assert sc.regressions(dict(SAME, p95_ms=29000, failed=3), BASE) == []  # noise: not half again as slow, not five points more failures


@pytest.mark.parametrize("change, phrase", [
    ({"failed": 5}, "answers that failed rose from 5% to 12%"),
    ({"p95_ms": 31000}, "the slow end of answers went from 20 s to 31 s"),
    ({"category_right": 12}, "fell from 13 to 12"),
    ({"tests": 7999}, "tests fell from 8000 to 7999"),
])
def test_what_is_clearly_worse_is_flagged_in_words(change, phrase):
    assert any(phrase in line for line in sc.regressions(dict(SAME, **change), BASE))


def test_speed_and_failures_are_compared_only_when_both_sides_have_enough_answers():
    few = dict(SAME, turns=3, failed=3, p95_ms=None)
    assert sc.regressions(few, BASE) == []
    assert sc.regressions(dict(SAME, failed=30), dict(BASE, turns=3, failed=0)) == []


def test_every_recorded_measurement_names_a_document_that_exists():
    assert len(sc.RECORDED) >= 4
    for date, what, result, where in sc.RECORDED:
        assert (ROOT / where).is_file() and date.startswith("2026-") and what and result


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    config = diya_config.load_config({})
    import dataclasses

    config = dataclasses.replace(config, db_path=str(tmp_path / "cmd.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
                                 profile_path=str(tmp_path / "profile.txt"))
    monkeypatch.setattr(diya_config, "load_config", lambda env=None: config)
    monkeypatch.setattr(sc, "BASELINE", tmp_path / "baseline.json")
    monkeypatch.setattr(sc, "DOC", tmp_path / "SCORECARD.md")
    monkeypatch.setattr(sc, "count_tests", lambda: 8200)
    return config


def test_the_commands_keep_a_baseline_write_the_page_and_compare(isolated, tmp_path, capsys):
    assert sc.main(["--compare"]) == 2 and "no baseline yet" in capsys.readouterr().out
    assert sc.main(["--save-baseline"]) == 0
    kept = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))
    assert kept["tests"] == 8200 and kept["category_right"] == kept["category_placed"] and kept["date"]
    assert sc.main(["--compare"]) == 0 and "Nothing is clearly worse" in capsys.readouterr().out
    assert sc.main(["--write"]) == 0
    page = (tmp_path / "SCORECARD.md").read_text(encoding="utf-8")
    assert "Against the baseline" in page and "nothing is clearly worse" in page
    kept["tests"] = 9000  # a baseline with more tests than there are now: tests were lost
    (tmp_path / "baseline.json").write_text(json.dumps(kept), encoding="utf-8")
    assert sc.main(["--compare"]) == 1 and "tests fell from 9000 to 8200" in capsys.readouterr().out
    assert sc.main(["--wrong"]) == 2


def test_the_scorecard_takes_the_checked_copy_first_like_every_program_that_opens_the_database(tmp_path, monkeypatch):
    import dataclasses
    import io
    import os

    from test_backup import old_database, versions

    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "old.db"), backup_dir=str(tmp_path / "backups"), data_dir=str(tmp_path), backup=True)
    monkeypatch.setattr(diya_config, "load_config", lambda env=None: config)
    monkeypatch.setattr(sc, "BASELINE", tmp_path / "baseline.json")
    old_database(config.db_path, upto=3)
    assert sc.main(["--compare"]) == 2  # (no baseline yet; what matters is what happened to the database first)
    [name] = os.listdir(config.backup_dir)
    assert versions(os.path.join(config.backup_dir, name)) == [1, 2, 3]  # the copy is of the database as it was, taken before it was opened

    # and when the copy cannot be made, it stops before opening the database
    other = dataclasses.replace(config, db_path=str(tmp_path / "old2.db"), backup_dir=str(tmp_path / "blocked"))
    monkeypatch.setattr(diya_config, "load_config", lambda env=None: other)
    old_database(other.db_path, upto=3)
    (tmp_path / "blocked").write_text("a file where the folder should be")
    assert sc.main(["--compare"]) == 2 and versions(other.db_path) == [1, 2, 3]

