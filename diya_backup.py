"""Backups of Diya's memory, made by themselves and checked (docs/BACKUP_DESIGN.md), added 2026-10-18.

    python diya_backup.py make [--keep N]        a snapshot of the database now, checked
    python diya_backup.py list                   the snapshots, newest first, with their age
    python diya_backup.py verify FILE            is this snapshot a database that opens, passes SQLite's check and the memory's own?
    python diya_backup.py restore FILE --to PATH put a snapshot at PATH (a new file: nothing is ever overwritten) and say how to use it

Everything Diya knows about the owner is one SQLite file. A bad write, a full disk or a sync program fighting over the file could lose all of it, and until now the only copy was the file itself. A snapshot is made
with SQLite's own backup (consistent even while Dreaming or a chat is writing), written to a temporary name and renamed only once it has been checked, so a half-written or broken snapshot never looks like a good one.

Rules this keeps:
* It only ever READS the live database and WRITES new files in the backup folder. It never overwrites a snapshot, and `restore` refuses a target that exists.
* It removes only its own old snapshots (names exactly `diya-YYYYMMDD-HHMMSS.db`), beyond the newest `keep`; a file anyone else put in the folder is never touched.
* The snapshots are as private as the database itself and sit beside it (a folder a sync program may copy: `docs/AUDIT_2026-10-10.md`, F3, says the same of the database). They hold no connector sign-ins (those are separate files).
* A snapshot is only as good as the check: the check proves the file opens, passes SQLite's integrity check and the memory's own trail check, and has the tables. It cannot prove the contents are what the owner wants.

Importing this module has no side effects.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime

import diya_config

NAME = re.compile(r"^diya-([0-9]{8})-([0-9]{6})\.db$")
KEEP = 14
DUE_HOURS = 24
EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2


class BackupError(Exception):
    """The snapshot was not made or not kept, with the reason in one sentence. Nothing half-made is left behind."""


@dataclass(frozen=True)
class Snapshot:
    path: str
    name: str
    taken: datetime  # local wall clock, from the name
    size: int


def _readonly(path):
    return sqlite3.connect("file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro", uri=True)


def check(path):
    """Problems with a snapshot, as sentences; an empty list means it opens, passes SQLite's integrity check, the memory's own trail check, and holds the tables a Diya database has."""
    problems = []
    try:
        conn = _readonly(path)
    except sqlite3.Error as exc:
        return [f"it cannot be opened ({exc})"]
    try:
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("SQLite's integrity check did not say ok")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        except sqlite3.DatabaseError as exc:
            return [f"it is not a database SQLite can read ({exc})"]
    finally:
        conn.close()
    for needed in ("messages", "facts", "migrations"):
        if needed not in tables:
            problems.append(f"table {needed} is missing")
    if not problems:
        problems += _memory_problems(path)
    return problems


def _memory_problems(path):
    """The memory's own trail check, run on a throwaway copy: opening a Store brings an older database up to the current schema, and checking a snapshot must never change it."""
    import diya_db
    import diya_memory

    folder = tempfile.mkdtemp(prefix="diya-check-")
    try:
        copy_path = os.path.join(folder, "copy.db")
        source, copy = _readonly(path), sqlite3.connect(copy_path)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        return [f"memory integrity: {problem}" for problem in diya_memory.Memory(diya_db.Store(copy_path)).verify_integrity()]
    except sqlite3.Error as exc:
        return [f"the memory could not be checked ({exc})"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def snapshots(config):
    """The snapshots in the backup folder, newest first. Only files named the way this module names them."""
    folder = config.backup_dir
    found = []
    try:
        names = os.listdir(folder)
    except OSError:
        return found
    for name in names:
        match = NAME.match(name)
        if not match:
            continue
        try:
            taken = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
            size = os.path.getsize(os.path.join(folder, name))
        except (ValueError, OSError):
            continue
        found.append(Snapshot(os.path.join(folder, name), name, taken, size))
    return sorted(found, key=lambda s: s.taken, reverse=True)


def make(config, keep=KEEP, now=None):
    """Take a snapshot of the live database now, check it, and keep only the newest `keep`. Returns the Snapshot. BackupError (and nothing left behind) if the database is missing, the copy fails, or the
    check finds anything wrong."""
    if not os.path.isfile(config.db_path):
        raise BackupError(f"there is no database at {config.db_path} to copy")
    moment = now or datetime.now()
    name = f"diya-{moment:%Y%m%d-%H%M%S}.db"
    try:
        os.makedirs(config.backup_dir, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"the backup folder {config.backup_dir} could not be made ({exc})")
    target = os.path.join(config.backup_dir, name)
    if os.path.exists(target):
        raise BackupError(f"{name} already exists; a snapshot is never overwritten")
    part = target + ".part"
    try:
        source, copy = _readonly(config.db_path), sqlite3.connect(part)
        try:
            source.backup(copy)
        finally:
            copy.close()
            source.close()
        problems = check(part)
        if problems:
            raise BackupError("the snapshot was not kept: " + "; ".join(problems))
        os.replace(part, target)
    except (sqlite3.Error, OSError) as exc:
        raise BackupError(f"the snapshot could not be made ({exc})")
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
    prune(config, keep)
    return Snapshot(target, name, datetime.strptime(f"{moment:%Y%m%d%H%M%S}", "%Y%m%d%H%M%S"), os.path.getsize(target))


def prune(config, keep=KEEP):
    """Remove this module's own snapshots beyond the newest `keep` (never fewer than 1). Returns the names removed."""
    removed = []
    for old in snapshots(config)[max(1, int(keep)):]:
        try:
            os.remove(old.path)
            removed.append(old.name)
        except OSError:
            pass
    return removed


def newest(config):
    found = snapshots(config)
    return found[0] if found else None


def age_hours(snapshot, now=None):
    return max(0.0, ((now or datetime.now()) - snapshot.taken).total_seconds() / 3600)


def make_if_due(config, now=None, due_hours=DUE_HOURS):
    """A snapshot if there is none yet or the newest is older than `due_hours`; else None. A failure is returned as the BackupError, not raised: a backup that fails must not stop Diya."""
    latest = newest(config)
    if latest is not None and age_hours(latest, now) < due_hours:
        return None
    try:
        return make(config, now=now)
    except BackupError as exc:
        return exc


def restore(snapshot_path, target):
    """Put a snapshot at `target`, a file that does not exist yet. It is checked first; it is never put over anything. Returns the target."""
    if os.path.exists(target):
        raise BackupError(f"{target} already exists; restoring never overwrites anything. Choose a new name.")
    problems = check(snapshot_path)
    if problems:
        raise BackupError("that snapshot is not good: " + "; ".join(problems))
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    source, copy = _readonly(snapshot_path), sqlite3.connect(target)
    try:
        source.backup(copy)
    finally:
        copy.close()
        source.close()
    problems = check(target)
    if problems:
        os.remove(target)
        raise BackupError("the restored copy did not pass its check, so it was removed: " + "; ".join(problems))
    return target


def pending_migrations(path):
    """The versions of the schema this program would add to the database at `path`: [] when it is up to date or does not exist yet (a new database has nothing to lose), every version when the file has
    no record of any. Reads only; never changes the file."""
    import diya_db

    if not os.path.isfile(path):
        return []
    try:
        conn = _readonly(path)
        try:
            has = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'migrations'").fetchone()
            applied = {row[0] for row in conn.execute("SELECT version FROM migrations")} if has else set()
            empty = not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return []  # not a database it can read: the migration would fail by itself and say so; there is nothing to snapshot
    if empty:
        return []
    return [version for version, _statements in diya_db.MIGRATIONS if version not in applied]


def before_migrating(config, now=None):
    """The migration policy (DIYA-016): the schema only moves forward, each step in one transaction that is rolled back whole if it fails (diya_db.apply_migrations), and BEFORE any step is applied to a
    database that has data, a checked snapshot of it is taken, so that the way back is `python diya_backup.py restore` of that snapshot. Returns the Snapshot, or None when there was nothing to migrate.
    BackupError when the snapshot could not be made: the caller then does not migrate."""
    if not pending_migrations(config.db_path):
        return None
    return make(config, now=now)


def guard_migration(config, say=print):
    """The rule of before_migrating for EVERY program that opens the database, not only the API's start-up: if the database has schema steps still to apply, a checked snapshot is taken first, and if it cannot
    be made the program must not go on (this says so and returns False, with the database untouched). Returns True when it is safe to open the database. Found 2026-10-18: a scheduled job (Dreaming, the notifier)
    loads whatever code is on disk, so a new migration reached the owner's real database through one of them with no copy taken, because the rule lived only in the API's start-up. DIYA_BACKUP=0 skips it, as there."""
    if not getattr(config, "backup", True):
        return True
    try:
        taken = before_migrating(config)
    except BackupError as exc:
        say(f"Diya's memory needs a schema update and a safety copy of it could not be made first ({exc}). Nothing was changed. Fix that, or set DIYA_BACKUP=0 to go on without the copy.")
        return False
    if taken is not None:
        say(f"Diya's memory needed a schema update. A checked copy was made first: {taken.name}. To go back: python diya_backup.py restore {taken.path} --to NEWFILE")
    return True


class Daily(threading.Thread):
    """Makes a snapshot when one is due, now and then every hour, while the API runs. A daemon thread: it never keeps Diya from stopping, and a failure is printed once and never raised."""

    def __init__(self, config, say=print, sleep=time.sleep):
        super().__init__(name="diya-backup", daemon=True)
        self.config, self.say, self.sleep = config, say, sleep
        self._stop_event = threading.Event()

    def run(self):
        while True:  # a pass at once, then one an hour, until stopped
            result = make_if_due(self.config)
            if isinstance(result, BackupError):
                self.say(f"Diya's backup did not work: {result}")
            elif result is not None:
                self.say(f"Diya made a backup of her memory: {result.name} ({result.size // 1024} KB), checked.")
            if self._stop_event.wait(3600):
                break

    def stop(self):
        self._stop_event.set()


def _age_words(hours):
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"{int(hours)} hours ago"
    return f"{int(hours // 24)} days ago"


def main(argv=None, out=None, config=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="diya_backup.py", description="Backups of Diya's memory.")
    sub = parser.add_subparsers(dest="command", required=True)
    make_parser = sub.add_parser("make", help="take a checked snapshot of the database now")
    make_parser.add_argument("--keep", type=int, default=KEEP, help=f"how many snapshots to keep (default {KEEP})")
    sub.add_parser("list", help="list the snapshots")
    verify_parser = sub.add_parser("verify", help="check a snapshot")
    verify_parser.add_argument("file")
    restore_parser = sub.add_parser("restore", help="put a snapshot at a new path")
    restore_parser.add_argument("file")
    restore_parser.add_argument("--to", required=True)
    args = parser.parse_args(argv)
    config = config or diya_config.load_config()
    try:
        if args.command == "make":
            made = make(config, keep=args.keep)
            print(f"Made {made.name} ({made.size // 1024} KB) in {config.backup_dir}. It opens, passes SQLite's check and the memory's own check.", file=out)
        elif args.command == "list":
            found = snapshots(config)
            if not found:
                print(f"No snapshots in {config.backup_dir}. Make one with: python diya_backup.py make", file=out)
            for snap in found:
                print(f"{snap.name}  {snap.size // 1024:>6} KB  {_age_words(age_hours(snap))}", file=out)
        elif args.command == "verify":
            problems = check(args.file)
            if problems:
                print("NOT GOOD: " + "; ".join(problems), file=out)
                return EXIT_FAILED
            print("Good: it opens, passes SQLite's integrity check and the memory's own check.", file=out)
        else:
            target = restore(args.file, args.to)
            print(f"Restored to {target}. To use it, start Diya with DIYA_DB_PATH set to that file; your current database was not touched.", file=out)
    except BackupError as exc:
        print(f"Not done: {exc}", file=out)
        return EXIT_REFUSED if "already exists" in str(exc) else EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
