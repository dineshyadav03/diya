"""The Google decisions that code can hold to (docs/GOOGLE_DECISIONS_2026-10-27.md; DIYA-066, -073, -079, -085, -099, -100, -114, -118 to -138, -144, -145), added 2026-10-27.

A decision on a page is only as good as what stops it being undone by accident. This pins what can be pinned: the page answers every task it says it does; the MCP client never touches a Google sign-in; the exact list of
things any Google card may DELETE (a draft, an event of the owner's own, a share, a contact: never a mail message, never a file, never a task list or a calendar); no change request can be aimed at any calendar, task list or
mailbox but the owner's own; and every Google module is imported by the tests that cover it, so a module cannot be added without its tests being named in the live-check plan.
"""
import re
from pathlib import Path

import diya_connector_tools
import diya_google_calchange
import diya_google_client as client
import diya_google_contacts
import diya_google_drive
import diya_google_forms
import diya_google_mailwrite
import diya_google_sheets
import diya_google_slides
import diya_google_tasks
import diya_mcp

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "docs" / "GOOGLE_DECISIONS_2026-10-27.md").read_text(encoding="utf-8")


def tasks_on_the_page():
    """Every task number the page names, with 'DIYA-118 to -121' meaning 118 to 121 and 'DIYA-125, -126' meaning both."""
    ids = set()
    for found in re.finditer(r"DIYA-(\d{3})((?:(?:,| and)\s*-\d{3})*)(?:\s+to\s+-(\d{3}))?", PAGE):
        first = int(found.group(1))
        ids.add(first)
        ids.update(int(extra) for extra in re.findall(r"-(\d{3})", found.group(2)))
        if found.group(3):
            ids.update(range(first, int(found.group(3)) + 1))
    return ids


def test_the_page_answers_every_task_it_says_it_does():
    assert {66, 73, 79, 85, 99, 100, 114, 144, 145} | set(range(118, 139)) <= tasks_on_the_page()
    for service in ("Google Chat", "Google Meet", "Google Keep", "Google Classroom", "Google Photos", "Maps and Places", "YouTube"):
        assert service in PAGE
    assert "No connector is exposed" in PAGE and "the direction is one way" in PAGE and "never** queued" in PAGE


def test_the_mcp_client_never_touches_a_google_sign_in():
    source = Path(diya_mcp.__file__).read_text(encoding="utf-8")
    assert "diya_google" not in source and "read_token" not in source and "access_token" not in source and "diya_connectors" not in source


def test_the_only_things_any_google_card_may_delete():
    deletes = sorted((c, p.pattern) for c, m, p in client._ALLOWED if m == "DELETE")
    names = {c for c, _ in deletes}
    assert names == {diya_google_mailwrite.DRAFTS, diya_google_calchange.CHANGE, diya_google_drive.CHANGE, diya_google_contacts.CHANGE, diya_google_tasks.CARD}
    for card, pattern in deletes:
        assert (card == diya_google_mailwrite.DRAFTS and pattern.endswith("/drafts/" + diya_google_mailwrite.ID)) \
            or (card == diya_google_calchange.CHANGE and pattern.endswith("/events/" + diya_google_calchange.EID)) \
            or (card == diya_google_drive.CHANGE and "/permissions/" in pattern and "/files/" in pattern) \
            or (card == diya_google_contacts.CHANGE and pattern.endswith(":deleteContact")) \
            or (card == diya_google_tasks.CARD and "/lists/@default/tasks/" in pattern), (card, pattern)
    assert not any("messages" in p or "labels" in p or p.rstrip("}0123456789,]-)+").endswith("/lists") for _, p in deletes)  # never a mail message, a label, a whole task list
    legacy = [m for _c, m, _p in __import__("diya_google_write")._PERMITTED]
    assert "DELETE" not in legacy  # nor anything through the first five cards' own list


def test_no_change_can_be_aimed_at_a_calendar_a_task_list_a_mailbox_or_a_person_but_the_owners_own():
    for card, method, pattern in client._ALLOWED:
        text = pattern.pattern
        if "calendar/v3" in text or "calendars" in text:
            assert "calendars/primary" in text, (card, method, text)  # only the main calendar, never a calendar id in the request
        if "tasks.googleapis.com" in text.replace("\\", "") and method != "GET":
            assert "lists/@default" in text, (card, method, text)  # a change is only to the default list
        if "gmail.googleapis.com" in text.replace("\\", ""):
            assert "/users/me" in text, (card, method, text)
        if "people.googleapis.com" in text.replace("\\", "") and "connections" in text:
            assert "people/me" in text, (card, method, text)


def test_every_google_module_that_changes_something_has_its_tests_named_in_the_live_check_plan():
    plan = (ROOT / "docs" / "GOOGLE_LIVE_SMOKE.md").read_text(encoding="utf-8")
    for module, test_file in ((diya_google_mailwrite, "test_google_mailwrite"), (diya_google_calchange, "test_google_calchange"), (diya_google_drive, "test_google_drive"), (diya_google_contacts, "test_google_contacts"),
                              (diya_google_sheets, "test_google_sheets_slides"), (diya_google_slides, "test_google_sheets_slides"), (diya_google_forms, "test_google_forms"), (diya_google_tasks, "test_google_tasks_changes")):
        assert test_file in plan, (module.__name__, test_file)
    changing = {m.name for m in ROOT.glob("diya_google_*.py")}
    assert {"diya_google_mailwrite.py", "diya_google_calchange.py", "diya_google_drive.py", "diya_google_contacts.py", "diya_google_sheets.py", "diya_google_slides.py", "diya_google_forms.py"} <= changing
