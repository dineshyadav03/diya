"""A sequence of steps undone, newest first, when a later one fails (diya_saga.py; DIYA-139; docs/GOOGLE_CHANGES.md), added 2026-10-27.

What this proves, first with plain steps and then with the example the task names, Docs -> Drive -> Gmail (write the plan in a Doc, put the Doc in the Exams folder, draft an email with its link) against stand-in services:
a step that fails cleanly undoes the earlier steps, newest first, by the undo each declared; a step with no undo is named and left; an undo that fails is recorded and the others still run; a step whose outcome is NOT known stops the
run and undoes nothing (it may have happened); nothing is retried; every step ends in one named state; and, for the example, the failure is injected at each of the three points and the state left behind is the one the report says.
"""
import dataclasses
import re
import types

import pytest

import diya_actions
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_client as client
import diya_google_drive as gd
import diya_google_mailwrite as mw
import diya_google_write as gw
import diya_saga as saga
from diya_actions import ActionFailed, ActionUncertain
from test_google_drive import ROOT, Drive, file
from test_google_mailwrite import Gmail


def step(name, log, fail=None, undo_fail=False, undoable=True):
    def do(context):
        log.append(("do", name))
        if fail == "clean":
            raise ActionFailed(f"{name} was refused")
        if fail == "unknown":
            raise ActionUncertain(f"{name} may or may not have happened")
        return f"{name} made"

    def undo(context, made):
        log.append(("undo", name, made))
        if undo_fail:
            raise ActionFailed(f"{name} could not be put back")
        return f"{name} put back"

    return saga.Step(name, do, undo if undoable else None)


def test_all_steps_done_in_order_and_nothing_is_undone():
    log = []
    outcome = saga.run([step("a", log), step("b", log), step("c", log)])
    assert outcome.status == "done" and log == [("do", "a"), ("do", "b"), ("do", "c")] and [s[1] for s in outcome.steps] == ["done"] * 3


def test_a_clean_failure_undoes_the_earlier_steps_newest_first_with_what_each_made():
    log = []
    outcome = saga.run([step("a", log), step("b", log), step("c", log, fail="clean"), step("d", log)])
    assert outcome.status == "rolled back" and log == [("do", "a"), ("do", "b"), ("do", "c"), ("undo", "b", "b made"), ("undo", "a", "a made")]
    assert [s[1] for s in outcome.steps] == ["undone", "undone", "failed", "not run"] and "c was refused" in outcome.says()


def test_a_step_that_cannot_be_undone_is_named_and_left_and_the_report_says_partly_done():
    log = []
    outcome = saga.run([step("a", log), step("b", log, undoable=False), step("c", log, fail="clean")])
    assert outcome.status == "partly done" and [s[1] for s in outcome.steps] == ["undone", "not undone", "failed"] and "cannot be undone, so it is left as it is" in outcome.says()


def test_an_undo_that_fails_is_recorded_and_the_other_undos_still_run():
    log = []
    outcome = saga.run([step("a", log), step("b", log, undo_fail=True), step("c", log, fail="clean")])
    assert [s[1] for s in outcome.steps] == ["undone", "undo failed", "failed"] and outcome.status == "partly done" and ("undo", "a", "a made") in log


def test_a_step_whose_outcome_is_not_known_stops_the_run_and_undoes_nothing():
    log = []
    outcome = saga.run([step("a", log), step("b", log, fail="unknown"), step("c", log)])
    assert outcome.status == "stopped" and log == [("do", "a"), ("do", "b")] and [s[1] for s in outcome.steps] == ["done", "unknown", "not run"]
    assert "nothing was undone" in outcome.says() and "may or may not have happened" in outcome.says()


def test_nothing_is_ever_retried_and_the_first_step_failing_has_nothing_to_undo():
    log = []
    outcome = saga.run([step("a", log, fail="clean"), step("b", log)])
    assert log == [("do", "a")] and outcome.status == "rolled back" and [s[1] for s in outcome.steps] == ["failed", "not run"]


def test_the_module_makes_no_request_and_knows_nothing_of_google():
    import inspect

    source = inspect.getsource(saga)
    assert "httpx" not in source and "diya_google" not in source and "client.send" not in source


# ---- the example: Docs -> Drive -> Gmail, with the failure injected at each point ---------------------------------------------------------------------

CARDS = (gd.READ, gd.CHANGE, mw.DRAFTS, "google_drive_files")


class World:
    """The Drive stand-in and the Gmail stand-in behind one door, with a failure that can be switched on for a request (after some that work)."""

    def __init__(self):
        self.office, self.gmail, self.rules, self.seen = Drive(), Gmail(), {}, {}

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        haystack = f"{url} {kwargs.get('params')} {kwargs.get('json')}"
        for (m, fragment), (allow, status) in self.rules.items():
            if method == m and fragment in haystack:
                self.seen[(m, fragment)] = self.seen.get((m, fragment), 0) + 1
                if self.seen[(m, fragment)] > allow:
                    return types.SimpleNamespace(status_code=status, headers={}, json=lambda: {"error": {"message": "refused"}}, text="")
        if method == "POST" and url == gw.DOCS_API:  # making a Doc (the stand-in Drive has no such request yet)
            self.office.next += 1
            doc_id = f"docMade{self.office.next:05d}"
            body = kwargs.get("json")
            self.office.add(file(doc_id, body["title"], gd.DOC))
            self.office.docs[doc_id] = {"documentId": doc_id, "title": body["title"], "revisionId": "rev-1", "text": ""}
            return types.SimpleNamespace(status_code=200, headers={}, json=lambda: {"documentId": doc_id, "title": body["title"]}, text="")
        if url.startswith(gw.DOCS_API) and url.endswith(":batchUpdate") and "insertText" in str(kwargs.get("json")):
            doc = self.office.docs[url.split("/")[-1].split(":")[0]]
            doc["text"] += kwargs["json"]["requests"][0]["insertText"]["text"]
            return types.SimpleNamespace(status_code=200, headers={}, json=lambda: {}, text="")
        return (self.gmail if url.startswith(mw.GMAIL) else self.office)(*args, **kwargs)


