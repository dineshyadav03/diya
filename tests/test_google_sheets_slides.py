"""Google Sheets and Slides on what Diya made (diya_google_sheets.py, diya_google_slides.py; DIYA-101 to -109; docs/GOOGLE_CHANGES.md), added 2026-10-26.

No test here reaches the real Google: a stateful stand-in (the Drive of tests/test_google_drive.py plus a Sheets and a Slides service) answers, keeps every request and applies what it is sent. What this proves: the Drive
(change) card may make and write sheets and decks and nothing else; no value can become a formula (everything is written as plain text and a value that starts with = + - or @ and is not a plain number is kept as text, with
the count on the card); rows are added after the last row the card said; cells that are filled are replaced only when the person said replace or overwrite, and only if they still hold what the card showed; the header
is bolded and frozen and read back; a deck is made from an outline shown whole and the slide count and every title are read back; a sheet or deck Diya did not make cannot be found; and none of it can be done straight away.
"""
import dataclasses
import json
import re

import pytest

import diya
import diya_actions
import diya_autoapprove
import diya_catalog
import diya_config
import diya_connectors
import diya_google_calendar as gcal
import diya_google_client as client
import diya_google_drive as gd
import diya_google_sheets as gs
import diya_google_slides as gl
import diya_intent_google as asks
from fakes import FakeClient, text_reply, tool_reply
from test_google_drive import Drive, file, resp

CARDS = (gd.READ, gd.CHANGE)


def cell_index(ref):
    letters, digits = re.fullmatch(r"([A-Z]+)([0-9]+)", ref).groups()
    col = 0
    for ch in letters:
        col = col * 26 + ord(ch) - 64
    return int(digits) - 1, col - 1


