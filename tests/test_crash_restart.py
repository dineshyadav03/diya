"""A process killed in the middle of a write does not corrupt the database, and a restart does not repeat a write nobody can vouch for (task DIYA-013; docs/BACKUP_DESIGN.md, docs/ACTIONS_DESIGN.md), added 2026-10-20.

What this proves, with real operating-system processes that are KILLED (not asked to stop), the nearest a test gets to a power cut: (1) a process saving the person's messages one after another is killed while it
is doing so; the database opens afterwards, passes SQLite's integrity check and Diya's own (memory trail, actions), and every message that was saved has its reading job and no job exists without its message
(the two are written in one transaction); (2) a process running an approved action, killed after the outside effect had started, leaves the action `executing`; a restart turns it into `unknown`, it is
never run again whatever is asked, and the effect happened exactly once; (3) the same restart leaves a younger run alone, so a second process cannot cancel a live one. It does not test a real power cut (the
operating system's write cache is not in play) or a disk that lies.
"""
import dataclasses
import os
import pathlib
import subprocess
import sys
import textwrap
import time
from datetime import timedelta

import pytest

import diya_actions
import diya_config
import diya_connectors
import diya_db
from diya_memory import Memory

ROOT = pathlib.Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

WRITER = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, sys.argv[2])
    from diya_db import Store
    store = Store(sys.argv[1])
    thread = store.main_thread()
    n = 0
    while True:
        store.add_message(thread, "user", f"message number {n} for the crash test", capture=True)
        n += 1
        print(n, flush=True)
    """
)

ACTOR = textwrap.dedent(
    """
    import dataclasses, sys, time
    sys.path.insert(0, sys.argv[5])
    import diya_config, diya_connectors
    from diya_actions import ActionKind, Actions
    from diya_db import Store

    config = dataclasses.replace(diya_config.load_config({}), db_path=sys.argv[1], connector_tokens_dir=sys.argv[2], connectors_log_path=sys.argv[3], protect_secrets=False)
    diya_connectors.store_token(config, "fakeservice", "not-a-real-token")
    marker = sys.argv[4]

    def execute(config, args):
        with open(marker, "a") as handle:
            handle.write("effect started\\n")  # the outside world was touched
        time.sleep(120)  # ... and the process is killed before it can say how it went
        return "never reached"

    kind = ActionKind(name="add_task", label="Add a task", connector="fakeservice", validate=lambda a: None, render=lambda a: "Add a task", execute=execute)
    actions = Actions(Store(config.db_path), config, (kind,))
    action = actions.propose("add_task", {"title": "buy milk"})
    actions.approve(action["id"], action["args_hash"], "ui")
    print("running", action["id"], flush=True)
    actions.run(action["id"])
    """
)


def start(script, *args):
    return subprocess.Popen([sys.executable, "-c", script, *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(ROOT))


def read_until(process, predicate, seconds=30):
    deadline = time.monotonic() + seconds
    lines = []
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        lines.append(line.strip())
        if predicate(lines):
            return lines
    pytest.fail(f"the process did not get there: {lines[-3:]}; stderr: {process.stderr.read()[-300:] if process.poll() is not None else ''}")


def count(path, query):
    import sqlite3

    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchone()[0]
    finally:
        conn.close()


def test_a_writer_killed_mid_stream_leaves_a_sound_database_and_every_message_with_its_reading_job(tmp_path):
    db = str(tmp_path / "crash.db")
    process = start(WRITER, db, ROOT)
    try:
        read_until(process, lambda lines: len(lines) >= 40)
    finally:
        process.kill()
        process.wait(timeout=20)
    store = diya_db.Store(db)  # a restart: opens the same file
    assert count(db, "PRAGMA integrity_check") == "ok"
    assert Memory(store).verify_integrity() == []
    messages = count(db, "SELECT COUNT(*) FROM messages WHERE role = 'user'")
    jobs = count(db, "SELECT COUNT(*) FROM capture_queue")
    assert messages >= 40
    assert jobs == messages  # one job per message: never a message without its reading, never a reading without its message
    assert count(db, "SELECT COUNT(*) FROM messages m WHERE m.role = 'user' AND NOT EXISTS (SELECT 1 FROM capture_queue q WHERE q.message_id = m.id)") == 0
    assert count(db, "SELECT COUNT(*) FROM capture_queue q WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.id = q.message_id)") == 0
    store.add_message(store.main_thread(), "user", "and the restarted program can write again", capture=True)  # and writing goes on


def test_an_action_killed_after_its_effect_began_becomes_unknown_and_is_never_run_again(tmp_path):
    db, tokens, log, marker = str(tmp_path / "a.db"), str(tmp_path / "tok"), str(tmp_path / "log"), tmp_path / "marker.txt"
    process = start(ACTOR, db, tokens, log, marker, TESTS)
    try:
        read_until(process, lambda lines: any(line.startswith("running") for line in lines))
        deadline = time.monotonic() + 30
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.exists(), "the effect never started"
    finally:
        process.kill()
        process.wait(timeout=20)
    config = dataclasses.replace(diya_config.load_config({}), db_path=db, connector_tokens_dir=tokens, connectors_log_path=log, protect_secrets=False)
    diya_connectors.store_token(config, "fakeservice", "not-a-real-token")
    again = {"calls": 0}

    def execute(config, args):
        again["calls"] += 1
        return "second time"

    kind = diya_actions.ActionKind(name="add_task", label="Add a task", connector="fakeservice", validate=lambda a: None, render=lambda a: "Add a task", execute=execute)
    actions = diya_actions.Actions(diya_db.Store(db), config, (kind,))
    (stuck,) = actions.actions()
    assert stuck["status"] == "executing"  # the outcome was never written
    assert actions.reconcile() == 0  # a run only a moment old may still be in flight (in another process): left alone
    assert actions.reconcile(older_than=timedelta(0)) == 1  # the program that was running it is gone
    assert actions.get(stuck["id"])["status"] == "unknown"
    with pytest.raises(diya_actions.IllegalTransition):
        actions.run(stuck["id"])
    assert again["calls"] == 0 and marker.read_text().count("effect started") == 1  # the outside effect happened once and was never repeated
    assert actions.verify_integrity() == []
