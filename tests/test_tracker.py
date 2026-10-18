"""The task sheet updater (scripts/tracker.py, docs/TRACKER.md), added 2026-10-18.

What this proves, on small sheets built the way the owner's are (a .csv with a byte order mark and CRLF line endings, a checklist .md, and an .xlsx whose cells are text with a prefixed namespace):
the progress file is checked (a status outside the list, a "Done" with no evidence, an unknown owner, a bad date are refused and nothing is written); the three files end up saying the same thing;
a task not in the progress file is left exactly as it was; the checklist's box is ticked only for "Done"; the workbook keeps everything else it had (its other sheets, formulas and drop-downs) and is told
to recalculate; a task id that is not in the sheet is refused before anything is written; and applying twice gives the same files.
"""
import csv
import importlib.util
import io
import pathlib
import zipfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("tracker", ROOT / "scripts" / "tracker.py")
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)

HEADER = ["Task ID", "Milestone", "Workstream", "Priority", "Task", "Status", "Definition of done / acceptance", "Source references", "Dependencies", "Estimate", "Owner", "Target date", "Evidence / PR / test", "Notes"]
TASKS = [
    ("DIYA-001", "F0 — Baseline", "Pin the SHA"),
    ("DIYA-002", "F0 — Baseline", "Compare the audits, with a comma, and \"quotes\""),
    ("DIYA-003", "F1 — Reliability", "Rerun the tests"),
]


def csv_bytes():
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(HEADER)
    for task_id, milestone, title in TASKS:
        writer.writerow([task_id, milestone, "Repo", "P0", title, "Needs verification", "Done when it is done.", "Part II", "", "M", "", "", "", ""])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


def md_text():
    lines = ["# DIYA — COMPLETE EXECUTION TASK LIST", "", "**Basis:** the blueprint.", "", "> Initial statuses are planning labels only.", "", "## F0 — Baseline — 2 tasks", ""]
    for task_id, _milestone, title in TASKS:
        lines += [f"- [ ] **{task_id} [P0] {title}**  ", "  - **Done when:** Done when it is done.  ", "  - **Source:** Part II | **Initial status:** Needs verification | **Est.:** M"]
    return "\n".join(lines) + "\n"


def sheet_xml():
    def cell(ref, text=None):
        return f'<x:c r="{ref}" s="8" t="str"><x:v>{text}</x:v></x:c>' if text else f'<x:c r="{ref}" s="8" t="str" />'

    rows = ['<x:row r="1">' + "".join(cell(f"{c}1", h.replace("&", "&amp;")) for c, h in zip("ABCDEFGHIJKLMN", HEADER)) + "</x:row>"]
    for n, (task_id, milestone, title) in enumerate(TASKS, 2):
        values = [task_id, milestone, "Repo", "P0", title.replace('"', "&quot;"), "Needs verification", "Done when it is done.", "Part II", None, "M", None, None, None, None]
        rows.append(f'<x:row r="{n}">' + "".join(cell(f"{c}{n}", v) for c, v in zip("ABCDEFGHIJKLMN", values)) + "</x:row>")
    return ('<?xml version="1.0" encoding="utf-8"?><x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheetData>' + "".join(rows)
            + '</x:sheetData><x:dataValidations count="1"><x:dataValidation type="list" sqref="F2:F299"><x:formula1>"Not started,Done"</x:formula1></x:dataValidation></x:dataValidations></x:worksheet>')


def xlsx_bytes():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="utf-8"?><x:workbook xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheets>'
                    '<x:sheet name="Dashboard" sheetId="1" r:id="Rdash" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" />'
                    '<x:sheet name="Tasks" sheetId="2" r:id="Rtasks" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" /></x:sheets></x:workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Type="x" Target="/xl/worksheets/sheet1.xml" Id="Rdash" /><Relationship Type="x" Target="/xl/worksheets/sheet2.xml" Id="Rtasks" /></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml", '<?xml version="1.0"?><x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><x:sheetData><x:row r="1"><x:c r="A1"><x:f>COUNTIF(Tasks!F2:F4,"Done")</x:f><x:v>0</x:v></x:c></x:row></x:sheetData></x:worksheet>')
        zf.writestr("xl/worksheets/sheet2.xml", sheet_xml())
    return buffer.getvalue()


def progress_file(tmp_path, *rows):
    path = tmp_path / "progress.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(tracker.FIELDS)
        writer.writerows(rows)
    return path


@pytest.fixture
def sheets(tmp_path):
    folder = tmp_path / "sheets"
    folder.mkdir()
    (folder / tracker.CSV_NAME).write_bytes(csv_bytes())
    (folder / tracker.MD_NAME).write_bytes(md_text().encode("utf-8"))
    (folder / tracker.XLSX_NAME).write_bytes(xlsx_bytes())
    return folder


