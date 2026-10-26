"""A sequence of steps that is undone, step by step, when a later one fails (DIYA-139; docs/GOOGLE_CHANGES.md), added 2026-10-27.

Several approved actions that belong together ("write the plan in a Doc, put the Doc in the Exams folder, draft an email to Sam with its link") leave a mess when the third fails: a Doc in the wrong place and no email. A saga
runs the steps in order and, when one FAILS CLEANLY (it knows nothing happened for that step), undoes the steps that already happened, newest first, each by the undo it declared. Rules, all pinned by tests/test_saga.py:

* **A step that failed cleanly** (ActionFailed) ends the run and undoes the earlier steps that declared an undo; a step with no undo is left as it is and is named ("not undone: ...") so that the person knows.
* **A step whose outcome is not known** (ActionUncertain: the request went out and nothing came back) STOPS the run and undoes NOTHING: the step may have taken effect, and undoing the ones before it on a guess could make a
  second mess. The report says which steps are done, which one is not known, and which never ran, for the person to look and decide.
* **An undo that fails** is recorded ("undo failed") and the other undos still run; nothing is retried, ever.
* **Nothing hidden:** every step ends in one state and the report says each in words, in the order of the steps.

This module knows nothing about Google and makes no request: it only calls the functions it is given. The steps of a real plan are the `*_execute` functions of approved actions, so a saga runs only inside a plan the owner approved as
a whole (a kind of action for that is a decision for the owner: approving several steps at once is a different gate from approving each, and none is registered). Importing this module has no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from diya_actions import ActionFailed, ActionUncertain

DONE, FAILED, UNKNOWN, UNDONE, UNDO_FAILED, NOT_UNDONE, NOT_RUN = "done", "failed", "unknown", "undone", "undo failed", "not undone", "not run"


@dataclass(frozen=True)
class Step:
    """One step: `do(context)` makes it happen and returns what it made (words or a value `undo` needs); `undo(context, made)` puts it back and returns words, or is None for a step that cannot be undone."""

    name: str
    do: object
    undo: object = None


@dataclass
class Outcome:
    status: str  # "done" (all steps), "rolled back" (a step failed cleanly and the earlier ones were undone), "partly done" (a step failed and some earlier step could not be undone or its undo failed), "stopped" (a step's outcome is not known)
    steps: list = field(default_factory=list)  # [(name, state, words)] in the order of the steps

    def says(self):
        """The report as plain lines."""
        head = {"done": "All steps were done.", "rolled back": "A step failed, and the steps before it were undone.", "partly done": "A step failed, and some earlier steps could not be undone: see below.",
                "stopped": "A step's outcome is not known, so nothing was undone and nothing more was done: look in the service, then decide."}[self.status]
        return "\n".join([head] + [f"- {name}: {state}" + (f" ({words})" if words else "") for name, state, words in self.steps])


def run(steps, context=None):
    """Run `steps` (a list of Step) in order with the shared `context`, and return the Outcome. Never raises for a step that fails: it is the report."""
    records = [[step.name, NOT_RUN, ""] for step in steps]
    made = {}
    for index, step in enumerate(steps):
        try:
            made[index] = step.do(context)
        except ActionFailed as exc:
            records[index][1:] = [FAILED, str(exc)]
            return _roll_back(steps, records, made, index, context)
        except ActionUncertain as exc:
            records[index][1:] = [UNKNOWN, str(exc)]
            return Outcome("stopped", [tuple(r) for r in records])
        records[index][1:] = [DONE, str(made[index]) if isinstance(made[index], str) else ""]
    return Outcome("done", [tuple(r) for r in records])


def _roll_back(steps, records, made, failed_at, context):
    clean = True
    for index in range(failed_at - 1, -1, -1):
        step = steps[index]
        if step.undo is None:
            records[index][1:] = [NOT_UNDONE, "this step cannot be undone, so it is left as it is"]
            clean = False
            continue
        try:
            records[index][1:] = [UNDONE, str(step.undo(context, made.get(index)) or "")]
        except (ActionFailed, ActionUncertain, Exception) as exc:  # noqa: BLE001 -- an undo that goes wrong is a line in the report, and the other undos still run
            records[index][1:] = [UNDO_FAILED, f"{type(exc).__name__}: {exc}"[:200]]
            clean = False
    return Outcome("rolled back" if clean else "partly done", [tuple(r) for r in records])