class Office(Drive):
    """The Drive stand-in with a Sheets service (values by cell, a frozen row) and a Slides service (slides with a title and a body) added."""

    def __init__(self):
        super().__init__()
        self.sheets, self.decks = {}, {}
        self.add(file("sheetBudget001", "Budget", gd.SHEET))
        self.sheets["sheetBudget001"] = {"title": "Budget", "cells": {(0, 0): "item", (0, 1): "cost", (1, 0): "books", (1, 1): "40"}, "frozen": 0}
        self.add(file("deckExams00001", "Exams deck", gd.SLIDES))
        self.decks["deckExams00001"] = {"title": "Exams deck", "slides": [{"id": "p1", "title": "Exams deck", "body": ""}, {"id": "p2", "title": "Plan", "body": "week 1"}]}
        self.add(file("sheetOthers001", "Others sheet", gd.SHEET, mine=False))

    def touch(self, fid):
        self.files[fid]["version"] = str(int(self.files[fid]["version"]) + 1)

    def rows(self, sheet, a, b):
        (r1, c1), (r2, c2) = cell_index(a), cell_index(b)
        out = [[sheet["cells"].get((r, c), "") for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)]
        for row in out:
            while row and row[-1] == "":
                row.pop()
        while out and not out[-1]:
            out.pop()
        return out

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        params, body = kwargs.get("params") or {}, kwargs.get("json")
        if url.startswith(gs.SHEETS):
            self.requests.append((method, url, dict(params), body, (kwargs.get("headers") or {}).get("Authorization", "")))
            return self.sheets_call(method, url, params, body)
        if url.startswith(gl.SLIDES):
            self.requests.append((method, url, dict(params), body, (kwargs.get("headers") or {}).get("Authorization", "")))
            return self.slides_call(method, url, body)
        return super().__call__(*args, **kwargs)

    def sheets_call(self, method, url, params, body):
        if method in self.fail_status:
            return resp(self.fail_status[method], {"error": {"message": "backend error"}})
        tail = url[len(gs.SHEETS):].strip("/")
        if not tail:
            self.next += 1
            sid = f"sheetMade{self.next:05d}"
            self.sheets[sid] = {"title": body["properties"]["title"], "cells": {}, "frozen": 0}
            self.add(file(sid, body["properties"]["title"], gd.SHEET))
            return resp(200, {"spreadsheetId": sid, "properties": {"title": body["properties"]["title"]}})
        sid = tail.split("/")[0].split(":")[0]
        sheet = self.sheets.get(sid)
        if sheet is None or not self.files[sid]["mine"]:
            return resp(404, {"error": {"message": "not found"}})
        if tail.endswith(":batchUpdate"):
            for request in body["requests"]:
                if "updateSheetProperties" in request:
                    sheet["frozen"] = request["updateSheetProperties"]["properties"]["gridProperties"]["frozenRowCount"]
            self.touch(sid)
            return resp(200, {})
        if tail == sid:
            return resp(200, {"spreadsheetId": sid, "sheets": [{"properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": sheet["frozen"]}}}]})
        rng = tail.split("/values/")[1]
        if method == "GET":
            a, _, b = rng.partition(":")
            return resp(200, {"values": self.rows(sheet, a, b or a)})
        if rng.endswith(":append"):
            last = max([r for (r, c), v in sheet["cells"].items() if v != ""] or [-1]) + 1
            for i, row in enumerate(body["values"]):
                for j, value in enumerate(row):
                    sheet["cells"][(last + i, j)] = value
            self.touch(sid)
            return resp(200, {})
        a, _, b = rng.partition(":")
        r0, c0 = cell_index(a)
        for i, row in enumerate(body["values"]):
            for j, value in enumerate(row):
                sheet["cells"][(r0 + i, c0 + j)] = value
        self.touch(sid)
        return resp(200, {})

    def slides_call(self, method, url, body):
        if method in self.fail_status:
            return resp(self.fail_status[method], {"error": {"message": "backend error"}})
        tail = url[len(gl.SLIDES):].strip("/")
        if not tail:
            self.next += 1
            did = f"deckMade{self.next:05d}"
            self.decks[did] = {"title": body["title"], "slides": [{"id": "p1", "title": "", "body": ""}]}
            self.add(file(did, body["title"], gd.SLIDES))
            return resp(200, {"presentationId": did, "title": body["title"], "slides": [self.view(self.decks[did])["slides"][0]]})
        did = tail.split(":")[0]
        deck = self.decks.get(did)
        if deck is None or not self.files[did]["mine"]:
            return resp(404, {"error": {"message": "not found"}})
        if method == "GET":
            return resp(200, self.view(deck))
        for request in body["requests"]:
            if "createSlide" in request:
                mapping = {m["layoutPlaceholder"]["type"]: m["objectId"] for m in request["createSlide"]["placeholderIdMappings"]}
                deck["slides"].append({"id": request["createSlide"]["objectId"], "title": "", "body": "", "title_id": mapping["TITLE"], "body_id": mapping["BODY"]})
            elif "insertText" in request:
                target = request["insertText"]["objectId"]
                for slide in deck["slides"]:
                    if target in (slide.get("title_id", slide["id"] + "_title"),):
                        slide["title"] = request["insertText"]["text"]
                    elif target == slide.get("body_id"):
                        slide["body"] = request["insertText"]["text"]
        self.touch(did)
        return resp(200, {})

    @staticmethod
    def view(deck):
        slides = []
        for slide in deck["slides"]:
            title_id = slide.get("title_id", slide["id"] + "_title")
            slides.append({"objectId": slide["id"], "pageElements": [{"objectId": title_id, "shape": {"placeholder": {"type": "TITLE" if slide.get("title_id") else "CENTERED_TITLE"},
                                                                                              "text": {"textElements": [{"textRun": {"content": slide["title"] + ("\n" if slide["title"] else "")}}]}}}]})
        return {"presentationId": "x", "title": deck["title"], "slides": slides}


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, lookup=False)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    return config


@pytest.fixture
def office(monkeypatch):
    service = Office()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: name if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


def propose(config, message_text, tool, args):
    agent = diya.Agent(config, client=FakeClient([tool_reply(tool, json.dumps(args)), text_reply("ok")]), action_kinds=list(gs.action_kinds()) + list(gl.action_kinds()))
    agent.ask([{"role": "user", "content": message_text}])
    return agent


def run_approved(agent):
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    return agent.actions.run(action["id"])


def new_action(agent, before=0):
    found = agent.actions.actions()
    assert len(found) == before + 1, found
    return found[-1]


# ---- what the card may ask for ------------------------------------------------------------------------------------------------------------------

