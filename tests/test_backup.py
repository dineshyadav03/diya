"""Backups of the memory (diya_backup.py, docs/BACKUP_DESIGN.md), added 2026-10-18.

What this proves, on throwaway databases: a snapshot is a faithful, checked copy made while the database may be written to; a broken one is never kept and leaves nothing behind; a snapshot is never
overwritten; only the module's own old snapshots are removed, beyond the newest N, and a stranger's file in the folder is never touched; one is made only when none is a day old; `verify` says what is wrong
with a broken or foreign file and never changes a snapshot (an old schema stays old); `restore` puts a snapshot at a NEW path and refuses an existing one; the command line says plainly what it did.
It does not prove that a snapshot restores the owner's real data the way they want: the owner's own `python diya_backup.py make` then `verify` is that.
"""
import dataclasses
import io
import os
import sqlite3
from datetime import datetime, timedelta

import pytest

import diya_backup as bk
import diya_config
import diya_db
from diya_memory import Memory

T0 = datetime(2026, 10, 18, 9, 0, 0)


@pytest.fixture
def config(tmp_path):
    cfg = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "live.db"), backup_dir=str(tmp_path / "backups"))
    store = diya_db.Store(cfg.db_path)
    thread = store.create_thread("t")
    store.add_message(thread, "user", "I have a dog named Rocky")
    Memory(store).add_manual("has a dog named Rocky", "api")
    return cfg


