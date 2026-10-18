"""The pause switch: stop Diya acting on her own until the owner says go (docs/PAUSE_DESIGN.md), added 2026-10-18 for DIYA-047.

While paused:
* an approved action is NOT run (diya_actions.Actions.run refuses; the action stays approved, so after "resume" it can still be run, as long as its day has not passed);
* automations the person scheduled do not run;
* Diya does not write first (the morning and evening messages, the "welcome back");
and nothing else changes: the person can still chat, see everything, approve, reject, and edit memory. Reminders still fire: they are the person's own alarms, not Diya acting.

The state is two small values in the database (`app_state`), so every part of Diya, including the scheduled notifier that runs as a separate process, sees the same switch the moment it changes. Pausing and
resuming are recorded in the activity journal. Importing this module has no side effects.
"""
from __future__ import annotations

from datetime import datetime, timezone

KEY_AT, KEY_WHY = "paused_at", "paused_reason"
REASON_CHARS = 200


def _get(conn, key):
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def state(store):
    """{"paused": bool, "since": ISO text or None, "reason": text}. A database that cannot be read counts as NOT paused: the switch must not be what takes Diya down, and every write already has its own checks."""
    try:
        conn = store.connect()
    except Exception:  # noqa: BLE001
        return {"paused": False, "since": None, "reason": ""}
    try:
        since = _get(conn, KEY_AT)
        return {"paused": since is not None, "since": since, "reason": _get(conn, KEY_WHY) or ""}
    except Exception:  # noqa: BLE001
        return {"paused": False, "since": None, "reason": ""}
    finally:
        conn.close()


def is_paused(store):
    return state(store)["paused"]


def pause(store, reason="", now=None):
    """Pause Diya. Pausing twice keeps the first time. Returns the state."""
    import diya_memory

    reason = diya_memory.printable(reason or "", REASON_CHARS)
    conn = store.connect()
    try:
        if _get(conn, KEY_AT) is None:
            conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (KEY_AT, (now or datetime.now(timezone.utc)).isoformat()))
            conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (KEY_WHY, reason))
            conn.commit()
            _record(store, "pause", reason)
    finally:
        conn.close()
    return state(store)


def resume(store):
    """Let Diya act again. Resuming when not paused does nothing. Returns the state."""
    conn = store.connect()
    try:
        was = _get(conn, KEY_AT) is not None
        conn.execute("DELETE FROM app_state WHERE key IN (?, ?)", (KEY_AT, KEY_WHY))
        conn.commit()
    finally:
        conn.close()
    if was:
        _record(store, "resume", "")
    return state(store)


def _record(store, what, note):
    import diya_journal

    diya_journal.record(store, what, {}, "ok", kind="flow", origin="chat", note=note or None)
