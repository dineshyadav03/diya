"""Keeps the owner's task sheet in step with the work (docs/TRACKER.md), added 2026-10-18.

    python scripts/tracker.py apply --dir "C:/Users/dines/Downloads/diya research materials"
    python scripts/tracker.py summary [--dir DIR] [--write docs/TRACKER.md]

The owner's task sheet comes as three files (a .csv, a checklist .md and a .xlsx) from the blueprint of 2026-10-18. The progress itself is kept in ONE small file in the repository,
`docs/tracker/progress.csv` (Task ID, Status, Owner, Date, Evidence, Notes), edited as work is finished. `apply` writes that into all three of the owner's files, so they always show the same thing:

* the .csv: the Status, Owner, Target date, Evidence and Notes cells of each task;
* the .md checklist: the box is ticked only for "Done", the status line says the new status, and the evidence and notes are added under the task;
* the .xlsx: the same cells of the "Tasks" sheet, changed in the file's XML so that nothing else in the workbook (its formulas, colours, tables and drop-downs) is touched; Excel is told to recalculate its Dashboard when it opens.

Rules this keeps, from the blueprint itself: "Done" needs evidence (a commit, a test or a document), and a task that touches Google, a phone or another real thing the tests cannot reach is not "Done" until
the owner has tried it; until then it says "In progress" and the note says what is still to be checked. Applying twice gives the same result; a task not in the progress file is left exactly as it was.

Importing this module has no side effects.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

STATUSES = ("Not started", "Needs verification", "Research queue", "In progress", "Blocked", "Done", "Deferred")
OWNERS = ("Claude", "Dinesh", "Both")
ID = re.compile(r"^DIYA-[0-9]{3}$")
CSV_NAME, MD_NAME, XLSX_NAME = "DIYA_COMPLETE_TASK_TRACKER.csv", "DIYA_COMPLETE_TASK_CHECKLIST.md", "DIYA_COMPLETE_TASK_TRACKER.xlsx"
PROGRESS = Path(__file__).resolve().parent.parent / "docs" / "tracker" / "progress.csv"
FIELDS = ("Task ID", "Status", "Owner", "Date", "Evidence", "Notes")
BOM = b"\xef\xbb\xbf"


class TrackerError(Exception):
    """The progress file or a sheet is not what it should be; nothing was written."""


# ---- the progress file ------------------------------------------------------------------------------------------------------------------------

def read_progress(path=PROGRESS):
    """{task id: row} from the progress file; a later row for the same task replaces an earlier one. TrackerError for a row that breaks a rule."""
    found = OrderedDict()
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise TrackerError(f"{path}: the columns must be {', '.join(FIELDS)}")
        for number, row in enumerate(reader, 2):
            row = {key: (value or "").strip() for key, value in row.items()}
            where = f"{path} line {number}"
            if not ID.match(row["Task ID"]):
                raise TrackerError(f"{where}: {row['Task ID']!r} is not a task id like DIYA-001")
            if row["Status"] not in STATUSES:
                raise TrackerError(f"{where}: status {row['Status']!r} is not one of {', '.join(STATUSES)}")
            if row["Owner"] not in OWNERS:
                raise TrackerError(f"{where}: owner {row['Owner']!r} is not one of {', '.join(OWNERS)}")
            if row["Status"] == "Done" and not row["Evidence"]:
                raise TrackerError(f"{where}: {row['Task ID']} is Done but has no evidence (a commit, a test or a document)")
            if row["Date"] and not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", row["Date"]):
                raise TrackerError(f"{where}: the date must look like 2026-10-18")
            found[row["Task ID"]] = row
    return found


# ---- the .csv ---------------------------------------------------------------------------------------------------------------------------------

def _cells(row):
    """What goes in the sheet's own columns for one progress row."""
    return {"Status": row["Status"], "Owner": row["Owner"], "Target date": row["Date"], "Evidence / PR / test": row["Evidence"], "Notes": row["Notes"]}