def rows(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_a_snapshot_is_a_checked_copy_with_the_same_rows(config):
    made = bk.make(config, now=T0)
    assert made.name == "diya-20261018-090000.db" and os.path.isfile(made.path) and made.size > 0
    assert rows(made.path, "messages") == rows(config.db_path, "messages") == 1 and rows(made.path, "facts") == 1
    assert bk.check(made.path) == [] and [s.name for s in bk.snapshots(config)] == [made.name]
    assert not any(name.endswith(".part") for name in os.listdir(config.backup_dir))


def test_it_is_consistent_while_the_database_is_being_written_to(config):
    writer = sqlite3.connect(config.db_path)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO messages (thread_id, role, content, created_at) VALUES (1, 'user', 'not yet committed', 'x')")
    try:
        made = bk.make(config, now=T0)  # the uncommitted row is not in the snapshot; the snapshot is whole
    finally:
        writer.rollback()
        writer.close()
    assert rows(made.path, "messages") == 1 and bk.check(made.path) == []


def test_a_missing_database_is_refused_and_nothing_is_made(config):
    os.remove(config.db_path)
    with pytest.raises(bk.BackupError, match="no database"):
        bk.make(config)
    assert not os.path.exists(config.backup_dir) or os.listdir(config.backup_dir) == []


def test_a_snapshot_that_fails_its_check_is_not_kept_and_leaves_nothing(config, monkeypatch):
    monkeypatch.setattr(bk, "check", lambda path: ["the memory says a fact has no events"])
    with pytest.raises(bk.BackupError, match="was not kept.*no events"):
        bk.make(config, now=T0)
    assert os.listdir(config.backup_dir) == []


def test_a_snapshot_is_never_overwritten(config):
    bk.make(config, now=T0)
    with pytest.raises(bk.BackupError, match="already exists"):
        bk.make(config, now=T0)


def test_only_the_newest_n_are_kept_and_only_its_own_files_are_removed(config):
    os.makedirs(config.backup_dir)
    strangers = ("diya-before-eval-cleanup.db", "notes.txt", "diya-2026.db", "diya-20260101-000000.db.bak")
    for stranger in strangers:
        with open(os.path.join(config.backup_dir, stranger), "w") as f:
            f.write("not mine")
    for day in range(5):
        bk.make(config, keep=3, now=T0 + timedelta(days=day))
    assert [s.name for s in bk.snapshots(config)] == ["diya-20261022-090000.db", "diya-20261021-090000.db", "diya-20261020-090000.db"]
    assert set(strangers) <= set(os.listdir(config.backup_dir))


def test_at_least_one_snapshot_is_always_kept(config):
    bk.make(config, now=T0)
    assert bk.prune(config, keep=0) == [] and len(bk.snapshots(config)) == 1


def test_one_is_made_only_when_none_is_a_day_old(config):
    first = bk.make_if_due(config, now=T0)
    assert first.name == "diya-20261018-090000.db"
    assert bk.make_if_due(config, now=T0 + timedelta(hours=23)) is None
    again = bk.make_if_due(config, now=T0 + timedelta(hours=25))
    assert again.name == "diya-20261019-100000.db" and len(bk.snapshots(config)) == 2


def test_a_failing_backup_is_returned_not_raised_so_it_cannot_stop_diya(config):
    os.remove(config.db_path)
    assert isinstance(bk.make_if_due(config, now=T0), bk.BackupError)


def test_the_daily_thread_makes_one_says_so_and_never_raises(config):
    said = []
    thread = bk.Daily(config, say=said.append)
    thread._stop_event.set()  # one pass only
    thread.run()
    assert len(said) == 1 and said[0].startswith("Diya made a backup of her memory: diya-") and len(bk.snapshots(config)) == 1
    for snapshot in bk.snapshots(config):
        os.remove(snapshot.path)
    os.remove(config.db_path)
    said.clear()
    thread.run()
    assert len(said) == 1 and said[0].startswith("Diya's backup did not work")


def test_age_is_measured_from_the_name(config):
    made = bk.make(config, now=T0)
    assert bk.age_hours(made, now=T0 + timedelta(hours=5, minutes=30)) == 5.5 and bk.newest(config).name == made.name


# ---- checking and restoring ------------------------------------------------------------------------------------------------------------------

def test_a_file_that_is_not_a_database_or_not_ours_is_not_good(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("this is not a database")
    assert bk.check(str(junk))
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE t (a)")
    conn.commit()
    conn.close()
    assert any("table messages is missing" in p for p in bk.check(str(other)))
    assert bk.check(str(tmp_path / "nothing.db"))  # a missing file is a problem, not a crash


def test_a_broken_memory_trail_is_found(config):
    conn = sqlite3.connect(config.db_path)
    conn.execute("DELETE FROM fact_events")
    conn.commit()
    conn.close()
    assert any("memory integrity" in p and "no events" in p for p in bk.check(config.db_path))


def test_checking_an_old_snapshot_does_not_change_it(config, tmp_path):
    old = tmp_path / "old.db"
    source, copy = sqlite3.connect(config.db_path), sqlite3.connect(old)
    source.backup(copy)
    copy.execute("DELETE FROM migrations WHERE version = (SELECT MAX(version) FROM migrations)")
    copy.commit()
    before = copy.execute("SELECT MAX(version) FROM migrations").fetchone()[0]
    copy.close()
    source.close()
    before_bytes = old.read_bytes()
    bk.check(str(old))
    check_conn = sqlite3.connect(old)
    try:
        assert old.read_bytes() == before_bytes and check_conn.execute("SELECT MAX(version) FROM migrations").fetchone()[0] == before
    finally:
        check_conn.close()


def test_restore_puts_a_snapshot_at_a_new_path_and_never_over_anything(config, tmp_path):
    made = bk.make(config, now=T0)
    target = str(tmp_path / "new" / "restored.db")
    assert bk.restore(made.path, target) == target and rows(target, "facts") == 1 and bk.check(target) == []
    with pytest.raises(bk.BackupError, match="already exists"):
        bk.restore(made.path, target)
    with pytest.raises(bk.BackupError, match="already exists"):
        bk.restore(made.path, config.db_path)
    assert rows(config.db_path, "facts") == 1


def test_restore_refuses_a_snapshot_that_is_not_good_and_creates_nothing(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_text("not a database")
    with pytest.raises(bk.BackupError, match="not good"):
        bk.restore(str(junk), str(tmp_path / "out.db"))
    assert not (tmp_path / "out.db").exists()


# ---- the command line --------------------------------------------------------------------------------------------------------------------------

def run(args, config):
    out = io.StringIO()
    return bk.main(args, out=out, config=config), out.getvalue()


def test_the_command_line_says_what_it_did(config, tmp_path):
    code, text = run(["list"], config)
    assert code == 0 and "No snapshots" in text
    code, text = run(["make"], config)
    assert code == 0 and text.startswith("Made diya-") and "passes SQLite's check" in text
    code, text = run(["list"], config)
    assert code == 0 and text.count("diya-") == 1 and "less than an hour ago" in text
    name = bk.snapshots(config)[0].path
    assert run(["verify", name], config) == (0, "Good: it opens, passes SQLite's integrity check and the memory's own check.\n")
    target = str(tmp_path / "back.db")
    code, text = run(["restore", name, "--to", target], config)
    assert code == 0 and "DIYA_DB_PATH" in text and "was not touched" in text
    code, text = run(["restore", name, "--to", target], config)
    assert code == bk.EXIT_REFUSED and text.startswith("Not done:")
    junk = tmp_path / "junk.db"
    junk.write_text("x")
    code, text = run(["verify", str(junk)], config)
    assert code == bk.EXIT_FAILED and text.startswith("NOT GOOD:")


def test_a_backup_that_cannot_be_made_exits_with_a_failure_and_a_sentence(config):
    os.remove(config.db_path)
    code, text = run(["make"], config)
    assert code == bk.EXIT_FAILED and text.startswith("Not done: there is no database")


def test_the_settings(tmp_path):
    assert diya_config.load_config({}).backup is True and diya_config.load_config({}).backup_dir == "backups"
    assert diya_config.load_config({"DIYA_BACKUP": "0"}).backup is False
    assert diya_config.load_config({"DIYA_BACKUP_DIR": str(tmp_path)}).backup_dir == str(tmp_path)
