"""A tidy-up of the Drive that shows its plan and how to undo it before anything is moved (diya_drive_tidy.py, Agent._tidy_drive; DIYA-143; docs/GOOGLE_CHANGES.md), added 2026-10-27.

What this proves: a file made by Diya at the top of the Drive whose name begins with, or says as a whole word, the name of a folder Diya made is planned to go into it (the longest folder name wins, and a tie is left alone);
the plan is shown whole as a manifest with the line that puts each file back; the first three moves (one message may lead to three actions) are proposed as ordinary moves, each approved on its own with from / to / how to
undo on its card; a file in a folder already, a file with no folder name in it and anything Diya did not make are left alone; and nothing is moved, renamed, binned or deleted before the approvals.
"""
import dataclasses

import pytest

import diya
import diya_actions
import diya_config
import diya_connectors
import diya_drive_tidy as tidy
import diya_google_calendar as gcal
import diya_google_client as client
import diya_google_drive as gd
from fakes import FakeClient
from test_google_drive import ROOT, Drive, file

CARDS = (gd.READ, gd.CHANGE)


@pytest.mark.parametrize("text, expected", [("tidy my drive", True), ("clean up my google drive", True), ("please organise my drive files", True), ("sort out my drive", True), ("what is in my drive", False), ("tidy my room", False), ("x" * 200, False)])
def test_a_plain_request_to_tidy_the_drive_is_understood(text, expected):
    assert tidy.request(text) is expected


def test_a_file_belongs_in_the_folder_whose_name_it_begins_with_or_says_and_a_tie_or_no_name_is_left_alone():
    folders = [{"name": "Exams"}, {"name": "Exams Physics"}, {"name": "Notes"}, {"name": "Notes"}]
    assert tidy.folder_for("Exams revision plan", folders)["name"] == "Exams"
    assert tidy.folder_for("exams physics - mock 1", folders)["name"] == "Exams Physics"  # the longest name wins
    assert tidy.folder_for("My exams plan", folders)["name"] == "Exams" and tidy.folder_for("Examsheet", folders) is None  # a whole word, not a piece of one
    assert tidy.folder_for("Notes for Monday", folders) is None  # two folders called Notes: not guessed
    assert tidy.folder_for("Budget", folders) is None


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, lookup=False)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    return config


@pytest.fixture
def drive(monkeypatch):
    service = Drive()
    service.files.pop("fileNotes0001")  # (the stand-in's other top-level files stay)
    monkeypatch.setattr(gcal, "access_token", lambda config, name: name if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


def chat(config):
    return diya.Agent(config, client=FakeClient([]), action_kinds=list(gd.action_kinds()))


def add_exam_files(drive, count):
    for n in range(count):
        drive.add(file(f"fileExamsPlan{n:02d}", f"Exams revision plan {n}", "text/plain"))


def test_the_plan_is_a_manifest_with_the_line_that_puts_each_file_back(config, drive):
    add_exam_files(drive, 2)
    moves, lines = tidy.plan(config)
    assert [m["name"] for m in moves] == ["Exams revision plan 0", "Exams revision plan 1"] and all(m["from_id"] == ROOT and m["to_id"] == "folderExams1" for m in moves)
    assert lines[0].startswith("A tidy-up of the files Diya made at the top of your Drive, by the names of the folders Diya made (2 move(s)):")
    assert "- 'Exams revision plan 0': from the top of My Drive into 'Exams'   (to put it back: move 'Exams revision plan 0' into My Drive)" in lines


def test_a_file_already_in_a_folder_a_file_with_no_folder_name_and_a_file_diya_did_not_make_are_left_alone(config, drive):
    drive.add(file("fileInside0001", "Exams old", "text/plain", parent="folderExams1"))
    drive.add(file("fileBudget0001", "Budget 2026", "text/plain"))
    drive.add(file("fileTheirs0001", "Exams from Sam", "text/plain", mine=False))
    moves, lines = tidy.plan(config)
    assert moves == [] and lines[0].startswith("Nothing to tidy: none of the ")


def test_the_chat_shows_the_plan_and_proposes_the_first_three_moves_and_moves_nothing(config, drive):
    add_exam_files(drive, 5)
    agent = chat(config)
    answer, tools = agent.ask([{"role": "user", "content": "tidy my drive"}])
    actions = agent.actions.actions()
    assert tools == ["read_drive", "propose_move_drive_file"] and agent.client.chat_calls == []
    assert answer.startswith("A tidy-up of the files Diya made at the top of your Drive") and "(5 move(s))" in answer and "3 of the 5 move(s) are proposed for you to approve one by one; ask again for the rest. Nothing is moved until you do." in answer
    assert len(actions) == diya_actions.MAX_PER_TURN == 3 and all(a["status"] == "pending" and a["kind"] == "google_drive_move" and a["tainted"] for a in actions) and drive.mutations() == []
    assert actions[0]["summary"] == "Move the Drive file 'Exams revision plan 0' from 'the top of My Drive' into 'Exams' (undo: move it back into 'the top of My Drive')"


def test_each_proposed_move_is_approved_on_its_own_and_only_that_file_moves(config, drive):
    add_exam_files(drive, 2)
    agent = chat(config)
    agent.ask([{"role": "user", "content": "tidy my drive"}])
    first, second = agent.actions.pending()
    agent.actions.approve(first["id"], first["args_hash"], "ui")
    assert agent.actions.run(first["id"])["status"] == "succeeded"
    assert drive.files["fileExamsPlan00"]["parents"] == ["folderExams1"] and drive.files["fileExamsPlan01"]["parents"] == [ROOT]
    assert len([r for r in drive.mutations() if r[0] == "PATCH"]) == 1


def test_a_file_that_changed_since_the_plan_is_not_moved_when_its_turn_comes(config, drive):
    add_exam_files(drive, 1)
    agent = chat(config)
    agent.ask([{"role": "user", "content": "tidy my drive"}])
    (action,) = agent.actions.pending()
    drive.files["fileExamsPlan00"]["version"] = "9"
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    done = agent.actions.run(action["id"])
    assert done["status"] == "failed" and drive.files["fileExamsPlan00"]["parents"] == [ROOT]


def test_without_the_drive_change_card_it_says_so_and_asks_nothing_of_google(config, drive):
    diya_connectors.disconnect(config, gd.CHANGE)
    agent = chat(config)
    answer, _ = agent.ask([{"role": "user", "content": "tidy my drive"}])
    assert "Google Drive (change) is not connected" in answer and drive.requests == [] and agent.actions.actions() == []


def test_nothing_is_ever_binned_renamed_or_deleted_by_a_tidy_up(config, drive):
    add_exam_files(drive, 3)
    agent = chat(config)
    agent.ask([{"role": "user", "content": "tidy my drive"}])
    for action in agent.actions.pending():
        agent.actions.approve(action["id"], action["args_hash"], "ui")
        agent.actions.run(action["id"])
    assert not [r for r in drive.requests if r[0] == "DELETE"] and all(r[3] in ({}, None) or set(r[3]) <= set() for r in drive.mutations())  # only moves: no name, no trashed flag in any body
    assert all(not f["trashed"] for f in drive.files.values())
