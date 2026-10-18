# The pause switch (2026-10-18; DIYA-047)

**Why.** The blueprint asks for an emergency kill switch so that "pending connector writes and background actions pause predictably". Diya now has things that happen without the owner being present (scheduled automations, Diya writing first) and things that touch their accounts (approved Google and Todoist actions). One obvious way to stop all of it, that works even when Diya is behaving oddly, is part of trusting it.

**What it does** (`diya_pause.py`). One switch, two values in the database's `app_state` (so the scheduled notifier, a separate process, sees it the moment it changes). Pause it on the **Status** page (**Pause Diya** / **Resume Diya**) or with `POST /api/pause` and `POST /api/resume`. While paused:

| Stopped | How |
|---|---|
| Running an approved action (a Google event, task, folder or document; a Todoist task) | `Actions.run` refuses before touching anything, so an action approved earlier stays **approved**, and runs once after resume if its day has not passed. The **Approve** button is refused *before* approving, so a waiting action simply keeps waiting (HTTP 423, with the reason shown on the page). |
| Scheduled automations ("every morning at 8, tell me the weather") | the notifier does not run them and says "paused" |
| Diya writing first (the morning and evening messages, "welcome back") | the notifier does not write them |

**Left running on purpose.** Chatting, reading, searching; proposing actions (a proposal only writes a card); rejecting; editing memory; **reminders**, which are the owner's own alarms and not Diya acting; Dreaming (it only changes Diya's own memory); backups; and the health page itself. If the switch is on and the database cannot be read, Diya is treated as **not** paused: the switch must not be what takes her down, and every write still has its own checks.

**Recorded.** Pausing and resuming are written to the activity journal (the first pause time is kept; pausing twice changes nothing).

**Proof.** `tests/test_pause.py` (10 cases): the state and its persistence across connections, idempotence, a safe reason, an unreadable database; an approved action not run, still approved, then run exactly once after resume; the approve route refusing with 423 and leaving the action pending; proposing/approving/rejecting still working; the notifier running no automation and writing nothing first while still telling a reminder, and running the automation again after resume; the Status page's line and the routes.

**Not done.** A way to pause by saying so in chat or Telegram; a time-limited pause ("until Monday"); stopping the live memory reading. Automatic pausing (for example after repeated refusals by Google) is not built.
