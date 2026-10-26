# A live check of every Google operation, for you to run once on your own account (DIYA-070; written 2026-10-25)

Every test of the Google parts of Diya talks to a stand-in Google (`tests/test_google_fault_matrix.py` and the files named below). Nobody has yet connected them to the real Google. This is the plan for that:
eight steps, one for each thing Diya can do with Google, each with what to say, what you should see, and how to undo it. Do them in this order; stop at the first one that does not do what the row says and tell me
what you saw instead. It takes about ten minutes once the cards on the Connections page say Connected. Nothing in the first eight steps can send an invitation, share a file or delete anything for good; the
Gmail steps further down can send an email, and the plan sends it only to your own address, only after you approve exactly that email.

Before you start: Connections page, Calendar, Gmail, Tasks and Drive and Docs each show Connected (`docs/GOOGLE_SETUP.md` has the steps), and the Google project's publishing status is **In production**
(`docs/GOOGLE_SURFACES_2026-10.md`: in Testing the sign-in dies after seven days).

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `list_calendar_events` | "what is on my calendar?" | The next events with their dates, or "No upcoming events." | Nothing changes | `tests/test_google_calendar.py` — `list_events` |
| `read_calendar` | "what am I doing next Tuesday?" | The events on that day, written by code from Google's answer, with the date shown | Nothing changes | `tests/test_calendar_talk.py` — `read_calendar` |
| `list_google_tasks` | "what is on my Google Tasks list?" | Your open tasks in the default list, or "No open tasks in Google Tasks." | Nothing changes | `tests/test_google_write.py` — `google_tasks_list` |
| `read_mail` | "did anyone email me about the exam this week?" | A short report of matching messages with who, when and the subject, and what was not read | Nothing changes (read-only) | `tests/test_google_mail.py` — `read_mail` |
| `propose_calendar_event` | "put 'Diya smoke test' on my calendar tomorrow at 5pm for 30 minutes" | A card on the Actions page with the exact title, time and "nobody is invited". After you approve: "Added", and the event on your calendar | Delete the event in Google Calendar | `tests/test_google_write.py` — `propose_calendar_event` |
| `propose_google_task` | "add a Google task: Diya smoke test" | A card; after approval the task appears in Google Tasks | Delete the task in Google Tasks | `tests/test_google_write.py` — `propose_google_task` |
| `propose_drive_folder` | "make a Drive folder called Diya smoke test" | A card; after approval a folder at the top of My Drive | Delete the folder in Drive | `tests/test_google_write.py` — `propose_drive_folder` |
| `propose_complete_google_task` | "mark 'Diya smoke test' as done in my Google Tasks" | A card "Mark done in your Google Tasks: Diya smoke test"; after approval the task shows as completed | Mark it open again in Google Tasks | `tests/test_google_tasks_changes.py` — `propose_complete_google_task` |
| `propose_update_google_task` | "rename Diya smoke test to Diya smoke test two in my Google Tasks" | A card saying the new name; after approval the task has it | Rename it back in Google Tasks | `tests/test_google_tasks_changes.py` — `propose_update_google_task` |
| `propose_move_google_task` | "move Diya smoke test two to the top of my Google Tasks" | A card; after approval the task is first in the list | Drag it back in Google Tasks | `tests/test_google_tasks_changes.py` — `propose_move_google_task` |
| `propose_delete_google_task` | "delete Diya smoke test two from my Google Tasks" | A card that says Diya cannot bring it back (risk level 3); after approval the task is gone | Nothing: it was a test task | `tests/test_google_tasks_changes.py` — `propose_delete_google_task` |
| `propose_google_doc` | "make a Google Doc called Diya smoke test with the line hello" | A card; after approval a Doc with that line, and its address | Delete the Doc in Drive | `tests/test_google_write.py` — `propose_google_doc` |

Things to look for on every step: it answers within about fifteen seconds; the Activity page shows one line for it; for a write the Actions page shows exactly what was approved and one outcome (succeeded, or a
plain sentence if it did not); asking the same write twice does not make two. If a step ends in "unknown", Google was reached but did not confirm: look in Google, then press the button that records what you found.

## The Gmail cards (added 2026-10-26; DIYA-075, -076, -077, -078, -113)

Before these: in your Google project, under Data access, add `gmail.compose`, `gmail.send` and `gmail.modify` (the Gmail API is already switched on for reading); then on the Connections page press Connect on **Gmail: drafts**,
**Gmail: send** and **Gmail: organise** (three separate cards), and keep the plain **Gmail** card connected too: a reply and a forward find the email through it. Use your own address wherever a step needs one.

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `propose_gmail_draft` | "draft an email to YOUR-ADDRESS about the Diya smoke test, saying hello" | A card "Save a draft email to YOUR-ADDRESS: ... (a draft is not sent)" with the whole text in its fields; after approval the draft is in Gmail's Drafts, unsent | Delete the draft in Gmail | `tests/test_google_mailwrite.py` — `propose_gmail_draft` |
| `propose_discard_gmail_draft` | "delete the draft Diya smoke test" | A card that says Diya cannot bring it back; after approval the draft is gone | Nothing: it was a test draft | `tests/test_google_mailwrite.py` — `propose_discard_gmail_draft` |
| `propose_send_gmail` | "send an email to YOUR-ADDRESS saying this is the Diya smoke test" | A card with the address, the subject and the whole text, risk level 3; after approval "Sent ... and read back from your Sent folder", and the email arrives | Nothing unsends it: it went to you | `tests/test_google_mailwrite.py` — `propose_send_gmail` |
| `propose_reply_gmail` | "reply to the email about the Diya smoke test saying got it" | A card naming which email and the address the reply goes to; after approval the reply is in the same conversation | Nothing unsends it: it went to you | `tests/test_google_mailwrite.py` — `propose_reply_gmail` |
| `propose_forward_gmail` | "forward the email about the Diya smoke test to YOUR-ADDRESS" | A card "Forward ... text only without attachments"; after approval the forward arrives | Nothing unsends it: it went to you | `tests/test_google_mailwrite.py` — `propose_forward_gmail` |
| `propose_organise_gmail` | "archive the email about the Diya smoke test" | A card; after approval the email has left your inbox (try mark as read, star and the bin too) | Move it back to the inbox in Gmail | `tests/test_google_mailwrite.py` — `propose_organise_gmail` |

Two things to try that should be **refused**: "send an email to my boss saying hi" (no address typed: nothing is proposed) and "reply to Sam's email" when two of Sam's emails match (Diya lists them and asks which).

When all eight pass, tell me, and the sheet's DIYA-216 (a smoke run on a real account) and the "needs your real account" rows (DIYA-081, -087, -093, -097) can be marked from what you saw.

**If you connected with "Connect all Google"** (`docs/GOOGLE_SETUP.md`): before the eight steps, look at the Connections page. Each card you allowed on Google's screen should say Connected and "Connected in one sign-in with the other Google cards"; a card you unticked
should say Not connected. Google's screen asked once, listing the permissions in plain words (it will say Diya is unverified: Advanced, then continue). If a step then answers "not connected" for a card you allowed, tell me which, and what Google's screen offered.
