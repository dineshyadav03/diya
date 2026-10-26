"""Do it straight away: the owner's switch for kinds of addition that need no Approve (docs/ACTIONS_DESIGN.md, "Do it straight away"), added 2026-10-26.

The owner found pressing Approve for every calendar event, task, folder and document tiring, and chose to have these four done without asking. This module is the whole of that permission, and it is narrow on purpose:

* only the four kinds in AUTO_KINDS can ever be switched on, by name: each only ADDS something new that is private to the owner and is taken back by deleting it in Google (an event with nobody invited, a task,
  an empty folder, a document with at most a line of text). Nothing that sends, shares, changes, moves or deletes can be added to the list without changing this file and the test that pins it;
* each is OFF until the owner switches it on, one by one, and can be switched off again at any time; the pause switch (docs/PAUSE_DESIGN.md) stops them too;
* it applies only to a proposal made while answering the owner's OWN message (the kind's own `asked` check, which every proposal has to pass, has already said that message asked for exactly that), and never to
  one made after Diya read something that is not the owner's (a web page, a note, an email, a file: `tainted`), which waits for an Approve as before;
* what is done is exactly what was recorded and hashed (the approval is made with that hash, so a change in between refuses it), is recorded as an approval `via` "auto" in the action's own history and in the
  activity journal, and is never retried if its outcome is not known.

The switches are values in the database (`app_state`), so the chat, the scheduled jobs and the phone channel all see the same one. Importing this module has no side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone

import diya_pause

AUTO_KINDS = ("google_calendar_add_event", "google_tasks_add", "google_drive_make_folder", "google_docs_create")
PREFIX = "auto_approve:"


def _key(name):
    return PREFIX + name


def enabled_kinds(store):
    """The kinds that are switched on, in the order of AUTO_KINDS. A database that cannot be read counts as nothing switched on: the switch must never be what lets something through."""
    try:
        conn = store.connect()
    except Exception:  # noqa: BLE001
        return []
    try:
        rows = conn.execute("SELECT key FROM app_state WHERE key LIKE ?", (PREFIX + "%",)).fetchall()
    except Exception:  # noqa: BLE001
        return []
    finally:
        conn.close()
    on = {row[0][len(PREFIX):] for row in rows}
    return [name for name in AUTO_KINDS if name in on]


def is_enabled(store, name):
    return name in enabled_kinds(store)


def set_enabled(store, name, on, now=None):
    """Switch one kind on or off. ValueError for a kind that is not in AUTO_KINDS (nothing else can be switched on, whoever asks). Recorded in the activity journal. Returns the kinds now on."""
    if name not in AUTO_KINDS:
        raise ValueError(f"{name!r} cannot be done without asking: only {', '.join(AUTO_KINDS)} can")
    import diya_journal

    conn = store.connect()
    try:
        if on:
            conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (_key(name), (now or datetime.now(timezone.utc)).isoformat()))
        else:
            conn.execute("DELETE FROM app_state WHERE key = ?", (_key(name),))
        conn.commit()
    finally:
        conn.close()
    diya_journal.record(store, "auto_approve_on" if on else "auto_approve_off", {"kind": name}, "ok", kind="flow", origin="chat", note=f"{name} {'is now done straight away' if on else 'asks for an Approve again'}")
    return enabled_kinds(store)


def allowed(store, action):
    """May this freshly proposed action be approved and run now, without the owner pressing Approve? Only if its kind is in AUTO_KINDS and switched on, it is still pending, nothing outside the owner's own
    message was read before it was proposed, and Diya is not paused."""
    return (
        action.get("kind") in AUTO_KINDS
        and action.get("status") == "pending"
        and action.get("tainted") is False
        and is_enabled(store, action["kind"])
        and not diya_pause.is_paused(store)
    )
