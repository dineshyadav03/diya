"""Move Diya's data out of the code folder (README, "Privacy, and where your data is kept"; docs/AUDIT_2026-10-10.md, F3).

    python diya_data.py move --to FOLDER [--certs] [--dry-run]

By default the database, the access-token hash, Dreaming's files, the notifier's log and the connectors' tokens sit beside the code, which for
this project can be inside a folder a cloud-sync program copies. `DIYA_DATA_DIR` makes Diya keep them in one folder instead; this program
puts what already exists there first.

It COPIES and never deletes or changes the originals: they stay where they are, and removing them is yours to do once you are satisfied.
The database is copied with SQLite's own backup (a consistent copy even if Dreaming runs at that moment), and every copy is checked before
anything is said to be done: files must be identical, the database must pass SQLite's and the memory's own integrity checks and hold the same
number of rows in every table. It refuses to overwrite a file that differs; the one exception is a database that holds no data at all (what a
scheduled task makes if it runs before the move), which it replaces. It prints names and sizes, never what is in them, and ends by printing
the settings to apply: it changes none itself.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import sys

import diya_config

SYNCED = ("onedrive", "dropbox", "google drive", "icloud")
EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2


class Refused(Exception):
    """Nothing was copied: what was asked cannot be done safely."""


def _sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _readonly(path):
    return sqlite3.connect("file:" + os.path.abspath(path).replace("\\", "/") + "?mode=ro", uri=True)


def _tables(conn):
    return [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def database_is_empty(path):
    """True for a database that holds no data of anyone's: every table but the list of migrations has no rows."""
    conn = _readonly(path)
    try:
        return all(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0 for table in _tables(conn) if table != "migrations")
    except sqlite3.DatabaseError:
        return False  # not a database it understands: never treated as empty
    finally:
        conn.close()


def synced_folder(path):
    """The name of the cloud-sync program whose folder `path` is inside, going by its name, or None."""
    lowered = os.path.normcase(os.path.abspath(path)).replace("\\", "/").lower()
    return next((name for name in SYNCED if f"/{name}" in lowered), None)


def _items(config, destination, with_certs):
    """What to copy, as (kind, source, target) for what exists: kind is 'database', 'file' or 'folder'."""
    found = []
    fields = [("database", "db_path"), ("file", "profile_path"), ("file", "dream_log_path"), ("file", "dream_state_path"),
              ("file", "dream_pending_path"), ("file", "notify_log_path"), ("file", "token_path"), ("folder", "connector_tokens_dir"),
              ("file", "connectors_log_path")]
    for kind, field in fields:
        source = getattr(config, field)
        name = diya_config.Config.__dataclass_fields__[field].default
        exists = os.path.isdir(source) if kind == "folder" else os.path.isfile(source)
        if exists:
            found.append((kind, source, os.path.join(destination, name)))
    if with_certs:
        pair = diya_config.tls_files(config)
        if pair is None:
            raise Refused("--certs was asked for but no TLS certificate pair was found (DIYA_SSL_CERT and DIYA_SSL_KEY, or a mkcert pair beside the code)")
        for source in pair:
            found.append(("file", source, os.path.join(destination, "certs", os.path.basename(source))))
    return found


def _check_target(kind, source, target):
    """What to do about what is already at `target`: 'copy', 'same' (already there, identical) or 'replace' (an empty database); else Refused."""
    if not os.path.exists(target):
        return "copy"
    if kind == "folder":
        if os.path.isdir(target) and not _verify_folder(source, target):
            return "same"
        raise Refused(f"{target} already exists and is not the same as {source}; it is not overwritten")
    if kind == "file" and _sha(source) == _sha(target):
        return "same"
    if kind == "database":
        if database_is_empty(target):
            return "replace"
        if not _verify_database(source, target):  # a copy made earlier (the bytes of a backup differ from the original's; the rows and checks do not)
            return "same"
    raise Refused(f"{target} already exists and is not the same as {source}; it is not overwritten")


def _copy_database(source, target):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    old, new = _readonly(source), sqlite3.connect(target)
    try:
        old.backup(new)
    finally:
        new.close()
        old.close()


def _verify_database(source, target):
    """Problems with the copy of a database, as sentences; an empty list means it is a faithful copy."""
    problems = []
    old, new = _readonly(source), _readonly(target)
    try:
        if new.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            problems.append("SQLite's integrity check of the copy did not say ok")
        for table in _tables(old):
            a = old.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            try:
                b = new.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.DatabaseError:
                problems.append(f"table {table} is missing from the copy")
                continue
            if a != b:
                problems.append(f"table {table} has {b} rows in the copy and {a} in the original")
    finally:
        old.close()
        new.close()
    if not problems:
        import diya_db
        import diya_memory

        problems += [f"memory integrity: {problem}" for problem in diya_memory.Memory(diya_db.Store(target)).verify_integrity()]
    return problems


