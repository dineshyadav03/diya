"""A schema change is never made to a database that has data without a checked copy first, whichever program makes it (diya_backup.guard_migration; docs/BACKUP_DESIGN.md), added 2026-10-18.

Found on 2026-10-18 by looking at the owner's real database: migration 23 had reached it through a scheduled job (Dreaming or the notifier, which load whatever code is on disk), and the only copy taken that
day was the API's daily one from hours before. The rule "snapshot first" had been written into the API's start-up alone. It is now one function every program that opens the database calls first.

What this proves: the function takes a checked snapshot when steps are pending and says so; does nothing when the database is current, new, or backups are off; refuses to go on when the copy cannot be made and
leaves the database as it was; and the scheduled Dreaming pass, the notifier, the review tool and the actions tool each call it before they open the database. It does not prove a migration is correct: a
failing one is rolled back whole by diya_db (tests/test_backup.py), and the snapshot is the way back from a correct one that was unwanted.
"""
import dataclasses
import io
import os

import pytest

import diya_backup as bk
import diya_config
import diya_db
from test_backup import old_database, versions


@pytest.fixture
def config(tmp_path):
    return dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "old.db"), backup_dir=str(tmp_path / "backups"), dream_log_path=str(tmp_path / "dream.log"), dream_state_path=str(tmp_path / "state.json"),
        dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), data_dir=str(tmp_path), backup=True,
    )


def snapshots(config):
    return sorted(os.listdir(config.backup_dir)) if os.path.isdir(config.backup_dir) else []


def test_pending_steps_get_a_checked_snapshot_first_and_it_says_so(config):
    old_database(config.db_path, upto=3)
    said = []
    assert bk.guard_migration(config, say=said.append) is True
    [name] = snapshots(config)
    assert versions(os.path.join(config.backup_dir, name)) == [1, 2, 3] and name in said[0] and "needed a schema update" in said[0]
    assert versions(config.db_path) == [1, 2, 3]  # the guard copies; it does not migrate


def test_a_current_new_or_unbacked_database_is_left_alone(config, tmp_path):
    said = []
    assert bk.guard_migration(config, say=said.append) is True  # no database yet
    diya_db.Store(config.db_path).get_messages(1)  # now it exists and is current
    assert bk.guard_migration(config, say=said.append) is True
    assert said == [] and snapshots(config) == []
    old_database(str(tmp_path / "other.db"), upto=3)
    off = dataclasses.replace(config, db_path=str(tmp_path / "other.db"), backup=False)
    assert bk.guard_migration(off, say=said.append) is True and snapshots(config) == []


def test_when_the_copy_cannot_be_made_it_says_so_and_the_database_is_untouched(config, tmp_path):
    old_database(config.db_path, upto=3)
    (tmp_path / "backups").write_text("a file where the folder should be")
    said = []
    assert bk.guard_migration(config, say=said.append) is False
    assert "could not be made first" in said[0] and "Nothing was changed" in said[0]
    assert versions(config.db_path) == [1, 2, 3]


def test_the_scheduled_dreaming_pass_takes_the_copy_before_it_migrates(config, tmp_path, monkeypatch):
    import dreaming

    old_database(config.db_path, upto=3)
    monkeypatch.setattr(diya_config, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(dreaming, "run_cycle", lambda dreamer: None)
    monkeypatch.setattr(dreaming, "Dreamer", lambda config: type("D", (), {})())
    assert dreaming.main() == 0
    assert len(snapshots(config)) == 1 and "needed a schema update" in open(config.dream_log_path, encoding="utf-8").read()


def test_the_scheduled_dreaming_pass_does_not_migrate_when_the_copy_fails(config, tmp_path, monkeypatch):
    import dreaming

    old_database(config.db_path, upto=3)
    (tmp_path / "backups").write_text("a file where the folder should be")
    monkeypatch.setattr(diya_config, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(dreaming, "Dreamer", lambda config: pytest.fail("the pass must not start"))
    assert dreaming.main() == 1
    assert versions(config.db_path) == [1, 2, 3]


@pytest.mark.parametrize("tool", ["notify", "review", "actions"])
def test_the_notifier_the_review_tool_and_the_actions_tool_take_the_copy_first(config, tool):
    import diya_actions_cli
    import diya_notify
    import diya_review

    old_database(config.db_path, upto=3)
    calls = {
        "notify": lambda: diya_notify.main(["--dry-run"], config=config, out=io.StringIO(), notify=lambda t, b: None),
        "review": lambda: diya_review.main(["list"], config=config, out=io.StringIO(), err=io.StringIO()),
        "actions": lambda: diya_actions_cli.main(["list"], config=config, out=io.StringIO(), err=io.StringIO(), kinds=()),
    }
    calls[tool]()
    [name] = snapshots(config)
    assert versions(os.path.join(config.backup_dir, name)) == [1, 2, 3]  # the copy is of the database as it was, taken before the tool opened it


def test_a_tool_that_cannot_make_the_copy_stops_before_it_opens_the_database(config, tmp_path):
    import diya_review

    old_database(config.db_path, upto=3)
    (tmp_path / "backups").write_text("a file where the folder should be")
    err = io.StringIO()
    assert diya_review.main(["list"], config=config, out=io.StringIO(), err=err) != 0
    assert "could not be made first" in err.getvalue() and versions(config.db_path) == [1, 2, 3]
