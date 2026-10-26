"""What every tool and flow can do, and what authority it takes: the side-effect catalog and the risk tiers (docs/AUTHORITY_MODEL.md), added 2026-10-18.

    python diya_catalog.py write     # rewrite docs/AUTHORITY_MODEL.md from this file
    python diya_catalog.py check     # say whether that document is current

The blueprint asks that no tool can exist without saying what it touches, how far it can be undone, and who must agree (DIYA-036, -037, -038). This file is that statement, in code, and
tests/test_catalog.py is what keeps it true: a tool the model can be offered, a kind of action, or a flow the code decides on that has no entry here fails the test; a tier that does not match the
way the tool works fails it; and a module that makes an outbound call that can change something outside this computer must be named here, with the reason, or the test fails. A new capability is
therefore a decision someone made on purpose, not a side effect of adding a function.

The tiers (the blueprint's Part V, 14.7):

0  reads. Looks at something and changes nothing outside Diya's own records: files in the allowed folders, the notes, the weather, a search, mail, a calendar.
1  reversible local writes. Changes Diya's own database in a way the person can see and undo: a reminder, a task on Diya's own list, a fact in memory.
2  reversible remote writes. Adds something private to one of the person's own accounts: an event, a task, a folder, a document. Only ever PROPOSED by the model; the owner approves each one,
   exactly as shown, and Diya cannot remove it afterwards (undoing is by hand in the service). The one exception, chosen by the owner on 2026-10-26 (diya_autoapprove.py): the four Google additions in
   AUTO_KINDS may be switched, one by one, to be done straight away when the owner asks for them in their own message and nothing outside that message was read first; everything else still waits.
3  external-facing, or not undoable. Reaches other people (sends a message, invites a guest, shares a file) or removes something Diya cannot bring back (deletes a task). Only ever PROPOSED; the owner approves each one, exactly as
   shown, with every recipient and what is lost on the card, and it is never done straight away (2026-10-26, docs/GOOGLE_CHANGES.md). Built one kind at a time as the owner connects the card it needs.
4  destructive or privileged. Deletes at scale, changes account settings, shares publicly. Not built, and denied by default.

Importing this module has no side effects.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

TIERS = {
    0: "reads: looks, changes nothing outside Diya's own records",
    1: "reversible local write: changes Diya's own database where the person can see and undo it",
    2: "reversible remote write: adds something private to the person's own account, or changes it in a way that can be put back by hand; proposed only, the owner approves each one (the four Google additions the owner may switch to 'straight away' are the one exception)",
    3: "external-facing or not undoable: reaches other people (send, invite, share) or removes what Diya cannot bring back; proposed only, the owner approves each one, and it is never done straight away",
    4: "destructive or privileged: delete at scale, account settings, public sharing. Not built; denied by default",
}


@dataclass(frozen=True)
class Entry:
    name: str
    type: str  # "tool" (the model calls it), "proposal" (the model proposes; the owner approves), "flow" (code decides to do it because of what the person said)
    tier: int
    effect: str  # one plain sentence
    network: str  # "none", or the hosts it can reach
    reversible: str  # "n/a" for a read; otherwise how it is undone
    approval: str  # "none" or "owner approves each action"
    untrusted_output: bool  # does what comes back contain words someone else wrote (so it must never be obeyed)?
    needs: str = ""  # the connector or setting it needs, in words
    connector: str = ""  # the connector's name (diya_connectors), so the permissions page can say what each connection was last used for


E = Entry
CATALOG = {e.name: e for e in (
    E("list_files", "tool", 0, "lists files and folders inside the allowed folders", "none", "n/a", "none", True),
    E("search_notes", "tool", 0, "searches the person's notes folder", "none", "n/a", "none", True),
    E("get_weather", "tool", 0, "asks a weather service for the weather in a place", "the allowed weather host", "n/a", "none", False),
    E("web_search", "tool", 0, "searches the web for a question", "the search service", "n/a", "none", True),
    E("add_reminder", "tool", 1, "saves a reminder in Diya's own database", "none", "the person ticks it off or deletes it on the Reminders page", "none", False),
    E("list_reminders", "tool", 0, "lists Diya's reminders", "none", "n/a", "none", False),
    E("add_task", "tool", 1, "adds a task to Diya's own to-do list", "none", "the person ticks it off on the Tasks page", "none", False),
    E("list_tasks", "tool", 0, "lists Diya's own tasks", "none", "n/a", "none", False),
    E("search_home_assistant", "tool", 0, "searches the states of the person's Home Assistant", "the person's own Home Assistant address", "n/a", "none", True, "Home Assistant connected", "home_assistant"),
    E("search_notion", "tool", 0, "searches the person's connected Notion", "api.notion.com", "n/a", "none", True, "Notion connected", "notion"),
    E("list_todoist_tasks", "tool", 0, "lists open tasks in Todoist", "api.todoist.com", "n/a", "none", True, "Todoist connected", "todoist"),
    E("list_calendar_events", "tool", 0, "lists the next events on the person's Google Calendar", "www.googleapis.com", "n/a", "none", True, "Google Calendar connected", "google_calendar"),
    E("list_google_tasks", "tool", 0, "lists open Google Tasks", "tasks.googleapis.com", "n/a", "none", True, "Google Tasks connected", "google_tasks"),
    E("propose_rename_drive_file", "proposal", 2, "proposes renaming one file or folder that Diya made in the person's Drive", "www.googleapis.com (only when approved)", "by hand in Google Drive: rename it back", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_move_drive_file", "proposal", 2, "proposes moving one file that Diya made into a folder that Diya made, showing where it comes from and goes to", "www.googleapis.com (only when approved)", "by hand in Google Drive: move it back (the card says where from)", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_trash_drive_file", "proposal", 2, "proposes putting one file (or an empty folder) that Diya made in the Drive bin", "www.googleapis.com (only when approved)", "Drive keeps it in the bin for 30 days; bring it back there or by asking Diya", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_restore_drive_file", "proposal", 2, "proposes bringing one file or folder that Diya made back from the Drive bin", "www.googleapis.com (only when approved)", "put it in the bin again", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_share_drive_file", "proposal", 3, "proposes sharing one file that Diya made with one address the person typed, as viewer, commenter or editor; Google emails them", "www.googleapis.com (only when approved)", "stop sharing it, but the person has been told", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_unshare_drive_file", "proposal", 2, "proposes stopping the sharing of one file that Diya made with one address the person typed", "www.googleapis.com (only when approved)", "share it again", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_edit_google_doc", "proposal", 2, "proposes adding text to the end of a Google Doc that Diya made, or changing words in it, guarded by the document's version", "docs.googleapis.com (only when approved)", "by hand in the Doc's version history", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_todoist_task", "proposal", 2, "proposes a task in the person's Todoist Inbox", "api.todoist.com (only when approved)", "by hand in Todoist: Diya cannot remove it", "owner approves each action", False, "Todoist connected", "todoist"),
    E("propose_calendar_event", "proposal", 2, "proposes an event, just for the person, on their Google Calendar", "www.googleapis.com (only when approved)", "by hand in Google Calendar: Diya cannot remove it", "owner approves each action", False, "Google Calendar (add events) connected", "google_calendar_edit"),
    E("propose_google_task", "proposal", 2, "proposes a task in the person's Google Tasks", "tasks.googleapis.com (only when approved)", "by hand in Google Tasks: Diya cannot remove it", "owner approves each action", False, "Google Tasks connected", "google_tasks"),
    E("propose_drive_folder", "proposal", 2, "proposes a new folder at the top of the person's Google Drive", "www.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive and Docs connected", "google_drive_files"),
    E("propose_complete_google_task", "proposal", 2, "proposes marking one of the person's open Google Tasks as done", "tasks.googleapis.com (only when approved)", "by hand in Google Tasks: it can be marked open again there", "owner approves each action", False, "Google Tasks connected", "google_tasks"),
    E("propose_update_google_task", "proposal", 2, "proposes renaming a Google Task or changing its notes or due day", "tasks.googleapis.com (only when approved)", "by hand in Google Tasks: Diya does not keep the old words", "owner approves each action", False, "Google Tasks connected", "google_tasks"),
    E("propose_move_google_task", "proposal", 2, "proposes moving a Google Task to the top of the list or under another task", "tasks.googleapis.com (only when approved)", "by hand in Google Tasks", "owner approves each action", False, "Google Tasks connected", "google_tasks"),
    E("propose_delete_google_task", "proposal", 3, "proposes deleting one of the person's open Google Tasks", "tasks.googleapis.com (only when approved)", "Diya cannot bring it back", "owner approves each action", False, "Google Tasks connected", "google_tasks"),
    E("propose_update_calendar_event", "proposal", 2, "proposes renaming, moving or changing the length of one of the person's own calendar events that has no guests", "www.googleapis.com (only when approved)", "by hand in Google Calendar: Diya does not keep the old name or time", "owner approves each action", False, "Google Calendar (change events) connected", "google_calendar_change"),
    E("propose_cancel_calendar_event", "proposal", 3, "proposes cancelling one of the person's own calendar events that has no guests", "www.googleapis.com (only when approved)", "Diya cannot bring it back", "owner approves each action", False, "Google Calendar (change events) connected", "google_calendar_change"),
    E("propose_invite_calendar_event", "proposal", 3, "proposes inviting addresses the person typed to one of their own events; Google Calendar emails the guests", "www.googleapis.com (only when approved)", "an invitation that is sent cannot be taken back", "owner approves each action", False, "Google Calendar (guests) connected", "google_calendar_guests"),
    E("propose_rsvp_calendar_event", "proposal", 3, "proposes accepting, declining or saying maybe to an invitation the person was sent; the organiser is told", "www.googleapis.com (only when approved)", "the answer can be changed by answering again, but the organiser has been told", "owner approves each action", False, "Google Calendar (guests) connected", "google_calendar_guests"),
    E("propose_repeating_calendar_event", "proposal", 2, "proposes an event that repeats (daily, weekly, monthly or yearly, 2 to 52 times), just for the person, on their Google Calendar", "www.googleapis.com (only when approved)", "by hand in Google Calendar: Diya cannot remove it", "owner approves each action", False, "Google Calendar (add events) connected", "google_calendar_edit"),
    E("propose_add_contact", "proposal", 2, "proposes adding a contact with an email address or number the person typed", "people.googleapis.com (only when approved)", "by hand in Google Contacts: delete it there", "owner approves each action", False, "Google Contacts (change) connected", "google_contacts_change"),
    E("propose_update_contact", "proposal", 2, "proposes adding an email address or number the person typed to one contact", "people.googleapis.com (only when approved)", "by hand in Google Contacts: remove it there", "owner approves each action", False, "Google Contacts (change) connected", "google_contacts_change"),
    E("propose_delete_contact", "proposal", 3, "proposes deleting one contact", "people.googleapis.com (only when approved)", "Diya cannot bring it back", "owner approves each action", False, "Google Contacts (change) connected", "google_contacts_change"),
    E("propose_contact_group", "proposal", 2, "proposes putting a contact in one of the person's own contact groups, or taking them out", "people.googleapis.com (only when approved)", "do the opposite", "owner approves each action", False, "Google Contacts (change) connected", "google_contacts_change"),
    E("propose_google_sheet", "proposal", 2, "proposes a new Google Sheet, optionally with rows of plain values (nothing can become a formula)", "sheets.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_sheet_rows", "proposal", 2, "proposes adding rows to the end of a sheet that Diya made", "sheets.googleapis.com (only when approved)", "by hand in the sheet's version history", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_sheet_cells", "proposal", 2, "proposes writing plain values into cells of a sheet that Diya made, showing what is there now; replacing filled cells needs the person's word replace or overwrite", "sheets.googleapis.com (only when approved)", "by hand in the sheet's version history", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_sheet_header", "proposal", 2, "proposes making the first row of a sheet that Diya made bold and keeping it in view", "sheets.googleapis.com (only when approved)", "by hand in Google Sheets", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_google_slides", "proposal", 2, "proposes a new Google Slides deck from an outline shown whole on the card", "slides.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_add_slides", "proposal", 2, "proposes adding slides from an outline to a deck that Diya made", "slides.googleapis.com (only when approved)", "by hand in the deck's version history", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_google_form", "proposal", 2, "proposes a new Google Form with the questions shown on the card; it is not shared with anyone", "forms.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_form_questions", "proposal", 2, "proposes adding questions to a form that Diya made", "forms.googleapis.com (only when approved)", "by hand in Google Forms", "owner approves each action", False, "Google Drive (change) connected", "google_drive_change"),
    E("propose_gmail_draft", "proposal", 2, "proposes saving (or replacing) a draft email in the person's Drafts folder; a draft is not sent", "gmail.googleapis.com (only when approved)", "by hand in Gmail: the draft can be edited or deleted there", "owner approves each action", False, "Gmail: drafts connected", "google_mail_drafts"),
    E("propose_discard_gmail_draft", "proposal", 3, "proposes throwing away one draft email", "gmail.googleapis.com (only when approved)", "Diya cannot bring it back", "owner approves each action", False, "Gmail: drafts connected", "google_mail_drafts"),
    E("propose_send_gmail", "proposal", 3, "proposes sending a new email to an address the person typed", "gmail.googleapis.com (only when approved)", "an email that is sent cannot be taken back", "owner approves each action", False, "Gmail: send connected", "google_mail_send"),
    E("propose_reply_gmail", "proposal", 3, "proposes replying to one email the person names, to the person who wrote it", "gmail.googleapis.com (only when approved)", "an email that is sent cannot be taken back", "owner approves each action", False, "Gmail: send and Gmail connected", "google_mail_send"),
    E("propose_forward_gmail", "proposal", 3, "proposes forwarding one email the person names to an address they typed (text only)", "gmail.googleapis.com (only when approved)", "an email that is sent cannot be taken back", "owner approves each action", False, "Gmail: send and Gmail connected", "google_mail_send"),
    E("propose_organise_gmail", "proposal", 2, "proposes filing one email the person names: archive, read or unread, star, one of their own labels, the bin and back", "gmail.googleapis.com (only when approved)", "by hand in Gmail: every one of these can be put back (the bin keeps mail for 30 days)", "owner approves each action", False, "Gmail: organise connected", "google_mail_organise"),
    E("propose_google_doc", "proposal", 2, "proposes a new Google Doc with at most a line of text", "docs.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive and Docs connected", "google_drive_files"),
    E("read_contacts", "flow", 0, "answers 'what is Maya's email?' from the person's Google Contacts, written by code with no model", "people.googleapis.com", "n/a", "none", True, "Google Contacts (read) connected", "google_contacts_read"),
    E("read_drive", "flow", 0, "looks through the person's Google Drive when they ask (a search by name, a file as numbered paragraphs, a file's earlier versions); the answer is written by a model with no tools", "www.googleapis.com", "n/a", "none", True, "Google Drive (read) connected", "google_drive_read"),
    E("read_mail", "flow", 0, "looks through the person's Gmail when they ask; the answer is written by a model with no tools", "gmail.googleapis.com", "n/a", "none", True, "Gmail connected", "google_mail"),
    E("mail_write_refused", "flow", 0, "answers a request to send, change or delete mail that cannot be proposed (the card for it is not connected, or it is for many emails at once) with the plain fact, and never lets the model guess", "none", "n/a", "none", False),
    E("study_repo", "flow", 0, "reads a public GitHub repository the person names and shows the evidence", "api.github.com, raw.githubusercontent.com", "n/a", "none", True),
    E("read_calendar", "flow", 0, "reads the person's Google Calendar for the days they ask about and writes the list itself, with no model", "www.googleapis.com", "n/a", "none", True, "Google Calendar connected", "google_calendar"),
    E("explain_connections", "flow", 0, "says which accounts are connected and what each can and cannot do, from the connection record and not from the model", "none", "n/a", "none", False),
    E("explain_memory", "flow", 0, "says where a remembered fact came from, from the memory's own record", "none", "n/a", "none", False),
    E("use_playbook", "flow", 0, "adds the steps of a playbook the person wrote themselves (named in the message or close in meaning) to the turn as their instructions; grants no tool and skips no approval", "none", "n/a", "none", False),
)}
# A flow shares a name with a tool when the same thing is done in code instead of by the model's choice: it is journalled under that name with kind="flow".
SHARED_FLOW_NAMES = frozenset({"search_notes", "web_search"})
# Tools of MCP servers the person added: not listed one by one (the person approves each tool, read-only, pinned: docs/MCP_DESIGN.md).
MCP_PREFIX = "mcp_"

# The modules that make an outbound call which can send something out (POST/PUT/PATCH/DELETE). Anything else that does so must be added here with its reason.
OUTBOUND_WRITERS = {
    "diya_connector_tools.py": "Notion search is a POST that only reads; the Todoist task is created only inside todoist_add_task_execute, which diya_actions.run calls after the owner approves",
    "diya_google_calendar.py": "Google's own OAuth endpoints: the token exchange and refresh, and revoking the permission",
    "diya_google_write.py": "the approved Google writes: every request goes through _send, called only from the kinds' execute functions",
    "diya_google_client.py": "the approved changes to the newer Google cards (mail drafts and sending, calendar edits, Drive, Docs, Sheets, Slides, contacts, forms): every request goes through send, called only from the kinds' execute functions",
    "diya_push.py": "web push to the person's own subscribed devices",
    "diya_telegram.py": "the person's own Telegram bot",
    "diya_warm.py": "the local Ollama, to keep the chat model loaded",
}


# The Rule of Two (Meta) and the lethal trifecta (Simon Willison), kept as code (RESEARCH.md entry 17, DIYA-281, 2026-10-21). An agent that at once (A) reads words other people wrote, (B) reaches the
# person's private data and (C) can send something out or change something, can be talked into stealing or damaging by a sentence hidden in what it reads. Each entry below is given its legs; a tool
# with all three must be a proposal the owner approves action by action, and the words a model can send to a service the owner does not control are listed here by name so that a new one is a decision.
PRIVATE_DATA = frozenset({
    "list_files", "search_notes", "list_reminders", "list_tasks", "search_home_assistant", "search_notion", "list_todoist_tasks", "list_calendar_events", "list_google_tasks", "read_drive", "read_contacts", "read_mail",
    "explain_memory", "use_playbook", "read_calendar",
})
# Tools whose arguments are words the MODEL chose and that leave this computer for a service the owner does not control (a free-text channel out, however harmless it looks).
FREE_TEXT_OUT = {
    "web_search": "the words of the query go to the search service",
    "get_weather": "the place name goes to the weather service",
}


def legs(entry):
    """(A) untrusted words come in, (B) the person's private data is reached, (C) something can go out or change at a service."""
    return {"untrusted": bool(entry.untrusted_output), "private": entry.name in PRIVATE_DATA, "outward": entry.tier >= 2 or entry.name in FREE_TEXT_OUT}