def apply_csv(path, progress):
    """Write the progress into the .csv, keeping its byte order mark and line endings. Returns the rows (as dicts) after the change."""
    raw = Path(path).read_bytes()
    bom = raw.startswith(BOM)
    text = raw[len(BOM):].decode("utf-8") if bom else raw.decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    table = list(csv.reader(io.StringIO(text, newline="")))
    header = table[0]
    index = {name: header.index(name) for name in ("Task ID", "Status", "Owner", "Target date", "Evidence / PR / test", "Notes")}
    unknown = set(progress) - {row[index["Task ID"]] for row in table[1:]}
    if unknown:
        raise TrackerError(f"{path}: no such task: {', '.join(sorted(unknown))}")
    for row in table[1:]:
        if row[index["Task ID"]] in progress:
            for name, value in _cells(progress[row[index["Task ID"]]]).items():
                row[index[name]] = value
    out = io.StringIO(newline="")
    csv.writer(out, lineterminator=eol).writerows(table)
    Path(path).write_bytes((BOM if bom else b"") + out.getvalue().encode("utf-8"))
    return [dict(zip(header, row)) for row in table[1:]]


# ---- the .md checklist ------------------------------------------------------------------------------------------------------------------------

TASK_LINE = re.compile(r"^- \[[ xX]\] \*\*(DIYA-[0-9]{3}) ")
PROGRESS_START, PROGRESS_END = "<!-- progress:start -->", "<!-- progress:end -->"


def _progress_block(rows, today):
    by_status = Counter(row["Status"] for row in rows)
    milestones = OrderedDict()
    for row in rows:
        counts = milestones.setdefault(row["Milestone"], Counter())
        counts[row["Status"]] += 1
    lines = [PROGRESS_START, f"## Progress (updated {today})", "", "| Status | Tasks |", "|---|---|"]
    lines += [f"| {status} | {by_status.get(status, 0)} |" for status in STATUSES]
    lines += ["", "| Milestone | Done | In progress | Total |", "|---|---|---|---|"]
    lines += [f"| {name} | {c['Done']} | {c['In progress']} | {sum(c.values())} |" for name, c in milestones.items()]
    lines += ["", PROGRESS_END]
    return lines


def apply_md(path, progress, rows, today):
    raw = Path(path).read_bytes().decode("utf-8")
    eol = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.replace("\r\n", "\n").split("\n")
    result, seen, i = [], set(), 0
    while i < len(lines):
        line = lines[i]
        match = TASK_LINE.match(line)
        if not match or match.group(1) not in progress:
            result.append(line)
            i += 1
            continue
        task = match.group(1)
        row = progress[task]
        seen.add(task)
        result.append(re.sub(r"^- \[[ xX]\]", "- [x]" if row["Status"] == "Done" else "- [ ]", line, count=1))
        i += 1
        while i < len(lines) and lines[i].startswith("  - "):
            body = lines[i]
            if body.startswith("  - **Evidence") or body.startswith("  - **Notes:**"):
                i += 1  # replaced below
                continue
            if body.startswith("  - **Source:**"):
                body = re.sub(r"\*\*(?:Initial status|Status):\*\* [^|]*", f"**Status:** {row['Status']} ", body)
                body = re.sub(r"\*\*Status:\*\* ([^|]*?) +\|", r"**Status:** \1 |", body)
                body = body.rstrip()
                if "**Owner:**" in body:
                    body = re.sub(r"\| \*\*Owner:\*\* [^|]*", f"| **Owner:** {row['Owner']} ", body).rstrip()
                else:
                    body += f" | **Owner:** {row['Owner']}"
                result.append(body + "  ")
                i += 1
                continue
            result.append(body)
            i += 1
        if row["Evidence"]:
            result.append(f"  - **Evidence ({row['Date'] or 'undated'}):** {row['Evidence']}  ")
        if row["Notes"]:
            result.append(f"  - **Notes:** {row['Notes']}  ")
    missing = set(progress) - seen
    if missing:
        raise TrackerError(f"{path}: no such task in the checklist: {', '.join(sorted(missing))}")
    text = "\n".join(result)
    block = "\n".join(_progress_block(rows, today))
    if PROGRESS_START in text:
        text = re.sub(re.escape(PROGRESS_START) + r".*?" + re.escape(PROGRESS_END), lambda _m: block, text, flags=re.S)
    else:
        marker = next((n for n, line in enumerate(text.split("\n")) if line.startswith("> Initial statuses")), None)
        parts = text.split("\n")
        at = (marker + 1) if marker is not None else 3
        parts[at:at] = ["", block]
        text = "\n".join(parts)
    Path(path).write_bytes(text.replace("\n", eol).encode("utf-8"))


