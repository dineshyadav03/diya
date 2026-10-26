# Google: what is decided, what is not built, and why (written 2026-10-27)

This page is the answer to the Google tasks on the sheet that are about a choice, a limit or a service Diya does not have, not about code. Each says what holds today, what pins it (a test, where there is one), and what it would take
to change. Nothing here claims a real account has tried it: the Google work is built and tested against stand-in services, and `docs/GOOGLE_LIVE_SMOKE.md` is the plan for the owner's own account.

## Accounts and where Google is reached from

**DIYA-066 One account per Diya, and no way to write to the wrong one.** Diya is for one person on one personal Google account (`docs/DECISIONS_2026-10-18.md`). Every card holds one stored sign-in, and every request it can make goes to that
account's own `primary` calendar, `@default` task list, Drive top level, `@me` mailbox or `people/me` (the lists of allowed requests in `diya_google_client.allow` and `diya_google_write` name no other calendar, list, mailbox or person, and a
test says so), so a write cannot be aimed at a second account by a word the model wrote. A second account means a second Diya folder (`DIYA_DATA_DIR`): its own database, its own sign-ins, its own cards. What is **not** here: showing which
address is signed in. That needs the `openid email` permission on every card, which would change every existing sign-in; it is a decision for the owner, and the sheet row stays open for it.

**DIYA-073 Direct calls, not a Google tool server.** Google is called with plain requests through one client (`diya_google_client`), each card held to its own list of allowed requests. A third-party Model Context Protocol server for Google would
need the sign-in or its own, and would move the list of what may be done out of Diya's code, so none is used. The MCP client Diya has (`docs/MCP_DESIGN.md`) takes only servers the owner adds, read-only tools approved one at a time and
pinned, never obeyed, and **never receives a Google sign-in**: a test reads its source and finds no Google module and no token function in it. Unvetted servers stay off.

## Mail

**DIYA-079 Filters, rules and permanent deletion: not supported, on purpose.** A mail filter can forward every message somewhere, which is a way to take a mailbox without ever sending anything, and permanent deletion cannot be undone. Neither
permission is asked for (`gmail.settings.*` and the full-mailbox `mail.google.com` do not appear in the code, and `tests/test_google_admin_policy.py` pins the whole list of permissions), and no card has a request that deletes mail for good
(`tests/test_google_decisions.py` lists every DELETE any card may make: a draft, an event of the owner's own with no guests, a task in the default list, a share, a contact; never a message, a file, a task list or a calendar). Mail is moved to the bin, which keeps it 30 days, and brought back. Wanting either would be a new card with its own design and its own approval.

## Calendar

**DIYA-085 Making calendars and changing who can see them: not offered.** It needs a broader permission than the events one, reaches other people (sharing a calendar), and depends on organiser rights and the kind of account. Every calendar card
is held to the main calendar. If it is ever wanted it is its own card, off until the owner adds the permission, and every change is level 3.

## Tasks

**DIYA-099 Which list is the truth.** Diya's own to-do list (the Tasks page) and Google Tasks are two lists and **nothing copies one into the other**. Google Tasks is read live from Google every time and Diya keeps no copy of it (only the
activity record's short line); Diya's own list lives in Diya's database. Because nothing writes in either direction by itself, there is no loop to guard. A copy from one to the other would be a proposal the owner approves, never background work.

**DIYA-100 Repeating tasks, duplicates and restarts.** Google's Tasks service has no repeat that its API can set, so Diya sets none and says so; a task that repeats is made in Google Tasks itself. Duplicates: the same proposal cannot wait twice (the
approval is bound to the exact arguments), an event added twice from one request gets the same id and the second is found, not made (`tests/test_google_write.py`), and nothing is kept in Diya that could disagree with Google after a restart: the
waiting proposals are in the database and run once (`tests/test_actions_multi_process.py`).

## Forms