@pytest.fixture
def world(monkeypatch, tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    service = World()
    monkeypatch.setattr(gcal, "access_token", lambda config_, name: name if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return config, service


def plan(config, state):
    """The three steps, each the `*_execute` of an approved action and each with the undo that puts it back."""
    def make_doc(_):
        done = gw.doc_execute(config, {"title": "Exam plan", "body": "Week 1 maths"})
        state["doc_id"] = re.search(r"/d/([A-Za-z0-9_-]+)/edit", done).group(1)
        return done

    def bin_doc(_, made):
        return gd.trash_execute(config, {"name": "Exam plan", "file_id": state["doc_id"], "version": "", "kind": "file"})

    def move_doc(_):
        return gd.move_execute(config, {"name": "Exam plan", "file_id": state["doc_id"], "version": "", "from_id": ROOT, "from_name": "the top of My Drive", "to_id": "folderExams1", "to_name": "Exams"})

    def move_back(_, made):
        return gd.move_execute(config, {"name": "Exam plan", "file_id": state["doc_id"], "version": "", "from_id": "folderExams1", "from_name": "Exams", "to_id": ROOT, "to_name": "the top of My Drive"})

    def draft(_):
        return mw.draft_execute(config, {"subject": "Exam plan", "body": f"The plan is here: https://docs.google.com/document/d/{state['doc_id']}/edit"})

    def discard(_, made):
        draft_id, subject, to = mw._find_draft(config, "Exam plan")
        return mw.discard_execute(config, {"subject": subject, "draft_id": draft_id, "to_shown": to or "no recipient yet"})

    return [saga.Step("Write the plan in a Doc", make_doc, bin_doc), saga.Step("Put the Doc in the Exams folder", move_doc, move_back), saga.Step("Draft the email with the link", draft, discard)]


def doc_state(service, state):
    f = service.office.files[state["doc_id"]]
    return f["parents"], f["trashed"]


def test_every_step_works_and_the_doc_is_in_the_folder_with_a_draft_that_has_its_link(world):
    config, service = world
    state = {}
    outcome = saga.run(plan(config, state))
    assert outcome.status == "done" and doc_state(service, state) == (["folderExams1"], False) and len(service.gmail.drafts) == 1


def test_the_first_step_failing_leaves_nothing_behind(world):
    config, service = world
    service.rules[("POST", gw.DOCS_API)] = (0, 400)
    outcome = saga.run(plan(config, {}))
    assert outcome.status == "rolled back" and [s[1] for s in outcome.steps] == ["failed", "not run", "not run"] and not [f for f in service.office.files if f.startswith("docMade")] and service.gmail.drafts == {}


def test_the_second_step_failing_bins_the_doc_that_was_made(world):
    config, service = world
    state = {}
    service.rules[("PATCH", "addParents")] = (0, 400)  # the move is refused (the bin, which is also a change to the file, is not)
    outcome = saga.run(plan(config, state))
    assert outcome.status == "rolled back" and [s[1] for s in outcome.steps] == ["undone", "failed", "not run"]
    assert doc_state(service, state) == ([ROOT], True) and service.gmail.drafts == {}  # the Doc made in step one is in the bin; no email was drafted


def test_the_third_step_failing_puts_the_doc_back_and_bins_it(world):
    config, service = world
    state = {}
    service.rules[("POST", "/drafts")] = (0, 400)
    outcome = saga.run(plan(config, state))
    assert outcome.status == "rolled back" and [s[1] for s in outcome.steps] == ["undone", "undone", "failed"]
    assert doc_state(service, state) == ([ROOT], True) and service.gmail.drafts == {}  # moved back to where it was made, then in the bin: as if the plan had never been tried, except that the bin keeps it for 30 days


def test_the_third_step_with_an_unknown_outcome_stops_and_undoes_nothing(world):
    config, service = world
    state = {}
    service.rules[("POST", "/drafts")] = (0, 500)
    outcome = saga.run(plan(config, state))
    assert outcome.status == "stopped" and [s[1] for s in outcome.steps] == ["done", "done", "unknown"]
    assert doc_state(service, state) == (["folderExams1"], False)  # the doc is where step two put it; nobody undid it on a guess
    assert "may or may not have been done" in outcome.says()


def test_a_failing_undo_is_said_and_the_other_undos_still_run(world):
    config, service = world
    state = {}
    service.rules[("POST", "/drafts")] = (0, 400)  # step three is refused
    service.rules[("PATCH", "addParents")] = (1, 400)  # the move worked once, so moving back is refused
    outcome = saga.run(plan(config, state))
    assert [s[1] for s in outcome.steps] == ["undone", "undo failed", "failed"] and outcome.status == "partly done"
    assert doc_state(service, state) == (["folderExams1"], True)  # still in the folder (the undo failed, and says so), and the earlier undo still ran: the Doc is in the bin
    assert "undo failed" in outcome.says() and "ActionFailed" in outcome.says()