def test_the_drive_change_card_may_make_and_write_sheets_and_decks_and_nothing_else_there():
    one = f"{gs.SHEETS}/sheetBudget001"
    assert client.permitted(gd.CHANGE, "POST", gs.SHEETS) and client.permitted(gd.CHANGE, "GET", one) and client.permitted(gd.CHANGE, "PUT", f"{one}/values/B2:C3") and client.permitted(gd.CHANGE, "POST", f"{one}/values/A1:append")
    assert client.permitted(gd.CHANGE, "POST", f"{one}:batchUpdate") and not client.permitted(gd.CHANGE, "DELETE", one) and not client.permitted(gd.CHANGE, "POST", f"{one}/values:batchClear")
    assert not client.permitted(gd.CHANGE, "PUT", f"{one}/values/Sheet1!A1") and not client.permitted(gd.CHANGE, "GET", f"{one}/values/B2:C3:evil")
    deck = f"{gl.SLIDES}/deckExams00001"
    assert client.permitted(gd.CHANGE, "POST", gl.SLIDES) and client.permitted(gd.CHANGE, "GET", deck) and client.permitted(gd.CHANGE, "POST", f"{deck}:batchUpdate") and not client.permitted(gd.CHANGE, "DELETE", deck)
    assert not any(client.permitted(gd.READ, m, url) for m in ("GET", "POST", "PUT") for url in (one, deck, gs.SHEETS, f"{one}/values/B2:C3"))


# ---- no value becomes a formula -----------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, safe, was", [
    ("=1+1", "'=1+1", True), ("=HYPERLINK(\"http://evil\",\"x\")", "'=HYPERLINK(\"http://evil\",\"x\")", True), ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0", True), ("@SUM(A1)", "'@SUM(A1)", True), ("-2+3", "'-2+3", True),
    ("-5", "-5", False), ("+3.5", "+3.5", False), ("12%", "12%", False), ("books", "books", False), ("a=b", "a=b", False), ("", "", False),
])
def test_a_value_that_could_be_a_formula_is_kept_as_text(value, safe, was):
    assert gs.safe_cell(value) == (safe, was)


def test_rows_have_limits_and_say_how_many_cells_were_kept_as_text():
    assert gs.parse_rows("item, cost; =1+1, -3; books, 40") == ([["item", "cost"], ["'=1+1", "-3"], ["books", "40"]], 1)
    for bad in ("", " ; ; ", ";".join("a" for _ in range(gs.MAX_ROWS + 1)), ",".join("a" for _ in range(gs.MAX_COLS + 1)), "x" * (gs.CELL_MAX + 1)):
        with pytest.raises(diya_actions.InvalidArgs):
            gs.parse_rows(bad)


@pytest.mark.parametrize("text, fn, expected", [
    ("make a Google Sheet called Budget with rows item, cost", asks.asks_for_sheet, True), ("add buy milk to my google tasks", asks.asks_for_sheet, False),
    ("add a row to the Budget sheet: pens, 5", asks.appends_to_sheet, True), ("add a row to my to-do list", asks.appends_to_sheet, False),
    ("in the Budget sheet set B2 to 45", asks.changes_sheet_cells, True), ("in the Budget sheet change the word", asks.changes_sheet_cells, False),
    ("make the header row of the Budget sheet bold", asks.formats_sheet_header, True),
    ("make a Google Slides deck called Exams with slides on revision", asks.asks_for_slides, True), ("add a slide to the Exams deck: Revision plan", asks.adds_slides, True), ("make a new google doc called Plan", asks.asks_for_slides, False),
])
def test_each_kind_is_asked_for_only_in_its_own_words(text, fn, expected):
    assert fn(text) is expected


# ---- make a sheet -------------------------------------------------------------------------------------------------------------------------------

def test_a_sheet_is_made_with_rows_written_as_plain_text_and_read_back(config, office):
    agent = propose(config, "make a Google Sheet called Plan with rows week, task; 1, =maths", "propose_google_sheet", {"title": "Plan", "rows": "week, task; 1, =maths"})
    action = new_action(agent)
    assert action["args"]["rows"] == "week, task; 1, '=maths" and action["args"]["kept_as_text"] == 1 and "1 cell(s) that began with = + - or @ are kept as plain text" in action["summary"]
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "read it back to check" in done["result"]
    put = [r for r in office.requests if r[0] == "PUT"][0]
    assert put[2] == {"valueInputOption": "RAW"} and put[3]["values"] == [["week", "task"], ["1", "'=maths"]]
    assert [office.sheets[s]["cells"] for s in office.sheets if office.sheets[s]["title"] == "Plan"][0][(1, 1)] == "'=maths"