**DIYA-114 What Forms needs, and what is not yet proven.** The Forms API must be switched on in the Google project; no new permission is asked: Google's own table of who may call what lets the Drive read permission (`drive.readonly`) read a form and its
answers and the Drive change permission (`drive.file`) make a form and change one the app made. That table is read from Google's documentation and has not been tried on the owner's account; if Google refuses, the card says the sign-in does not
allow it (`diya_google_client.error_for`, the "scope" kind) and nothing is done. Account constraints (a form made by a Workspace account that an administrator limits) are the owner's to see; the live check has a row for it.

## The services Diya does not have, and why

Each was looked at as the task asks. None is built; none has a card on the Connections page, so none is promised. What is written is what stops it and what would have to be true first. Check Google's own pages before building any of them: these
services change, and what is written here is from the sheet and from what was known on 2026-10-27.

| Task | Service | Why it is not built | What would have to be true first |
|---|---|---|---|
| DIYA-118 to -121 | Google Chat | The Chat interface is built around apps and bots in a Workspace space; acting as a person in chat needs sign-in modes and a Workspace account that a personal account may not have. Posting reaches other people, and incoming chat text is words from anyone. | A test account that supports the identity mode wanted; posting identity and recipients approved exactly as for email; incoming text read by code with no tool, never as an instruction. |
| DIYA-122 to -124 | Google Meet | Making a meeting space is reachable, but recordings and transcripts depend on the account's plan and on each participant's permission. | The entitlements documented for the account; participants' consent; retention rules; level 3 for anything that reaches others. |
| DIYA-125, -126 | Google Keep | Keep's interface is offered to Workspace organisations, with no promise for personal accounts. **No connector is exposed** until a real account shows it works. | A real account test that demonstrates read and write. |
| DIYA-127, -128 | Google Classroom | Depends on being a teacher or a student, and on the school's policies; writing to a course reaches a class. | The role and the institution's policy, and a fixture course for tests. |
| DIYA-129, -130 | Google Photos | The photo library interface has been narrowed to what an app itself created and to a picker the person chooses from; a general "look through my photos" is not available to promise. | The current limits re-checked and a use that fits them; no library-wide promise. |
| DIYA-131, -132 | Maps and Places | Searching places is a keyed service about the world, not the person's account; the person's own saved places and favourites are not changed by a documented interface. Diya has no Maps key. | A key the owner chooses to create; reads kept apart from the account; no write advertised. |
| DIYA-133, -134 | YouTube | Needs its own sign-in, a channel and quota; uploading and publishing reach the public. | Public publishing as a per-action preview and approval at level 3; quota counted. |
| DIYA-135 to -138 | Cloud and Workspace administration | Off by rule: see `docs/GOOGLE_ADMIN_POLICY.md`. | That page's list. |

## Joining services

**DIYA-144 Events from Google starting something.** Google can tell an app when mail arrives, a calendar changes or a file moves, but only by calling a public web address, and Diya runs on the owner's own computer with none. So nothing is pushed to
Diya; it looks when asked, and the scheduled automations read on a timer, read-only. If a public address is ever added, a raw event may only start a *suggestion or a review* (a line on the Today page, a notification) or a flow the owner
approved in advance that is deterministic and read-only; never an action on its own, never a model that obeys the text of the event. Each event would be checked for who sent it, counted once by its id, and rate-limited.

**DIYA-145 No queue of writes, so no hidden retry.** A read that fails says why in a plain sentence and is tried again at most twice, waiting a few seconds, only for a busy or failing service (`diya_google_client`). A change is **never** queued and
never tried again: if it did not reach Google it is "failed" and stays so; if it may have reached Google it is "unknown", the owner is told to look, and it is not run again. Diya counts its own requests to Google each day and stops at
the limit (`DIYA_GOOGLE_DAILY_REQUESTS`, 5000 by default) with a sentence. So after the network comes back nothing runs by itself: the owner proposes it again. (`tests/test_google_client.py` pins the retries, the count and the no-retry of a change.)

## The sheet

Rows that this page settles by decision are marked as such, not "Done": the choice is made and pinned, but only the owner can say a real account behaves as the page says.