GOOD = [("DIYA-001", "Done", "Claude", "2026-10-18", "docs/BASELINE.md", "All recorded."), ("DIYA-003", "In progress", "Both", "2026-10-18", "tests/x.py", "Stand-in only; & <check> it.")]


def read_csv(folder):
    raw = (folder / tracker.CSV_NAME).read_bytes()
    return raw, list(csv.DictReader(io.StringIO(raw[3:].decode("utf-8"), newline="")))


def read_xlsx_cells(folder, sheet="xl/worksheets/sheet2.xml"):
    with zipfile.ZipFile(folder / tracker.XLSX_NAME) as zf:
        return zf.read(sheet).decode("utf-8")


# ---- the progress file -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("row, why", [
    (("DIYA-1", "Done", "Claude", "2026-10-18", "e", ""), "not a task id"),
    (("DIYA-001", "Finished", "Claude", "2026-10-18", "e", ""), "not one of"),
    (("DIYA-001", "Done", "Claude", "2026-10-18", "", ""), "no evidence"),
    (("DIYA-001", "In progress", "Robot", "2026-10-18", "", ""), "owner"),
    (("DIYA-001", "In progress", "Claude", "18/10/2026", "", ""), "date"),
])
def test_a_progress_row_that_breaks_a_rule_is_refused(tmp_path, row, why):
    with pytest.raises(tracker.TrackerError, match=why):
        tracker.read_progress(progress_file(tmp_path, row))


def test_a_later_row_for_the_same_task_replaces_an_earlier_one(tmp_path):
    path = progress_file(tmp_path, ("DIYA-001", "In progress", "Claude", "2026-10-17", "", "started"), ("DIYA-001", "Done", "Claude", "2026-10-18", "docs/x.md", ""))
    assert tracker.read_progress(path)["DIYA-001"]["Status"] == "Done"


def test_a_progress_file_with_the_wrong_columns_is_refused(tmp_path):
    path = tmp_path / "p.csv"
    path.write_text("Task ID,Status\nDIYA-001,Done\n", encoding="utf-8")
    with pytest.raises(tracker.TrackerError, match="columns"):
        tracker.read_progress(path)


# ---- the three files ---------------------------------------------------------------------------------------------------------------------------

def test_the_csv_gets_the_progress_and_keeps_its_byte_order_mark_and_line_endings(sheets, tmp_path):
    tracker.apply(sheets, progress_file(tmp_path, *GOOD), today="2026-10-18")
    raw, rows = read_csv(sheets)
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    by_id = {r["Task ID"]: r for r in rows}
    assert (by_id["DIYA-001"]["Status"], by_id["DIYA-001"]["Owner"], by_id["DIYA-001"]["Target date"], by_id["DIYA-001"]["Evidence / PR / test"]) == ("Done", "Claude", "2026-10-18", "docs/BASELINE.md")
    assert by_id["DIYA-003"]["Notes"] == "Stand-in only; & <check> it."
    assert by_id["DIYA-002"]["Status"] == "Needs verification" and by_id["DIYA-002"]["Notes"] == ""  # not in the progress file: untouched
    assert by_id["DIYA-002"]["Task"] == 'Compare the audits, with a comma, and "quotes"'


def test_the_checklist_ticks_only_done_and_says_the_status_evidence_and_notes(sheets, tmp_path):
    tracker.apply(sheets, progress_file(tmp_path, *GOOD), today="2026-10-18")
    text = (sheets / tracker.MD_NAME).read_text(encoding="utf-8")
    assert "- [x] **DIYA-001 [P0] Pin the SHA**" in text and "- [ ] **DIYA-003 [P0] Rerun the tests**" in text and "- [ ] **DIYA-002 [P0]" in text
    assert "**Status:** Done | **Est.:** M | **Owner:** Claude" in text.replace("  \n", "\n") or "**Status:** Done" in text
    assert "**Evidence (2026-10-18):** docs/BASELINE.md" in text and "**Notes:** Stand-in only; & <check> it." in text
    assert text.count("**Initial status:**") == 1  # DIYA-002 still has its original line
    assert "## Progress (updated 2026-10-18)" in text and "| Done | 1 |" in text and "| In progress | 1 |" in text
    assert "| F0 — Baseline | 1 | 0 | 2 |" in text and "| F1 — Reliability | 0 | 1 | 1 |" in text