# ---- the .xlsx --------------------------------------------------------------------------------------------------------------------------------

def _escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _set_cell(xml, reference, text):
    """`xml` with the text cell `reference` set to `text`. The cell must already be there (the sheet is laid out with every column present)."""
    pattern = re.compile(r'<(?P<p>(?:\w+:)?)c r="' + reference + r'"(?P<s> s="[0-9]+")? t="str"(?:\s*/>|>.*?</(?P=p)c>)', re.S)
    found = pattern.search(xml)
    if not found:
        raise TrackerError(f"the sheet has no text cell {reference}")
    p, s = found.group("p"), found.group("s") or ""
    cell = f'<{p}c r="{reference}"{s} t="str"/>' if not text else f'<{p}c r="{reference}"{s} t="str"><{p}v>{_escape(text)}</{p}v></{p}c>'
    return xml[: found.start()] + cell + xml[found.end():]


def _tasks_sheet_path(zf):
    workbook = zf.read("xl/workbook.xml").decode("utf-8")
    rels = zf.read("xl/_rels/workbook.xml.rels").decode("utf-8")
    sheet = re.search(r'<(?:\w+:)?sheet [^>]*name="Tasks"[^>]*r:id="([^"]+)"', workbook)
    if not sheet:
        raise TrackerError("the workbook has no sheet called Tasks")
    target = re.search(r'<Relationship [^>]*Id="' + re.escape(sheet.group(1)) + r'"[^>]*Target="([^"]+)"', rels) or re.search(
        r'<Relationship [^>]*Target="([^"]+)"[^>]*Id="' + re.escape(sheet.group(1)) + r'"', rels)
    if not target:
        raise TrackerError("could not find the Tasks sheet's file")
    name = target.group(1).lstrip("/")
    return name if name.startswith("xl/") else "xl/" + name


def apply_xlsx(path, progress):
    with zipfile.ZipFile(path) as zf:
        entries = [(info, zf.read(info.filename)) for info in zf.infolist()]
        sheet_name = _tasks_sheet_path(zf)
    out = []
    for info, data in entries:
        if info.filename == sheet_name:
            xml = data.decode("utf-8")
            rows = {}
            for match in re.finditer(r'<(?:\w+:)?c r="A([0-9]+)"[^>]*><(?:\w+:)?v>(DIYA-[0-9]{3})</(?:\w+:)?v>', xml):
                rows[match.group(2)] = match.group(1)
            unknown = set(progress) - set(rows)
            if unknown:
                raise TrackerError(f"{path}: no such task: {', '.join(sorted(unknown))}")
            for task, row in progress.items():
                n = rows[task]
                for column, value in zip("FKLMN", (row["Status"], row["Owner"], row["Date"], row["Evidence"], row["Notes"])):
                    xml = _set_cell(xml, f"{column}{n}", value)
            data = xml.encode("utf-8")
        elif info.filename == "xl/workbook.xml" and b"fullCalcOnLoad" not in data:
            text = data.decode("utf-8")
            prefix = re.search(r"</((?:\w+:)?)workbook>", text).group(1)
            text = text.replace(f"</{prefix}workbook>", f'<{prefix}calcPr fullCalcOnLoad="1"/></{prefix}workbook>')
            data = text.encode("utf-8")
        out.append((info, data))
    temporary = Path(str(path) + ".part")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in out:
            zf.writestr(info.filename, data)
    temporary.replace(path)