def test_a_sheet_needs_a_name_the_person_said(config, office):
    agent = propose(config, "make a Google Sheet with rows a, b", "propose_google_sheet", {"title": "Secret plan", "rows": "a, b"})
    assert agent.actions.actions() == [] and office.mutations() == []


def test_a_sheet_whose_rows_could_not_be_written_is_unknown_and_says_where_it_is(config, office):
    agent = propose(config, "make a Google Sheet called Plan with rows a, b", "propose_google_sheet", {"title": "Plan", "rows": "a, b"})
    office.fail_status["PUT"] = 500
    done = run_approved(agent)
    assert done["status"] == "unknown" and "The sheet was made but its rows could not be put in it" in done["result"] and "docs.google.com/spreadsheets" in done["result"]


# ---- add rows ---------------------------------------------------------------------------------------------------------------------------------------------

def test_rows_are_added_after_the_last_row_the_card_said_and_read_back(config, office):
    agent = propose(config, "add a row to the Budget sheet: pens, 5", "propose_sheet_rows", {"name": "Budget", "rows": "pens, 5"})
    action = new_action(agent)
    assert action["args"]["after_row"] == 2 and action["summary"].startswith("Add 1 row(s) to the Google Sheet Budget, after row 2: pens, 5") and office.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and office.sheets["sheetBudget001"]["cells"][(2, 0)] == "pens"
    post = office.mutations()[0]
    assert post[2] == {"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"}


def test_a_sheet_that_changed_since_the_proposal_gets_nothing(config, office):
    agent = propose(config, "add a row to the Budget sheet: pens, 5", "propose_sheet_rows", {"name": "Budget", "rows": "pens, 5"})
    office.sheets["sheetBudget001"]["cells"][(2, 0)] = "added by Sam"
    office.touch("sheetBudget001")
    done = run_approved(agent)
    assert done["status"] == "failed" and "changed in Google Drive after it was proposed" in done["result"] and office.mutations() == []


def test_a_sheet_diya_did_not_make_cannot_be_found(config, office):
    agent = propose(config, "add a row to the Others sheet: pens, 5", "propose_sheet_rows", {"name": "Others sheet", "rows": "pens, 5"})
    assert agent.actions.actions() == []


# ---- change cells ----------------------------------------------------------------------------------------------------------------------------------------

def test_empty_cells_are_written_and_read_back(config, office):
    agent = propose(config, "in the Budget sheet set D2 to 45", "propose_sheet_cells", {"name": "Budget", "start": "D2", "rows": "45"})
    action = new_action(agent)
    assert action["args"]["filled"] == 0 and action["args"]["range"] == "D2:D2" and "only empty cells" in action["summary"]
    done = run_approved(agent)
    assert done["status"] == "succeeded" and office.sheets["sheetBudget001"]["cells"][(1, 3)] == "45"


def test_filled_cells_are_replaced_only_when_the_person_said_replace_or_overwrite_and_the_card_shows_what_is_lost(config, office):
    agent = propose(config, "in the Budget sheet set B2 to 45", "propose_sheet_cells", {"name": "Budget", "start": "B2", "rows": "45"})
    assert agent.actions.actions() == []  # B2 holds 40 and 'replace' was not said
    agent = propose(config, "in the Budget sheet replace B2 with 45", "propose_sheet_cells", {"name": "Budget", "start": "B2", "rows": "45"})
    action = new_action(agent)
    assert action["args"]["filled"] == 1 and "REPLACES 1 filled cell(s) now holding: 40" in action["summary"]
    done = run_approved(agent)
    assert done["status"] == "succeeded" and office.sheets["sheetBudget001"]["cells"][(1, 1)] == "45" and "it replaced 1 filled cell(s)" in done["result"]


