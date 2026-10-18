# Google writes: Diya adds things to your Google account, one approval at a time (2026-10-18)

**What the owner asked for.** The engineering blueprint (`DIYA_MASTER_RESEARCH_ENGINEERING_BLUEPRINT_2026-10-18`, milestone G1) asks for Diya to *do* things in Google, not only read them, without ever acting on its own. This is the first round: four things, all of them **new, private and easy to take back by hand**.

| Ask Diya | What is made | Connector (its own sign-in) | Google scope |
|---|---|---|---|
| "put the dentist on my calendar for friday at 5pm" | an event, just you (nobody is invited, no mail is sent) | Google Calendar (add events) | `calendar.events` |
| "add renew the bus pass to my Google Tasks" | a task in your default list | Google Tasks | `tasks` |
| "make a folder called Exams in my Google Drive" | a folder at the top of My Drive | Google Drive and Docs (new things) | `drive.file` |
| "create a Google Doc called Study plan" | a new document, with one line of text if you gave it | the same Drive and Docs connector | `drive.file` |

**Not in this round, on purpose:** changing or deleting what is already there (that needs a read tool that shows ids, and a different risk tier), sending or drafting mail, sharing anything with anybody, reading your Drive (`drive.file` lets Diya see only files she made herself).

## How it stays safe

All four are **action kinds in the approval system** (`diya_actions.py`, `docs/ACTIONS_DESIGN.md`), the same machinery as the Todoist task, so nothing here is new trust:

1. **The model can only propose.** The tools are named `propose_*`. A proposal writes a pending card and sends nothing to Google. Approving it sends nothing either; only *running* an approved action does, once.
2. **Only what was asked.** A proposal is refused unless the owner's latest message asks for exactly that thing (`diya_intent.asks_to_add_calendar_event`, `asks_for_google_task`, `asks_for_drive_folder`, `asks_for_google_doc`), because a small model proposes things nobody asked for. A task is proposed for Google Tasks only when the message *names* Google Tasks; Diya's own to-do list refuses such a message, the way it refuses one that names Todoist.
3. **What you approve is built in code.** The one sentence on the Actions page comes from the arguments, not from anything the model said. Approval is bound to a hash of the exact arguments and lapses after a day.
4. **The time is yours.** The event's start is read by code (`diya_time`) from *your* words and **frozen when it is proposed**: "tomorrow at 5pm" cannot mean a different day if it is approved the next day. A time the model made up, or worked out itself, is never taken; the model is told it has none and must ask. The proposal note tells it to say how the time was read ("Friday 23 Oct 2026, 17:00") so you can check before you approve. A due day on a task works the same way (a day, not a time).
5. **A refusal is not an uncertainty.** Google refusing before anything happened (not connected, API not switched on, rate limit, any 4xx) is a **failed** action. A request that may have reached Google with no answer, or a server error part way, is **unknown**, is never sent again by itself, and waits for you to look in Google and record what you found.
6. **An event cannot be made twice.** Its id is made from the request (title, start, length), which Google accepts as the event's id. Asking again returns Google's "already exists", which is *checked* (is it this event?) and reported as "already on your calendar". An event added and later deleted cannot come back under the same id; the message says to change the title or length a little.
7. **A document is made in two steps** (create, then the text), so a failure between them is reported as *unknown, with the address of the document*, not as a clean failure or success.
8. **Narrow sign-ins.** Each connector asks Google for exactly one scope, added only when you press Connect on its own card (incremental consent). `drive.file` is used for both folders and documents, so Diya can never read the rest of your Drive. The Google client id and secret you already pasted are shared; forgetting them signs all five Google connectors out.
9. **The activity journal** (`docs/ACTIVITY_JOURNAL_DESIGN.md`) records every proposal, so the Activity page shows what Diya tried.

## What the approval system limits (and so this does too)

- The arguments are plain **single-line** text up to 4,000 characters, so a document's text is **one line** (up to 3,000 characters) and the Actions page shows its first 100 characters. A long document is a later feature with its own rendering.
- At most 10 actions wait at once and 3 per message.

## What is *not* verified

**Nothing here has been tried against a real Google account.** The tests (`tests/test_google_write.py`) stand in for Google: they prove the requests, the checks and the failure handling, not that Google answers the way the stand-in does. Things I could not check without the real service and that may need a change on the first real try:

- that `documents.create` and `documents.batchUpdate` accept the narrow `drive.file` scope for a document Diya made (the API's documentation lists it; the stand-in cannot confirm);
- that a custom event id of 32 hex characters is accepted (the rule is letters a to v and digits, 5 to 1024 characters; a hex digest fits);
- the exact wording of Google's refusals (shown to you as Google's own short message, with control characters removed).

## What only the owner can do

For each, in the same Google Cloud project as Calendar (`docs/GOOGLE_SETUP.md`): enable the API (Calendar, Tasks, Drive and Docs), add the scope under *Data access*, press **Connect** on the card, and say yes to Google's own page. Then try one by saying, for example, "add test to my Google Tasks", and look at the Actions page *before* approving.

## Next, in the blueprint's order

Updating and deleting (with a tier for each), `gmail.compose` drafts (never send), a Drive search/read tool for files Diya made, and a durable task state machine that survives a restart in the middle of an action.