# ---- the whole thing --------------------------------------------------------------------------------------------------------------------------

def apply(folder, progress_path=PROGRESS, today=None):
    """Write the progress into whichever of the three files are in `folder`. Returns the counts by status. Nothing is written if the progress file is not valid or names a task that is not in a sheet."""
    folder = Path(folder)
    progress = read_progress(progress_path)
    today = today or date.today().isoformat()
    csv_path = folder / CSV_NAME
    if not csv_path.is_file():
        raise TrackerError(f"{csv_path} is not there")
    rows = apply_csv(csv_path, progress)
    if (folder / MD_NAME).is_file():
        apply_md(folder / MD_NAME, progress, rows, today)
    if (folder / XLSX_NAME).is_file():
        apply_xlsx(folder / XLSX_NAME, progress)
    return Counter(row["Status"] for row in rows)


def summary_markdown(progress, rows, today):
    """The page docs/TRACKER.md: counts, what is done and with what evidence, what waits for the owner."""
    by_status = Counter(row["Status"] for row in rows)
    total = len(rows)
    lines = [
        "# Task sheet progress", "",
        f"Updated {today}. The blueprint's task sheet has {total} tasks; the progress is kept in `docs/tracker/progress.csv` and written into the owner's three copies of the sheet by `python scripts/tracker.py apply`.",
        "\"Done\" means the acceptance test in the sheet was met and there is evidence. Anything that touches Google, a phone or another real thing the tests cannot reach stays \"In progress\" until the owner has tried it.", "",
        "| Status | Tasks |", "|---|---|",
    ]
    lines += [f"| {status} | {by_status.get(status, 0)} |" for status in STATUSES]
    by_id = {row["Task ID"]: row for row in rows}
    for title, wanted in (("Done", ("Done",)), ("In progress", ("In progress",)), ("Waiting for the owner", None)):
        chosen = [p for p in progress.values() if (p["Status"] in wanted if wanted else p["Owner"] in ("Dinesh", "Both") and p["Status"] != "Done")]
        if not chosen:
            continue
        lines += ["", f"## {title} ({len(chosen)})", ""]
        for p in chosen:
            lines.append(f"- **{p['Task ID']}** {by_id[p['Task ID']]['Task']}" + (f" ({p['Date']})" if p["Date"] else "") + (f": {p['Evidence']}" if p["Evidence"] and wanted and p["Status"] == "Done" else "") + (f". {p['Notes']}" if p["Notes"] else ""))
    return "\n".join(lines) + "\n"


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog="scripts/tracker.py", description="Keep the task sheet in step with the work.")
    sub = parser.add_subparsers(dest="command", required=True)
    apply_parser = sub.add_parser("apply", help="write the progress into the sheet files in a folder")
    apply_parser.add_argument("--dir", required=True)
    apply_parser.add_argument("--progress", default=str(PROGRESS))
    summary_parser = sub.add_parser("summary", help="counts, and optionally a markdown page")
    summary_parser.add_argument("--dir", required=True)
    summary_parser.add_argument("--progress", default=str(PROGRESS))
    summary_parser.add_argument("--write")
    args = parser.parse_args(argv)
    try:
        if args.command == "apply":
            counts = apply(args.dir, args.progress)
            print("Updated the task sheet: " + ", ".join(f"{status} {counts.get(status, 0)}" for status in STATUSES), file=out)
        else:
            progress = read_progress(args.progress)
            with open(Path(args.dir) / CSV_NAME, encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            text = summary_markdown(progress, rows, date.today().isoformat())
            if args.write:
                Path(args.write).write_bytes(text.encode("utf-8"))
                print(f"Wrote {args.write}", file=out)
            else:
                print(text, file=out)
    except (TrackerError, OSError) as exc:
        print(f"Not done: {exc}", file=out)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
