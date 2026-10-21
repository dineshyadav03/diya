"""One separate process for tests/test_actions_multi_process.py: it opens the same database as its brothers and tries to propose, approve or run an action, then prints what happened as one line of JSON.

    python tests/_action_worker.py MODE DB EFFECT_FILE START_AT [ACTION_ID]

MODE is propose (prints the id it made or the refusal), run (runs the action; the effect appends this process's id to EFFECT_FILE, holds the lease for HOLD seconds), or die (the same, but the process
stops dead in the middle of the effect, as a crash or a power cut would). START_AT is a clock time all the brothers wait for, so that they really do collide. It is not a test (its name does not start
with test_) and it changes nothing outside the files it is given.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import diya_actions  # noqa: E402
import diya_config  # noqa: E402
from diya_db import Store  # noqa: E402

HOLD = 0.6


def validate(args):
    if not isinstance(args.get("title"), str):
        raise diya_actions.InvalidArgs("a task needs a title")


def render(args):
    return f"Add the task {args['title']!r}"


def build(mode, effect_file):
    def execute(config, args):
        with open(effect_file, "a", encoding="utf-8") as out:
            out.write(f"{os.getpid()}\n")
        if mode == "die":
            os._exit(3)  # no outcome is written, nothing is cleaned up
        time.sleep(HOLD)
        return "done"

    return diya_actions.ActionKind("add_task", "Add a task", None, validate, render, execute)


def main():
    mode, db, effect_file, start_at = sys.argv[1:5]
    action_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
    actions = diya_actions.Actions(Store(db), diya_config.load_config({}), (build(mode, effect_file),))
    while time.time() < float(start_at):
        time.sleep(0.005)
    try:
        if mode == "propose":
            result = {"ok": True, "id": actions.propose("add_task", {"title": "buy milk"})["id"]}
        else:
            result = {"ok": True, "status": actions.run(action_id)["status"]}
    except diya_actions.ActionError as exc:
        result = {"ok": False, "error": type(exc).__name__}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