def leg_count(entry):
    return sum(legs(entry).values())


def rule_of_two_violations(catalog=None):
    """What breaks the rule in `catalog` (default: the real one), in words: an entry with all three legs that is not a proposal the owner approves action by action; a tool that reaches a service
    with no connector (so not the owner's own account) and is not declared in FREE_TEXT_OUT; a connector read that is not counted as private data."""
    catalog = CATALOG if catalog is None else catalog
    found = []
    for entry in catalog.values():
        if leg_count(entry) == 3 and not (entry.type == "proposal" and entry.approval == "owner approves each action"):
            found.append(f"{entry.name} has all three legs and is not a proposal the owner approves each time")
        if entry.type == "tool" and entry.network != "none" and not entry.connector and entry.name not in FREE_TEXT_OUT:
            found.append(f"{entry.name} sends the model's words to a service that is not the owner's own account and is not declared in FREE_TEXT_OUT")
        if entry.connector and entry.tier == 0 and entry.name not in PRIVATE_DATA:
            found.append(f"{entry.name} reads through a connector (the owner's account) and is not counted as private data")
    return found


def session_exposure():
    """What one chat session holds side by side, because the model may call any tool in the same turn: the tools that bring private data AND untrusted words in (A and B), and the tools that send
    free text out without the owner approving it (C, ungated). A chat session that offers both has all three legs even though no single tool does: this is the one open accounting, stated in
    docs/AUTHORITY_MODEL.md, and the test pins it so it cannot grow unseen."""
    readers = sorted(e.name for e in CATALOG.values() if e.type == "tool" and e.name in PRIVATE_DATA and e.untrusted_output)
    senders = sorted(name for name in FREE_TEXT_OUT if CATALOG[name].approval == "none")
    return readers, senders