def test_the_workbook_gets_the_same_cells_and_keeps_everything_else(sheets, tmp_path):
    tracker.apply(sheets, progress_file(tmp_path, *GOOD), today="2026-10-18")
    xml = read_xlsx_cells(sheets)
    assert '<x:c r="F2" s="8" t="str"><x:v>Done</x:v></x:c>' in xml and '<x:c r="K2" s="8" t="str"><x:v>Claude</x:v></x:c>' in xml
    assert '<x:c r="N4" s="8" t="str"><x:v>Stand-in only; &amp; &lt;check&gt; it.</x:v></x:c>' in xml
    assert '<x:c r="F3" s="8" t="str"><x:v>Needs verification</x:v></x:c>' in xml and '<x:c r="N3" s="8" t="str" />' in xml  # DIYA-002 untouched
    assert "<x:dataValidations" in xml and "COUNTIF" in read_xlsx_cells(sheets, "xl/worksheets/sheet1.xml")
    with zipfile.ZipFile(sheets / tracker.XLSX_NAME) as zf:
        assert 'fullCalcOnLoad="1"' in zf.read("xl/workbook.xml").decode("utf-8") and zf.testzip() is None
        assert [i.filename for i in zf.infolist()] == ["xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"]


def test_applying_twice_gives_the_same_files(sheets, tmp_path):
    path = progress_file(tmp_path, *GOOD)
    tracker.apply(sheets, path, today="2026-10-18")
    first = {name: (sheets / name).read_bytes() for name in (tracker.CSV_NAME, tracker.MD_NAME)}
    first_xml = read_xlsx_cells(sheets)
    tracker.apply(sheets, path, today="2026-10-18")
    assert {name: (sheets / name).read_bytes() for name in first} == first and read_xlsx_cells(sheets) == first_xml


def test_a_changed_status_replaces_the_old_text_in_every_file(sheets, tmp_path):
    tracker.apply(sheets, progress_file(tmp_path, *GOOD), today="2026-10-18")
    later = progress_file(tmp_path, ("DIYA-001", "In progress", "Both", "2026-10-19", "", "reopened"), GOOD[1])
    tracker.apply(sheets, later, today="2026-10-19")
    text = (sheets / tracker.MD_NAME).read_text(encoding="utf-8")
    assert "- [ ] **DIYA-001" in text and "BASELINE.md" not in text and "**Notes:** reopened" in text and "(updated 2026-10-19)" in text and text.count("## Progress") == 1
    assert 'r="F2" s="8" t="str"><x:v>In progress' in read_xlsx_cells(sheets)


def test_a_task_that_is_not_in_the_sheet_is_refused_and_nothing_is_written(sheets, tmp_path):
    before = {name: (sheets / name).read_bytes() for name in (tracker.CSV_NAME, tracker.MD_NAME, tracker.XLSX_NAME)}
    with pytest.raises(tracker.TrackerError, match="no such task"):
        tracker.apply(sheets, progress_file(tmp_path, GOOD[0], ("DIYA-999", "Done", "Claude", "2026-10-18", "e", "")))
    assert {name: (sheets / name).read_bytes() for name in before} == before


def test_the_summary_page_lists_done_with_evidence_and_what_waits_for_the_owner(sheets, tmp_path):
    progress = tracker.read_progress(progress_file(tmp_path, *GOOD, ("DIYA-002", "Not started", "Dinesh", "2026-10-18", "", "Owner decision.")))
    tracker.apply(sheets, progress_file(tmp_path, *GOOD, ("DIYA-002", "Not started", "Dinesh", "2026-10-18", "", "Owner decision.")), today="2026-10-18")
    _raw, rows = read_csv(sheets)
    page = tracker.summary_markdown(progress, rows, "2026-10-18")
    assert "| Done | 1 |" in page and "## Done (1)" in page and "docs/BASELINE.md" in page and "## Waiting for the owner (2)" in page and "Owner decision." in page  # the "Both" task still waits for them too
    assert "## In progress (1)" in page and "Stand-in only" in page


def test_the_command_line_says_what_it_did(sheets, tmp_path):
    out = io.StringIO()
    assert tracker.main(["apply", "--dir", str(sheets), "--progress", str(progress_file(tmp_path, *GOOD))], out=out) == 0
    assert "Done 1" in out.getvalue() and "In progress 1" in out.getvalue()
    out = io.StringIO()
    assert tracker.main(["apply", "--dir", str(tmp_path / "nothing"), "--progress", str(progress_file(tmp_path, *GOOD))], out=out) == 1 and out.getvalue().startswith("Not done:")


def test_the_real_progress_file_is_valid_and_every_done_has_evidence():
    progress = tracker.read_progress()
    assert progress and all(row["Evidence"] for row in progress.values() if row["Status"] == "Done")
    assert all(task.startswith("DIYA-") for task in progress)