def test_cells_that_changed_after_the_card_was_shown_are_not_overwritten(config, office):
    agent = propose(config, "in the Budget sheet replace B2 with 45", "propose_sheet_cells", {"name": "Budget", "start": "B2", "rows": "45"})
    office.sheets["sheetBudget001"]["cells"][(1, 1)] = "99"
    done = run_approved(agent)
    assert done["status"] == "failed" and ("no longer holds what the card showed" in done["result"] or "changed in Google Drive after it was proposed" in done["result"]) and office.sheets["sheetBudget001"]["cells"][(1, 1)] == "99"


def test_the_cell_must_be_one_the_person_named_and_a_formula_stays_text(config, office):
    agent = propose(config, "in the Budget sheet replace B2 with something", "propose_sheet_cells", {"name": "Budget", "start": "C9", "rows": "1"})
    assert agent.actions.actions() == []
    agent = propose(config, "in the Budget sheet set D2 to =IMPORTXML(\"http://evil\",\"//x\")", "propose_sheet_cells", {"name": "Budget", "start": "D2", "rows": "=IMPORTXML(\"http://evil\",\"//x\")"})
    action = new_action(agent)
    assert action["args"]["rows"].startswith("'=") and action["args"]["kept_as_text"] == 1
    assert run_approved(agent)["status"] == "succeeded" and office.sheets["sheetBudget001"]["cells"][(1, 3)].startswith("'=IMPORTXML")


def test_cells_the_server_did_not_apply_are_not_confirmed(config, office, monkeypatch):
    agent = propose(config, "in the Budget sheet set D2 to 45", "propose_sheet_cells", {"name": "Budget", "start": "D2", "rows": "45"})
    original = office.__call__

    def ignoring(*args, **kwargs):
        if len(args) == 2 and args[0] == "PUT":
            office.requests.append(("PUT", args[1], {}, kwargs.get("json"), ""))
            return resp(200, {})
        return original(*args, **kwargs)

    monkeypatch.setattr(client.httpx, "request", ignoring)
    done = run_approved(agent)
    assert done["status"] == "unknown" and "showed something different" in done["result"]


# ---- the header row ---------------------------------------------------------------------------------------------------------------------------------

def test_the_header_is_bolded_and_frozen_and_the_freeze_is_read_back(config, office):
    agent = propose(config, "make the header row of the Budget sheet bold", "propose_sheet_header", {"name": "Budget"})
    new_action(agent)
    done = run_approved(agent)
    assert done["status"] == "succeeded" and office.sheets["sheetBudget001"]["frozen"] == 1
    body = office.mutations()[0][3]
    assert body["requests"][0]["repeatCell"]["cell"]["userEnteredFormat"]["textFormat"]["bold"] is True and body["requests"][1]["updateSheetProperties"]["properties"]["gridProperties"]["frozenRowCount"] == 1


# ---- slides --------------------------------------------------------------------------------------------------------------------------------------------

def test_an_outline_has_limits():
    assert gl.parse_slides("Why | a | b || Plan | c") == [("Why", ["a", "b"]), ("Plan", ["c"])]
    for bad in ("", " || ", "||".join(f"s{n}" for n in range(gl.MAX_SLIDES + 1)), "t | " + " | ".join("b" for _ in range(gl.MAX_BULLETS + 1)), "t | " + "x" * (gl.TEXT_MAX + 1)):
        with pytest.raises(diya_actions.InvalidArgs):
            gl.parse_slides(bad)


def test_a_deck_is_made_from_an_outline_shown_whole_and_the_count_and_titles_are_read_back(config, office):
    said = "make a Google Slides deck called Revision with slides: Why | spaced practice || Plan | week 1"
    agent = propose(config, said, "propose_google_slides", {"title": "Revision", "slides": "Why | spaced practice || Plan | week 1"})
    action = new_action(agent)
    assert action["summary"] == "Make a new Google Slides deck called Revision with a title slide and 2 slide(s): Why / Plan (the whole outline is in the fields below)" and office.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "the count and every title read back to check" in done["result"]
    deck = [d for d in office.decks.values() if d["title"] == "Revision"][0]
    assert [s["title"] for s in deck["slides"]] == ["Revision", "Why", "Plan"] and deck["slides"][1]["body"] == "spaced practice"
    batch = [r for r in office.mutations() if r[1].endswith(":batchUpdate")][0][3]["requests"]
    assert all(r.get("createSlide", {}).get("slideLayoutReference", {"predefinedLayout": "TITLE_AND_BODY"}) == {"predefinedLayout": "TITLE_AND_BODY"} for r in batch)


