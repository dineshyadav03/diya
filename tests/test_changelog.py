"""CHANGELOG.md keeps up with the database (task DIYA-223).

What this proves: every migration the code carries appears in the changelog's table (so a new migration cannot be added without saying what it holds), every doc the table points to exists, and the recovery
steps name commands that exist. The recovery itself is proved in tests/test_backup.py (a snapshot is taken before a migration and is the way back; a failed migration changes nothing). It does not prove the
changelog's prose is complete.
"""
import pathlib
import re

import diya_backup
import diya_db

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEXT = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def listed_numbers():
    found = set()
    for line in TEXT.split("## Migrations", 1)[1].splitlines():
        cell = line.split("|")[1].strip() if line.startswith("|") and line.count("|") >= 3 else ""
        match = re.fullmatch(r"(\d+)(?:[–-](\d+))?", cell)
        if match:
            found.update(range(int(match.group(1)), int(match.group(2) or match.group(1)) + 1))
    return found


def test_every_migration_is_in_the_table_and_nothing_else_is():
    assert listed_numbers() == {version for version, _ in diya_db.MIGRATIONS}


def test_every_doc_the_changelog_names_exists():
    missing = [path for path in re.findall(r"`(docs/[A-Za-z0-9_./-]+\.md)`", TEXT) if not (ROOT / path).is_file()]
    assert missing == []


def test_the_recovery_steps_name_commands_that_exist():
    for command in ("list", "verify", "restore"):
        assert f"diya_backup.py {command}" in TEXT
        assert command in diya_backup.__doc__
    assert hasattr(diya_backup, "before_migrating")
    assert "diya_run.py --stop" in (ROOT / "diya_run.py").read_text(encoding="utf-8")
