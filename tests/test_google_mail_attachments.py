"""Attachments in the mail look-through: listed by name, type and size, and flagged when risky; never downloaded, opened or described by their contents (diya_google_mail.attachments_of; DIYA-078; docs/GOOGLE_CHANGES.md),
added 2026-10-26.

What this proves: an attachment is found at any depth of a message, with only its name (cleaned and cut), type and size; a file that can run code (an executable, a script, a macro document, a disk image) is flagged "dangerous"
and an archive "archive", also when it hides behind a second extension; the report and the note for the model carry the names and the warning and never a byte of content; and the module has no request that downloads an attachment.
"""
import re
from pathlib import Path

import pytest

import diya_google_mail as gm


def part(name, mime="application/pdf", size=1200, **extra):
    return {"filename": name, "mimeType": mime, "body": {"size": size, "attachmentId": "SECRET-ATTACHMENT-ID"}, **extra}


def test_attachments_are_listed_by_name_type_and_size_at_any_depth():
    payload = {"mimeType": "multipart/mixed", "parts": [{"mimeType": "text/plain", "filename": "", "body": {"data": "aGk="}}, part("report.pdf"), {"mimeType": "multipart/related", "parts": [part("photo.png", "image/png", 3_500_000)]}]}
    found = gm.attachments_of(payload)
    assert [(a["name"], a["type"], a["size"], a["risk"]) for a in found] == [("report.pdf", "application/pdf", 1200, ""), ("photo.png", "image/png", 3_500_000, "")]
    assert "SECRET-ATTACHMENT-ID" not in repr(found)  # nothing about how to fetch it is kept


@pytest.mark.parametrize("name, risk", [
    ("invoice.exe", "dangerous"), ("run.BAT", "dangerous"), ("setup.msi", "dangerous"), ("x.ps1", "dangerous"), ("macro.docm", "dangerous"), ("disk.iso", "dangerous"), ("invoice.pdf.exe", "dangerous"), ("shortcut.lnk", "dangerous"),
    ("photos.zip", "archive"), ("backup.7z", "archive"), ("notes.pdf", ""), ("picture.jpg", ""), ("noextension", ""), ("archive.zip.txt", ""),
])
def test_a_file_that_can_run_code_or_hide_it_is_flagged_by_its_last_extension(name, risk):
    assert gm.attachments_of(part(name))[0]["risk"] == risk


def test_a_hostile_name_is_cleaned_and_cut_and_a_message_with_many_has_a_limit():
    found = gm.attachments_of(part("evil\u202e\x1b[31m" + "x" * 300 + ".pdf"))
    assert len(found[0]["name"]) <= 120 and "\u202e" not in found[0]["name"] and "\x1b" not in found[0]["name"] and "\\u202e" in found[0]["name"]  # cut at 80 characters, and a hidden character is shown as its visible escape
    assert len(gm.attachments_of({"parts": [part(f"f{n}.txt") for n in range(40)]})) == gm.MAX_ATTACHMENTS


def test_a_size_that_is_not_a_number_is_unknown_and_nothing_else_breaks():
    assert gm.attachments_of(part("a.pdf", size="huge"))[0]["size"] is None and gm.attachments_of(part("a.pdf", size=True))[0]["size"] is None
    assert gm.attachments_of(None) == [] and gm.attachments_of({"parts": "nope"}) == []


def test_the_line_names_the_files_and_warns_about_the_risky_ones():
    line = gm.attachments_line(gm.attachments_of({"parts": [part("report.pdf", size=120_000), part("invoice.exe", "application/x-msdownload", 40), part("pics.zip", "application/zip", 5_000_000)]}))
    assert line.startswith("Attachments (names and sizes only; never opened): report.pdf (application/pdf, 117 KB); invoice.exe (application/x-msdownload, 40 bytes) - a kind of file that can run code: never open it; pics.zip")
    assert "an archive that can hide such a file" in line and gm.attachments_line([]) == ""


def test_the_report_and_the_note_for_the_model_carry_the_warning_and_no_content():
    evidence = {"query": "q", "described": "from bank", "limits": [], "requests": 1,
                "messages": [{"from": "bank", "subject": "Statement", "date": "Mon", "snippet": "See attached.", "body": "See the attached statement.", "attachments": gm.attachments_of({"parts": [part("statement.exe")]})}]}
    report, note = gm.render(evidence), gm.explain_note(evidence, "PROMPT")
    assert "Attachments (names and sizes only; never opened): statement.exe" in report and "never open it" in report
    assert "statement.exe" in note and "never open it" in note and "SECRET" not in report + note


def test_no_request_the_mail_module_makes_can_download_an_attachment():
    source = (Path(gm.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"attachments/|/attachments|attachmentId\s*[=:]\s*['\"]|messages/[^'\"]*attachments", source) and "alt=media" not in source
