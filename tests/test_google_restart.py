"""A crash or a restart can never make Google hold a second copy (DIYA-100), added 2026-10-26.

The danger is the moment between "the request reached Google" and "Diya wrote down that it did": if the program stops there, a naive retry on the next start would create the event, task, folder or document a second time.
What this proves, with the real approval system on a database file and Google replaced by a stand-in that counts its requests: when the process dies right after Google received the creating request (a crash, a power cut:
simulated by an exception that nothing in Diya catches), a fresh start with a new Actions object on the same file cannot run that action again, whether it is asked straight away, after reconcile has called it
unknown, or by several fresh starts in a row; Google was sent exactly one creating request for each of the four kinds; an action that finished stays finished through restarts; and an event's Google id is made from
its content, so even a second proposal of the same event after a restart reaches Google under the same id. It does not prove Google's own behaviour, and Google Tasks has no such id, which is why the unknown outcome is
shown to the owner to look in Google, never retried (docs/ACTIONS_DESIGN.md).
"""
import types
from datetime import timedelta

import httpx
import pytest

import diya_actions
import diya_google_write as gw
from diya_actions import Actions
from diya_db import Store
from test_google_write import EVENT, config, signed_in  # noqa: F401  (fixtures)


class ProcessDied(BaseException):
    """The process stopped: not an Exception, so nothing in Diya's own error handling can catch it, as with a crash."""


def reply(status=200, body=None):
    return types.SimpleNamespace(status_code=status, json=lambda: body if body is not None else {})


class Google:
    """Records every request. With `die_after_creating`, the first creating (POST) request is received and recorded and then the process dies before an answer is used."""

    def __init__(self, monkeypatch, die_after_creating=False):
        self.calls, self.die = [], die_after_creating
        monkeypatch.setattr(gw.httpx, "request", self)

    def __call__(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls.append((method, url))
        if method == "POST" and self.die:
            self.die = False
            raise ProcessDied()
        return reply(200, {})

    def creating(self):
        return [call for call in self.calls if call[0] == "POST"]


KINDS = [
    ("google_calendar_add_event", EVENT),
    ("google_tasks_add", {"title": "Renew pass"}),
    ("google_drive_make_folder", {"name": "Exams"}),
    ("google_docs_create", {"title": "Plan"}),
]


def fresh_start(config_):
    """A new process: nothing in memory, the same database file."""
    return Actions(Store(config_.db_path), config_, gw.action_kinds())


@pytest.mark.parametrize("kind, args", KINDS)
def test_a_process_that_dies_after_google_got_the_request_never_sends_it_again_however_often_it_restarts(kind, args, signed_in, monkeypatch):
    google = Google(monkeypatch, die_after_creating=True)
    before = fresh_start(signed_in)
    action = before.propose(kind, args)
    before.approve(action["id"], action["args_hash"], "ui")
    with pytest.raises(ProcessDied):
        before.run(action["id"])
    assert len(google.creating()) == 1  # Google got it once

    for restart in range(3):
        again = fresh_start(signed_in)
        assert again.get(action["id"])["status"] == ("executing" if restart < 2 else "unknown")  # what the database remembers: started and not finished, until reconcile (at the second restart) calls it unknown
        with pytest.raises(diya_actions.IllegalTransition):
            again.run(action["id"])
        if restart == 1:
            assert again.reconcile(older_than=timedelta(0)) == 1  # the owner is told the outcome is unknown, not "do it again"
            assert again.get(action["id"])["status"] == "unknown"
    final = fresh_start(signed_in)
    with pytest.raises(diya_actions.IllegalTransition):
        final.run(action["id"])
    assert len(google.creating()) == 1 and final.verify_integrity() == []


@pytest.mark.parametrize("kind, args", KINDS)
def test_an_action_that_finished_stays_finished_through_restarts(kind, args, signed_in, monkeypatch):
    google = Google(monkeypatch)
    first = fresh_start(signed_in)
    action = first.propose(kind, args)
    first.approve(action["id"], action["args_hash"], "ui")
    first.run(action["id"])  # the stand-in answers {}: the read-back does not confirm it, so the outcome is unknown, which is final enough here
    done = first.get(action["id"])["status"]
    assert done in ("succeeded", "unknown")
    sent = len(google.creating())
    for _ in range(3):
        later = fresh_start(signed_in)
        with pytest.raises(diya_actions.IllegalTransition):
            later.run(action["id"])
        assert later.get(action["id"])["status"] == done
    assert len(google.creating()) == sent == 1


def test_two_fresh_starts_racing_for_one_approved_action_send_it_once(signed_in, monkeypatch):
    google = Google(monkeypatch)
    one, two = fresh_start(signed_in), fresh_start(signed_in)
    action = one.propose("google_tasks_add", {"title": "Renew pass"})
    one.approve(action["id"], action["args_hash"], "ui")
    one.run(action["id"])
    with pytest.raises(diya_actions.IllegalTransition):
        two.run(action["id"])  # the other process, started earlier, still believes it can: the database says no
    assert len(google.creating()) == 1


def test_an_events_google_id_is_made_from_its_content_so_it_is_the_same_after_any_restart():
    assert gw.event_id(EVENT) == gw.event_id(dict(EVENT)) and gw.event_id(EVENT) != gw.event_id(dict(EVENT, title="Another"))