def test_a_deck_needs_a_name_the_person_said_and_slides(config, office):
    agent = propose(config, "make a Google Slides deck with slides: Why | a", "propose_google_slides", {"title": "Hidden", "slides": "Why | a"})
    assert agent.actions.actions() == []
    agent = propose(config, "make a Google Slides deck called Revision", "propose_google_slides", {"title": "Revision", "slides": ""})
    assert agent.actions.actions() == [] and office.mutations() == []


def test_a_deck_whose_slides_could_not_be_put_in_is_unknown_and_says_where_it_is(config, office):
    agent = propose(config, "make a Google Slides deck called Revision with slides: Why | a", "propose_google_slides", {"title": "Revision", "slides": "Why | a"})
    original = office.__call__
    state = {}

    def failing(*args, **kwargs):
        if len(args) == 2 and args[0] == "POST" and args[1].endswith(":batchUpdate"):
            office.requests.append(("POST", args[1], {}, kwargs.get("json"), ""))
            return resp(500, {"error": {"message": "backend error"}})
        return original(*args, **kwargs)

    monkey = pytest.MonkeyPatch()
    monkey.setattr(client.httpx, "request", failing)
    try:
        done = run_approved(agent)
    finally:
        monkey.undo()
    assert done["status"] == "unknown" and "The deck was made but its slides could not be put in it" in done["result"] and "docs.google.com/presentation" in done["result"]


def test_slides_are_added_to_a_deck_diya_made_after_its_last_slide_and_read_back(config, office):
    agent = propose(config, "add a slide to the Exams deck: Revision plan | mock tests", "propose_add_slides", {"name": "Exams deck", "slides": "Revision plan | mock tests"})
    action = new_action(agent)
    assert action["args"]["slide_count"] == 2 and "(now 2 slide(s))" in action["summary"]
    done = run_approved(agent)
    assert done["status"] == "succeeded" and [s["title"] for s in office.decks["deckExams00001"]["slides"]] == ["Exams deck", "Plan", "Revision plan"]


def test_a_deck_that_changed_since_is_not_added_to_and_one_diya_did_not_make_is_not_found(config, office):
    agent = propose(config, "add a slide to the Exams deck: Revision plan", "propose_add_slides", {"name": "Exams deck", "slides": "Revision plan"})
    office.decks["deckExams00001"]["slides"].append({"id": "p9", "title": "Sam added", "body": ""})
    office.touch("deckExams00001")
    done = run_approved(agent)
    assert done["status"] == "failed" and office.mutations() == []
    office.add(file("deckOthers0001", "Others deck", gd.SLIDES, mine=False))
    agent = propose(config, "add a slide to the Others deck: Hello", "propose_add_slides", {"name": "Others deck", "slides": "Hello"})
    assert len(agent.actions.actions()) == 1  # only the first (refused later) proposal is there


# ---- the catalog and the switches -----------------------------------------------------------------------------------------------------------------------

def test_every_kind_is_in_the_catalog_and_none_can_be_done_straight_away():
    kinds = list(gs.action_kinds()) + list(gl.action_kinds())
    expected = {"propose_google_sheet", "propose_sheet_rows", "propose_sheet_cells", "propose_sheet_header", "propose_google_slides", "propose_add_slides"}
    assert {k.tool_name for k in kinds} == expected and all(diya_catalog.CATALOG[n].tier == 2 and diya_catalog.CATALOG[n].approval == "owner approves each action" for n in expected)
    assert not {k.name for k in kinds} & set(diya_autoapprove.AUTO_KINDS) and all(k.auto_ok is None for k in kinds)


def test_the_models_tools_cannot_name_an_id_a_range_to_overwrite_or_a_formula_mode():
    for kind in list(gs.action_kinds()) + list(gl.action_kinds()):
        assert not set(kind.tool["function"]["parameters"]["properties"]) & {"file_id", "version", "range", "filled", "before", "value_input_option", "valueInputOption", "formula"}, kind.name