def render():
    """docs/AUTHORITY_MODEL.md, from this file."""
    lines = [
        "# What every tool can do, and who must agree (generated by `python diya_catalog.py write`; do not edit by hand)",
        "",
        "Written 2026-10-18 for the blueprint's DIYA-036, -037 and -038. The source is `diya_catalog.py`; `tests/test_catalog.py` fails if a tool, a kind of action or a flow exists that is not listed here,"
        " if a tier does not match how the tool works, or if a new part of the code starts making outbound writes without being named.",
        "",
        "## The risk tiers", "",
        "| Tier | Meaning |", "|---|---|",
    ]
    lines += [f"| {tier} | {text} |" for tier, text in TIERS.items()]
    lines += [
        "",
        "## The rule that makes it a broker",
        "",
        "A **tool** the model calls can read (tier 0) or change Diya's own records (tier 1). It cannot change anything at a service. A **proposal** is the only way the model can ask for a change at a service (tier 2 and up): it writes a pending card, "
        "the owner approves exactly what is shown, and only then does the code run it, once (`diya_actions.py`). The model has no tool whose parameters name an address, a header or a credential. What comes back from "
        "anywhere outside is data, never an instruction (`untrusted` below), and is read by a model with no tools whenever it is mail, a repository or notes.",
        "",
        "## The kill switch",
        "",
        "One press of **Pause Diya** on the Status page (or `POST /api/pause`) stops the three ways Diya acts on her own: an approved action is not run (and \"Approve\" is refused, leaving the action waiting), "
        "scheduled automations do not run, and she does not write first. Chat, reading, approving later and editing memory still work; reminders still fire, because they are the person's own alarms (`docs/PAUSE_DESIGN.md`).",
        "",
        "## Every tool, proposal and flow", "",
        "| Name | Type | Tier | What it does | Reaches | Undo | Approval | Output may hold other people's words | Needs |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in CATALOG.values():
        lines.append(
            f"| `{entry.name}` | {entry.type} | {entry.tier} | {entry.effect} | {entry.network} | {entry.reversible} | {entry.approval} | {'yes' if entry.untrusted_output else 'no'} | {entry.needs or '-'} |"
        )
    lines += [
        "",
        f"Tools of MCP servers the person added (`{MCP_PREFIX}...`) are not listed one by one: each is read-only, approved by the person one at a time, and pinned (`docs/MCP_DESIGN.md`).",
        "",
        "## The parts of the code that can send something out", "",
        "| Module | Why it may |", "|---|---|",
    ]
    lines += [f"| `{module}` | {why} |" for module, why in OUTBOUND_WRITERS.items()]
    readers, senders = session_exposure()
    lines += [
        "",
        "## The Rule of Two, tool by tool (`legs()` in `diya_catalog.py`)",
        "",
        "Meta's Rule of Two and Simon Willison's lethal trifecta say an agent should not, in one session, (A) read words other people wrote, (B) reach the person's private data and (C) send something out or change something,"
        " because a sentence hidden in what it reads can then steal or damage. Below, each entry's legs; `tests/test_rule_of_two.py` fails if any entry has all three without being a proposal the owner approves action by action,"
        " or if a tool that sends the model's own words to a service the owner does not control is not listed.",
        "",
        "| Name | A: untrusted words in | B: private data | C: can send out / change | Legs |", "|---|---|---|---|---|",
    ]
    for entry in CATALOG.values():
        have = legs(entry)
        lines.append(f"| `{entry.name}` | {'yes' if have['untrusted'] else '-'} | {'yes' if have['private'] else '-'} | {'yes' if have['outward'] else '-'} | {leg_count(entry)} |")
    lines += [
        "",
        f"**No single entry has all three.** The one open accounting is the session: a chat offers {', '.join('`' + r + '`' for r in readers)} (private data and untrusted words, legs A and B) next to "
        f"{', '.join('`' + n + '`' for n in senders)} (free text out, leg C, no approval), so all three legs exist in one turn even though no tool has them alone. What stands in the way: "
        "the model has no tool that names an address, a header or a credential; what a service returns is data, never an instruction; mail, repositories and notes are read by a model with no tools; "
        "every write to an account is a proposal the owner approves exactly as shown, and the tools that ran earlier in the turn are shown on the card as a warning. What is not closed: a query or a place name can carry words "
        "the model took from what it read. Closing it would mean approving each search, or a search that sees no private text; neither is built, and it is a decision for the owner, not a default.",
    ]
    lines += [
        "",
        "## Not built (so nothing here can do it)",
        "",
        "Sending, drafting, replying to or deleting mail; inviting anyone to an event; sharing a file; changing or deleting anything that already exists in a Google account; account settings. Each would be tier 3 or 4 and would need"
        " its own entry, its own approval wording and its own tests before it could exist (`docs/GOOGLE_WRITE_DESIGN.md`, \"Next\").",
        "",
    ]
    return "\n".join(lines)


DOC = Path(__file__).resolve().parent / "docs" / "AUTHORITY_MODEL.md"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["write"]:
        DOC.write_bytes(render().encode("utf-8"))
        print(f"Wrote {DOC}")
        return 0
    if argv == ["check"]:
        current = DOC.read_bytes().decode("utf-8") if DOC.exists() else ""
        print("docs/AUTHORITY_MODEL.md is current." if current == render() else "docs/AUTHORITY_MODEL.md is out of date: run python diya_catalog.py write")
        return 0 if current == render() else 1
    print("usage: python diya_catalog.py write | check")
    return 2


if __name__ == "__main__":
    sys.exit(main())