def _copy_folder(source, target):
    shutil.copytree(source, target)


def _verify_folder(source, target):
    wanted = sorted(os.path.relpath(os.path.join(root, name), source) for root, _, names in os.walk(source) for name in names)
    problems = []
    for relative in wanted:
        copy = os.path.join(target, relative)
        if not os.path.isfile(copy) or _sha(os.path.join(source, relative)) != _sha(copy):
            problems.append(f"{relative} is missing or different in the copy")
    return problems


def move(config, destination, with_certs=False, dry_run=False, allow_synced=False, out=print):
    """Copy the data to `destination` and verify it; returns an exit code. Nothing is written when anything is refused."""
    destination = os.path.abspath(destination)
    synced = synced_folder(destination)
    if synced and not allow_synced:
        raise Refused(f"{destination} is inside a {synced} folder, which is what this is meant to get away from; pass --allow-synced if you mean it")
    items = _items(config, destination, with_certs)
    if not items:
        out("There is nothing to move: none of Diya's data files exist where it looks for them.")
        return EXIT_OK
    actions = [(kind, source, target, _check_target(kind, source, target)) for kind, source, target in items]  # all refusals before any copy
    for kind, source, target, action in actions:
        out(f"{'would ' if dry_run else ''}{action:8} {os.path.basename(target) if kind != 'folder' else os.path.basename(target) + '/'}  ->  {target}")
    if dry_run:
        out("Dry run: nothing was copied.")
        return EXIT_OK

    failed = False
    for kind, source, target, action in actions:
        if action == "same":
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if kind == "database":
            _copy_database(source, target)
            problems = _verify_database(source, target)
        elif kind == "folder":
            _copy_folder(source, target)
            problems = _verify_folder(source, target)
        else:
            shutil.copy2(source, target)
            problems = [] if _sha(source) == _sha(target) else [f"{os.path.basename(target)} is not identical to the original"]
        size = "" if kind == "folder" else f" ({os.path.getsize(target)} bytes)"
        name = os.path.basename(target)
        if problems:
            failed = True
            out(f"CHECK FAILED for {name}{size}: " + "; ".join(problems))
        elif kind == "database":
            out(f"checked  {name}{size}: same rows in every table, integrity checks pass")
        else:
            out(f"checked  {name}{size}: identical to the original")
    if failed:
        out("At least one copy did not check out. The originals were not touched; do not apply any setting.")
        return EXIT_FAILED

    out("")
    out("Done: everything above was copied and checked, and nothing was changed or deleted where it was.")
    out("To use the copy, set these (PowerShell), then open a NEW terminal and restart the API; a scheduled task picks them up at its next run:")
    quoted = destination.replace("'", "''")
    out(f"    [Environment]::SetEnvironmentVariable('DIYA_DATA_DIR', '{quoted}', 'User')")
    if with_certs:
        for variable, source in zip(("DIYA_SSL_CERT", "DIYA_SSL_KEY"), diya_config.tls_files(config)):
            copy = os.path.join(destination, "certs", os.path.basename(source)).replace("'", "''")
            out(f"    [Environment]::SetEnvironmentVariable('{variable}', '{copy}', 'User')")
    out("The access token is unchanged (its hash was copied). To go back, remove those settings: the originals are still where they were.")
    out("Once you have used the copy for a while and are satisfied, the originals can be deleted by you; this program never does.")
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="diya_data.py", description="Move Diya's data out of the code folder (copies and checks; never deletes).")
    commands = parser.add_subparsers(dest="command", required=True)
    mover = commands.add_parser("move", help="copy the data to a folder and check the copy")
    mover.add_argument("--to", required=True, metavar="FOLDER", help="the folder to keep the data in (made if it does not exist)")
    mover.add_argument("--certs", action="store_true", help="copy the TLS certificate pair too, and print the settings for it")
    mover.add_argument("--dry-run", action="store_true", help="say what would be copied; copy nothing")
    mover.add_argument("--allow-synced", action="store_true", help="allow a folder that looks like a cloud-sync folder")
    return parser


def main(argv=None, config=None, out=print):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_REFUSED
    try:
        config = config or diya_config.load_config()
        return move(config, args.to, with_certs=args.certs, dry_run=args.dry_run, allow_synced=args.allow_synced, out=out)
    except (Refused, diya_config.ConfigError) as exc:
        out(f"Nothing was copied: {exc}.")
        return EXIT_REFUSED
    except OSError as exc:
        out(f"Stopped: {exc}. The originals were not touched.")
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
