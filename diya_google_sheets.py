"""Google Sheets on the sheets Diya made: make one, add rows, change cells, and bold and freeze the header row, each only when you approve it (DIYA-101 to -105; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Uses the narrow `drive.file` permission of the Drive (change) card, which only ever sees what Diya made: so these work on sheets Diya made and cannot reach any other sheet. (Reading ANY sheet is the Drive read card: a Sheet comes back
as rows of what is shown in it.)

The rules (docs/GOOGLE_CHANGES.md): a proposal the owner approves exactly as shown, never straight away; the sheet is found NOW by the words the person used; the rows are in the card whole; **no value can become a formula**
(DIYA-104): everything is written as plain text (`valueInputOption=RAW`, so `=1+1` stays text) and a value that starts with `=`, `+`, `-` or `@` and is not a plain number is also kept as text with a visible apostrophe in front, so
that it stays text when the sheet is exported and opened elsewhere, and the card says how many; changing cells shows the range and what is in it now, and **replacing filled cells needs the word replace or overwrite in the
person's own message** (DIYA-105) and is checked again when it runs: if the cells are no longer what the card showed, nothing is done; every change is read back; an outcome that is not known is `unknown` and never retried.

Not built: charts, named ranges, other formatting, formulas, several sheets in one file, and sheets Diya did not make.

Importing this module has no side effects except naming what the Drive (change) card may ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import re

import diya_google_client as client
import diya_google_drive as gd
import diya_google_write as gw
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

CARD = gd.CHANGE
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
MAX_ROWS, MAX_COLS, CELL_MAX = 30, 10, 100
CELL_RANGE = r"[A-Z]{1,2}[0-9]{1,4}(?::[A-Z]{1,2}[0-9]{1,4})?"
_S = re.escape(SHEETS)
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:[.,][0-9]+)?|\.[0-9]+)%?")

client.allow(CARD, "POST", _S)
client.allow(CARD, "GET", rf"{_S}/{gd.FID}")
client.allow(CARD, "GET", rf"{_S}/{gd.FID}/values/{CELL_RANGE}")
client.allow(CARD, "PUT", rf"{_S}/{gd.FID}/values/{CELL_RANGE}")
client.allow(CARD, "POST", rf"{_S}/{gd.FID}/values/{CELL_RANGE}:append")
client.allow(CARD, "POST", rf"{_S}/{gd.FID}:batchUpdate")


# ---- rows as the person's card shows them, and the one place a value is made safe ---------------------------------------------------------------

def safe_cell(value):
    """(the value, whether it had to be kept as text): a value that starts with = + - or @ (or a tab or a line break) and is not a plain number gets an apostrophe in front, so that no spreadsheet program reads it as a formula."""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _NUMBER.fullmatch(text.strip()):
        return "'" + text, True
    return text, False


def parse_rows(text):
    """Rows from the text of a card: rows separated by ';', cells by ','. ([[cell]], how many cells were kept as text); InvalidArgs for too much or nothing."""
    rows, kept = [], 0
    for line in str(text or "").split(";"):
        cells = [cell.strip() for cell in line.split(",")]
        if not any(cells):
            continue
        if len(cells) > MAX_COLS or any(len(c) > CELL_MAX for c in cells):
            raise InvalidArgs(f"a row has at most {MAX_COLS} cells of at most {CELL_MAX} characters")
        row = []
        for cell in cells:
            safe, was = safe_cell(cell)
            kept += was
            row.append(safe)
        rows.append(row)
    if not rows:
        raise InvalidArgs("there are no rows: write them as 'item, cost; books, 40; pens, 5'")
    if len(rows) > MAX_ROWS:
        raise InvalidArgs(f"at most {MAX_ROWS} rows at a time")
    return rows, kept


def rows_text(rows):
    return "; ".join(", ".join(row) for row in rows)


def _clean_rows_arg(text):
    parse_rows(text)  # validates
    if diya_memory.printable(text) != text:
        raise InvalidArgs("the rows are one plain line")


def _a1(rows, start="A1"):
    """The range a block of rows covers from `start` (a top-left cell): 'A1:C3'."""
    column, row = re.fullmatch(r"([A-Z]{1,2})([0-9]{1,4})", start).groups()
    width = max(len(r) for r in rows)
    index = 0
    for ch in column:
        index = index * 26 + ord(ch) - 64
    last = index + width - 1
    letters = ""
    while last:
        last, rest = divmod(last - 1, 26)
        letters = chr(65 + rest) + letters
    return f"{start}:{letters}{int(row) + len(rows) - 1}"


def _values(config, sheet_id, cells):
    data = client.read(config, CARD, gd.LABELS[CARD], f"{SHEETS}/{sheet_id}/values/{cells}")
    return [[str(c) for c in row] for row in (data.get("values") or []) if isinstance(row, list)]


def _trim(rows):
    """Rows without the empty cells and empty rows at the ends, which Google leaves out when it answers."""
    out = [list(r) for r in rows]
    for r in out:
        while r and r[-1] == "":
            r.pop()
    while out and not out[-1]:
        out.pop()
    return out


def _find_sheet(config, name, said):
    return gd.find_file(config, name, said, mime=gd.SHEET)


def _validate_ref(args):
    if not isinstance(args.get("file_id"), str) or not re.fullmatch(gd.FID, args["file_id"]):
        raise InvalidArgs("a change needs the sheet found by its name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("name"), "a sheet")


# ---- make a sheet --------------------------------------------------------------------------------------------------------------------------------------

def create_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("title", "rows")}
    if not gw._own_words(kept.get("title"), text):
        raise InvalidArgs("the sheet's name must be one the user said; ask them what to call it")
    if kept.get("rows"):
        rows, was = parse_rows(kept["rows"])
        kept["rows"] = rows_text(rows)
        if was:
            kept["kept_as_text"] = was
    else:
        kept.pop("rows", None)
    return kept, []


def create_validate(args):
    gw._only(args, {"title", "rows", "kept_as_text"}, "a Google Sheet")
    gw._clean_title(args.get("title"), "a sheet")
    if args.get("rows") is not None:
        _clean_rows_arg(args["rows"])
    if args.get("kept_as_text") is not None and (not isinstance(args["kept_as_text"], int) or isinstance(args["kept_as_text"], bool) or args["kept_as_text"] < 1):
        raise InvalidArgs("how many cells were kept as text is a number")


def _text_note(args):
    return f"; {args['kept_as_text']} cell(s) that began with = + - or @ are kept as plain text" if args.get("kept_as_text") else ""


def create_render(args):
    rows = parse_rows(args["rows"])[0] if args.get("rows") else []
    return f"Make a new Google Sheet called {diya_memory.printable(args['title'], 70)}" + (f", with {len(rows)} row(s), the first being: {diya_memory.printable(', '.join(rows[0]), 70)}" if rows else ", empty") + _text_note(args)


def create_execute(config, args):
    made = client.as_json(client.send(config, CARD, gd.LABELS[CARD], "POST", SHEETS, body={"properties": {"title": args["title"]}}, doing="making the sheet"))
    sheet_id = made.get("spreadsheetId")
    if not isinstance(sheet_id, str) or not re.fullmatch(gd.FID, sheet_id) or (made.get("properties") or {}).get("title") != args["title"]:
        raise ActionUncertain("Google answered, but not with the sheet that was asked for, so it may or may not be in your Drive. Look in Google Drive, then record what you found.")
    link = f" https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    rows = parse_rows(args["rows"])[0] if args.get("rows") else []
    if rows:
        try:
            cells = _a1(rows)
            client.send(config, CARD, gd.LABELS[CARD], "PUT", f"{SHEETS}/{sheet_id}/values/{cells}", params={"valueInputOption": "RAW"}, body={"range": cells, "majorDimension": "ROWS", "values": rows}, doing="writing the rows")
        except (ActionFailed, ActionUncertain) as exc:
            raise ActionUncertain(f"The sheet was made but its rows could not be put in it ({exc}). It is here:{link}")
        try:
            got = _trim(_values(config, sheet_id, _a1(rows)))
        except client.GoogleError:
            raise ActionUncertain(f"Google said the sheet was made, but reading it back to check did not work, so it is not confirmed. It is here:{link}")
        if got != _trim(rows):
            raise ActionUncertain(f"Google said the sheet was made, but reading it back showed different rows, so it is not confirmed. It is here:{link}")
    return f"Made the Google Sheet {args['title']}" + (f" with {len(rows)} row(s)" if rows else "") + f" and read it back to check.{link}"


# ---- add rows ---------------------------------------------------------------------------------------------------------------------------------------------

def append_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "rows")}
    rows, was = parse_rows(kept.get("rows"))
    kept["rows"] = rows_text(rows)
    if was:
        kept["kept_as_text"] = was
    return kept, []


def append_resolve(config, args, said):
    file = _find_sheet(config, args.get("name"), said)
    try:
        have = _trim(_values(config, file["id"], f"A1:{'J'}{1000}"))
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    return dict(gd._ref(file), rows=args["rows"], after_row=len(have), **({"kept_as_text": args["kept_as_text"]} if args.get("kept_as_text") else {}))


def append_validate(args):
    gw._only(args, {"name", "file_id", "version", "rows", "after_row", "kept_as_text"}, "adding rows")
    _validate_ref(args)
    _clean_rows_arg(args.get("rows"))
    if not isinstance(args.get("after_row"), int) or isinstance(args.get("after_row"), bool) or not 0 <= args["after_row"] <= 1000:
        raise InvalidArgs("where the rows go is found by looking at the sheet")


def append_render(args):
    rows = parse_rows(args["rows"])[0]
    return f"Add {len(rows)} row(s) to the Google Sheet {diya_memory.printable(args['name'], 60)}, after row {args['after_row']}: {diya_memory.printable(rows_text(rows), 100)}" + _text_note(args)


def append_execute(config, args):
    gd._still_the_same(config, args)  # (the file is where it was; a sheet's `version` moves with every edit, so a changed sheet is reported, not overwritten)
    rows = parse_rows(args["rows"])[0]
    try:
        before = _trim(_values(config, args["file_id"], "A1:J1000"))
    except client.GoogleError as exc:
        raise ActionFailed(f"{exc} Nothing was done.")
    if len(before) != args["after_row"]:
        raise ActionFailed("The sheet has a different number of rows than when this was proposed, so nothing was added. Look at it and ask again if you still want this.")
    client.send(config, CARD, gd.LABELS[CARD], "POST", f"{SHEETS}/{args['file_id']}/values/A1:append", params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"}, body={"majorDimension": "ROWS", "values": rows},
                doing=f"adding rows to '{args['name']}'")
    try:
        after = _trim(_values(config, args["file_id"], "A1:J1000"))
    except client.GoogleError:
        raise ActionUncertain("Google said the rows were added, but reading the sheet back to check did not work, so it is not confirmed. Look in Google Sheets, then record what you found.")
    if after != _trim(before + rows):
        raise ActionUncertain("Google said the rows were added, but reading the sheet back showed something different, so it is not confirmed. Look in Google Sheets, then record what you found.")
    return f"Added {len(rows)} row(s) to the Google Sheet '{args['name']}' (after row {args['after_row']}) and read it back to check."


# ---- change cells (a range, with what is in it now) -------------------------------------------------------------------------------------------

_REPLACE_WORDS = re.compile(r"\b(?:replace|overwrite|overwriting|replacing)\b", re.IGNORECASE)


def update_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "start", "rows")}
    if not re.fullmatch(r"[A-Z]{1,2}[0-9]{1,4}", str(kept.get("start") or "")) or not re.search(rf"(?<![A-Za-z0-9]){re.escape(kept['start'])}(?![A-Za-z0-9])", text, re.IGNORECASE):
        raise InvalidArgs("say which cell the change starts at (like B2), in the user's own words; I do not choose")
    rows, was = parse_rows(kept.get("rows"))
    kept["rows"] = rows_text(rows)
    if was:
        kept["kept_as_text"] = was
    return kept, []


def update_resolve(config, args, said):
    file = _find_sheet(config, args.get("name"), said)
    rows = parse_rows(args["rows"])[0]
    cells = _a1(rows, args["start"])
    try:
        now = _values(config, file["id"], cells)
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    filled = sum(1 for row in now for cell in row if cell != "")
    if filled and not _REPLACE_WORDS.search(said):
        raise InvalidArgs(f"{cells} already holds {filled} filled cell(s) ({diya_memory.printable(rows_text(now), 80)}); changing them replaces what is there, so the user must say 'replace' or 'overwrite' (ask them)")
    resolved = dict(gd._ref(file), start=args["start"], rows=args["rows"], range=cells, filled=filled, before=rows_text(_trim(now)) or "(empty)")
    if args.get("kept_as_text"):
        resolved["kept_as_text"] = args["kept_as_text"]
    return resolved


def update_validate(args):
    gw._only(args, {"name", "file_id", "version", "start", "rows", "range", "filled", "before", "kept_as_text"}, "changing cells")
    _validate_ref(args)
    _clean_rows_arg(args.get("rows"))
    if not re.fullmatch(r"[A-Z]{1,2}[0-9]{1,4}", str(args.get("start"))) or not re.fullmatch(CELL_RANGE, str(args.get("range"))):
        raise InvalidArgs("the cells are like B2")
    if not isinstance(args.get("filled"), int) or isinstance(args.get("filled"), bool) or args["filled"] < 0:
        raise InvalidArgs("how many cells are filled is a number")
    before = args.get("before")
    if not isinstance(before, str) or not before or len(before) > 1500 or diya_memory.printable(before) != before:
        raise InvalidArgs("what is in the cells now is one plain line")


def update_render(args):
    rows = parse_rows(args["rows"])[0]
    risk = f"REPLACES {args['filled']} filled cell(s) now holding: {diya_memory.printable(args['before'], 60)}" if args["filled"] else "only empty cells"
    return f"In the Google Sheet {diya_memory.printable(args['name'], 50)} write {diya_memory.printable(rows_text(rows), 70)} into {args['range']} ({risk})" + _text_note(args)


def update_execute(config, args):
    gd._still_the_same(config, args)
    rows = parse_rows(args["rows"])[0]
    try:
        now = _trim(_values(config, args["file_id"], args["range"]))
    except client.GoogleError as exc:
        raise ActionFailed(f"{exc} Nothing was done.")
    if (rows_text(now) or "(empty)") != args["before"]:
        raise ActionFailed(f"{args['range']} no longer holds what the card showed (it was changed after this was proposed), so nothing was done. Look at the sheet and ask again if you still want this.")
    client.send(config, CARD, gd.LABELS[CARD], "PUT", f"{SHEETS}/{args['file_id']}/values/{args['range']}", params={"valueInputOption": "RAW"}, body={"range": args["range"], "majorDimension": "ROWS", "values": rows},
                doing=f"changing cells in '{args['name']}'")
    try:
        after = _trim(_values(config, args["file_id"], args["range"]))
    except client.GoogleError:
        raise ActionUncertain("Google said the cells were changed, but reading them back to check did not work, so it is not confirmed. Look in Google Sheets, then record what you found.")
    if after != _trim(rows):
        raise ActionUncertain("Google said the cells were changed, but reading them back showed something different, so it is not confirmed. Look in Google Sheets, then record what you found.")
    return f"Wrote {args['range']} in the Google Sheet '{args['name']}' and read it back to check" + (f" (it replaced {args['filled']} filled cell(s))." if args["filled"] else ".")


# ---- the header row: bold, and stays in view (the layout template) --------------------------------------------------------------------------------

def header_resolve(config, args, said):
    file = _find_sheet(config, args.get("name"), said)
    return dict(gd._ref(file))


def header_validate(args):
    gw._only(args, {"name", "file_id", "version"}, "formatting a sheet")
    _validate_ref(args)


def header_render(args):
    return f"In the Google Sheet {diya_memory.printable(args['name'], 80)} make the first row bold and keep it in view when scrolling (nothing else changes)"


def header_execute(config, args):
    gd._still_the_same(config, args)
    requests = [
        {"repeatCell": {"range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1}, "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}},
        {"updateSheetProperties": {"properties": {"sheetId": 0, "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}},
    ]
    client.send(config, CARD, gd.LABELS[CARD], "POST", f"{SHEETS}/{args['file_id']}:batchUpdate", body={"requests": requests}, doing=f"formatting '{args['name']}'")
    try:
        found = client.read(config, CARD, gd.LABELS[CARD], f"{SHEETS}/{args['file_id']}")
    except client.GoogleError:
        raise ActionUncertain("Google said the header was formatted, but reading the sheet back to check did not work, so it is not confirmed. Look in Google Sheets, then record what you found.")
    frozen = [((s.get("properties") or {}).get("gridProperties") or {}).get("frozenRowCount") for s in (found.get("sheets") or []) if isinstance(s, dict)]
    if 1 not in frozen[:1]:
        raise ActionUncertain("Google said the header was formatted, but the first row is not kept in view, so it is not confirmed. Look in Google Sheets, then record what you found.")
    return f"The first row of the Google Sheet '{args['name']}' is bold and kept in view (read back: the row is frozen)."


# ---- the kinds ----------------------------------------------------------------------------------------------------------------------------------------

def _kind(name, label, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=CARD, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is done until the user approves it on the Actions page. It works only on sheets Diya made.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


NAME = {"type": "string", "description": "The sheet's name, exactly as the user said it."}
ROWS = {"type": "string", "description": "The rows, on one line: rows separated by ';' and cells by ',', for example 'item, cost; books, 40; pens, 5'. Plain values only: nothing becomes a formula."}


def action_kinds():
    return (
        _kind("google_sheets_create", "Make a Google Sheet", "propose_google_sheet", "Propose making a new Google Sheet, optionally with rows (the first row the headings). Use it only when the user asks for a Google Sheet or spreadsheet.",
              {"title": {"type": "string", "description": "The sheet's name, exactly as the user said it."}, "rows": ROWS}, ["title"], validate=create_validate, render=create_render, execute=create_execute,
              asked=asks.asks_for_sheet, prepare=create_prepare),
        _kind("google_sheets_append", "Add rows to a Google Sheet", "propose_sheet_rows", "Propose adding rows to the end of a Google Sheet. Use it only when the user asks to add rows to a sheet, naming it.",
              {"name": NAME, "rows": ROWS}, ["name", "rows"], validate=append_validate, render=append_render, execute=append_execute, asked=asks.appends_to_sheet, prepare=append_prepare, resolve=append_resolve),
        _kind("google_sheets_update", "Change cells in a Google Sheet", "propose_sheet_cells", "Propose writing values into cells of a Google Sheet, starting at a cell the user named (like B2). Replacing filled cells needs the user to say replace or overwrite.",
              {"name": NAME, "start": {"type": "string", "description": "The first cell, like B2, as the user said it."}, "rows": ROWS}, ["name", "start", "rows"], validate=update_validate, render=update_render, execute=update_execute,
              asked=asks.changes_sheet_cells, prepare=update_prepare, resolve=update_resolve),
        _kind("google_sheets_header", "Bold the header row of a Google Sheet", "propose_sheet_header", "Propose making the first row of a Google Sheet bold and keeping it in view. Use it only when the user asks for that, naming the sheet.",
              {"name": NAME}, ["name"], validate=header_validate, render=header_render, execute=header_execute, asked=asks.formats_sheet_header, resolve=header_resolve),
    )
