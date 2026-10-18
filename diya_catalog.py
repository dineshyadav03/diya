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
   exactly as shown, and Diya cannot remove it afterwards (undoing is by hand in the service).
3  external-facing. Reaches other people: sends a message, invites a guest, shares a file. Not built; each would need exact per-action approval at the least.
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
    2: "reversible remote write: adds something private to the person's own account; proposed only, the owner approves each one",
    3: "external-facing: reaches other people (send, invite, share). Not built",
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
    needs: str = ""  # the connector or setting it needs


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
    E("search_home_assistant", "tool", 0, "searches the states of the person's Home Assistant", "the person's own Home Assistant address", "n/a", "none", True, "Home Assistant connected"),
    E("search_notion", "tool", 0, "searches the person's connected Notion", "api.notion.com", "n/a", "none", True, "Notion connected"),
    E("list_todoist_tasks", "tool", 0, "lists open tasks in Todoist", "api.todoist.com", "n/a", "none", True, "Todoist connected"),
    E("list_calendar_events", "tool", 0, "lists the next events on the person's Google Calendar", "www.googleapis.com", "n/a", "none", True, "Google Calendar connected"),
    E("list_google_tasks", "tool", 0, "lists open Google Tasks", "tasks.googleapis.com", "n/a", "none", True, "Google Tasks connected"),
    E("propose_todoist_task", "proposal", 2, "proposes a task in the person's Todoist Inbox", "api.todoist.com (only when approved)", "by hand in Todoist: Diya cannot remove it", "owner approves each action", False, "Todoist connected"),
    E("propose_calendar_event", "proposal", 2, "proposes an event, just for the person, on their Google Calendar", "www.googleapis.com (only when approved)", "by hand in Google Calendar: Diya cannot remove it", "owner approves each action", False, "Google Calendar (add events) connected"),
    E("propose_google_task", "proposal", 2, "proposes a task in the person's Google Tasks", "tasks.googleapis.com (only when approved)", "by hand in Google Tasks: Diya cannot remove it", "owner approves each action", False, "Google Tasks connected"),
    E("propose_drive_folder", "proposal", 2, "proposes a new folder at the top of the person's Google Drive", "www.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive and Docs connected"),
    E("propose_google_doc", "proposal", 2, "proposes a new Google Doc with at most a line of text", "docs.googleapis.com (only when approved)", "by hand in Google Drive: Diya cannot remove it", "owner approves each action", False, "Google Drive and Docs connected"),
    E("read_mail", "flow", 0, "looks through the person's Gmail when they ask; the answer is written by a model with no tools", "gmail.googleapis.com", "n/a", "none", True, "Gmail connected"),
    E("mail_write_refused", "flow", 0, "answers a request to send, change or delete mail with the fact that access is read-only", "none", "n/a", "none", False),
    E("study_repo", "flow", 0, "reads a public GitHub repository the person names and shows the evidence", "api.github.com, raw.githubusercontent.com", "n/a", "none", True),
    E("explain_memory", "flow", 0, "says where a remembered fact came from, from the memory's own record", "none", "n/a", "none", False),
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
    "diya_push.py": "web push to the person's own subscribed devices",
    "diya_telegram.py": "the person's own Telegram bot",
    "diya_warm.py": "the local Ollama, to keep the chat model loaded",
}


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
