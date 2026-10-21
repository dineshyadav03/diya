"""An approved action is done once, whichever session, device or process tries (diya_actions.Actions; docs/ACTIONS_DESIGN.md; task DIYA-058), added 2026-10-21.

What this proves, with separate operating-system processes (not threads) sharing one database file, as two browser tabs, the command line and a phone would: six processes asking to run the same approved
action at the same instant perform its effect exactly once (one "succeeded", five refused, one effect line, one "executing" and one "succeeded" in its history); six processes proposing the same action at the
same instant leave exactly one waiting; a process that dies in the middle of the effect leaves the action "executing", and no process, when asked again, performs it a second time: after the time
limit it is "unknown", and the effect line count is still one. The two mechanisms are the stable key (the hash of the kind and the arguments: one exact action waits at most once) and the lease (the move to
"executing" is committed before the effect starts, inside a transaction that only one process can win). It does not prove a remote service sees one request: Diya never retries, so it sends no
idempotency key, and an action whose outcome is unknown is shown to the person as unknown rather than tried again.
"""
import json
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest

import diya_actions
import diya_config
from diya_db import Store

WORKER = Path(__file__).resolve().parent / "_action_worker.py"
PROCESSES = 6
KIND = diya_actions.ActionKind(
    "add_task", "Add a task", None,
    lambda args: None if isinstance(args.get("title"), str) else (_ for _ in ()).throw(diya_actions.InvalidArgs("a task needs a title")),
    lambda args: f"Add the task {args['title']!r}", lambda config, args: "done",
)


@pytest.fixture
def world(tmp_path):
    db = tmp_path / "shared.db"
    store = Store(str(db))
    return db, tmp_path / "effects.txt", store, diya_actions.Actions(store, diya_config.load_config({}), (KIND,))


def start_workers(mode, db, effect, action_id=None, count=PROCESSES):
    start_at = time.time() + 2.5  # long enough for every interpreter to start and import, so they collide
    args = [sys.executable, str(WORKER), mode, str(db), str(effect), str(start_at)] + ([str(action_id)] if action_id is not None else [])
    return [subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(count)]


def finish(workers):
    found = []
    for worker in workers:
        out, err = worker.communicate(timeout=60)
        found.append((worker.returncode, out.strip(), err.strip()))
    return found


def effect_lines(path):
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_six_processes_running_the_same_approved_action_at_once_perform_it_once(world):
    db, effect, store, actions = world
    action = actions.propose("add_task", {"title": "buy milk"})
    actions.approve(action["id"], action["args_hash"], "ui")
    results = finish(start_workers("run", db, effect, action["id"]))
    assert all(code == 0 for code, _out, err in results), results
    answers = [json.loads(out) for _code, out, _err in results]
    assert sorted((a["ok"], a.get("status") or a["error"]) for a in answers) == [(False, "IllegalTransition")] * (PROCESSES - 1) + [(True, "succeeded")]
    assert len(effect_lines(effect)) == 1
    assert [e[0] for e in actions.events(action["id"])] == ["proposed", "approved", "executing", "succeeded"]
    assert actions.get(action["id"])["status"] == "succeeded" and actions.verify_integrity() == []


def test_six_processes_proposing_the_same_action_at_once_leave_one_waiting(world):
    db, effect, store, actions = world
    answers = [json.loads(out) for code, out, err in finish(start_workers("propose", db, effect)) if code == 0]
    assert len(answers) == PROCESSES
    assert sorted((a["ok"], a.get("error")) for a in answers) == [(False, "DuplicatePending")] * (PROCESSES - 1) + [(True, None)]
    assert len(actions.pending()) == 1


def test_a_process_that_dies_in_the_middle_leaves_the_action_unrunnable_and_it_is_never_run_again(world):
    db, effect, store, actions = world
    action = actions.propose("add_task", {"title": "buy milk"})
    actions.approve(action["id"], action["args_hash"], "ui")
    (code, out, err), = finish(start_workers("die", db, effect, action["id"], count=1))
    assert code == 3 and out == ""  # it stopped dead: no outcome was written
    assert actions.get(action["id"])["status"] == "executing" and len(effect_lines(effect)) == 1
    # another session asks to run it again, on the same database: refused, and the effect is not repeated
    results = finish(start_workers("run", db, effect, action["id"], count=3))
    assert [json.loads(out)["error"] for _c, out, _e in results] == ["IllegalTransition"] * 3
    assert len(effect_lines(effect)) == 1
    # after the time limit it is called unknown (the owner is told it may or may not have happened), still not run again
    assert actions.reconcile(older_than=timedelta(0)) == 1
    assert actions.get(action["id"])["status"] == "unknown"
    finish(start_workers("run", db, effect, action["id"], count=2))
    assert len(effect_lines(effect)) == 1 and actions.get(action["id"])["status"] == "unknown"
