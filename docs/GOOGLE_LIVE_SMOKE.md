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
| `propose_cited_google_doc` | "research spaced practice and make a Google Doc called Diya cited test with sources" | A card whose text cites [1], [2] and ends with a numbered Sources list, every address one the search showed (the card says a page's claims are not checked); after approval the Doc has it | Delete the Doc in Drive | `tests/test_google_cited.py` — `propose_cited_google_doc` |

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

## The Calendar changes (added 2026-10-26; DIYA-080, -082, -083, -084)

Before these: Google Cloud needs nothing new (the same `calendar.events` permission is already added for "add events"); on the Connections page press Connect on **Google Calendar (change events)** and **Google Calendar (guests)**
(two more cards). Make a plain test event first: "put 'Diya calendar test' on my calendar tomorrow at 5pm for 30 minutes".

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `propose_update_calendar_event` | "rename Diya calendar test to Diya calendar test two" then "move Diya calendar test two to tomorrow at 6pm" | A card with the event and the change; after approval the event has the new name or time | Change it back in Google Calendar | `tests/test_google_calchange.py` — `propose_update_calendar_event` |
| `propose_cancel_calendar_event` | "cancel Diya calendar test two" | A card that says Diya cannot bring it back (risk level 3); after approval the event is gone | Nothing: it was a test event | `tests/test_google_calchange.py` — `propose_cancel_calendar_event` |
| `propose_invite_calendar_event` | "invite YOUR-OTHER-ADDRESS to Diya calendar test" (make a new test event first) | A card that says Google Calendar emails them (risk level 3); after approval the address is a guest and gets an email | Remove the guest in Google Calendar | `tests/test_google_calchange.py` — `propose_invite_calendar_event` |
| `propose_rsvp_calendar_event` | "accept the invitation to Diya calendar test" (from your other account's invitation) | A card that says the organiser is told; after approval the answer shows as accepted | Answer again in Google Calendar | `tests/test_google_calchange.py` — `propose_rsvp_calendar_event` |
| `propose_repeating_calendar_event` | "add a weekly Diya repeat test on monday at 6pm for 3 weeks" | A card "repeating weekly, 3 times"; after approval three events appear, one a week | Delete the series in Google Calendar | `tests/test_google_calchange.py` — `propose_repeating_calendar_event` |

Two read-only questions to try as well (nothing changes): "when is my Diya calendar test?" lists it with its day and time, and "when am I free tomorrow?" lists the gaps between 9:00 and 18:00.

## Google Drive and Docs (added 2026-10-26; DIYA-086, -088, -089, -090, -091, -092, -094, -095)

Before these: in your Google project switch on the Google Drive API (and Google Docs API, already on), add `drive.readonly` under Data access (this one is Google's "restricted" kind: it lets Diya see your whole Drive, to search and read it;
nothing in the read card changes anything), then on the Connections page press Connect on **Google Drive (read)** and **Google Drive (change)**. Make a test Doc first: "make a Google Doc called Diya drive test with the line hello".

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `read_drive` | "search my drive for physics notes", then "read my Diya drive test doc in my drive", then "what are the earlier versions of Diya drive test?" | A list of names, types and dates (never contents); the file's text as numbered paragraphs with its version and date, with a short answer above it; the dates and who changed it. Nothing changes | Nothing changes | `tests/test_google_drive.py` — `read_drive` |
| `propose_rename_drive_file` | "rename the file Diya drive test to Diya drive test two" | A card with the old and new name; after approval the file has the new name | Rename it back | `tests/test_google_drive.py` — `propose_rename_drive_file` |
| `propose_move_drive_file` | "make a Drive folder called Diya box", then "move the file Diya drive test two into the folder Diya box" | A card with where it comes from and goes, and how to put it back; after approval it is in the folder | Move it back | `tests/test_google_drive.py` — `propose_move_drive_file` |
| `propose_trash_drive_file` | "delete the file Diya drive test two from my drive" | A card saying Drive keeps it 30 days; after approval it is in the Drive bin | Bring it back from the bin | `tests/test_google_drive.py` — `propose_trash_drive_file` |
| `propose_restore_drive_file` | "restore the file Diya drive test two from the bin in my drive" | A card; after approval it is out of the bin | Put it in the bin again | `tests/test_google_drive.py` — `propose_restore_drive_file` |
| `propose_share_drive_file` | "share the file Diya drive test two with YOUR-OTHER-ADDRESS so they can view it" | A card with the one address and the role, risk level 3; after approval Google emails them and they can open it | Stop sharing it (next row) | `tests/test_google_drive.py` — `propose_share_drive_file` |
| `propose_unshare_drive_file` | "stop sharing the file Diya drive test two with YOUR-OTHER-ADDRESS" | A card; after approval they lose access | Share it again | `tests/test_google_drive.py` — `propose_unshare_drive_file` |
| `propose_edit_google_doc` | "add a line to my Diya drive test doc saying second line", then "in my Diya drive test doc change hello to goodbye" | A card with the whole text (or the old and new words and how many places); after approval the Doc has it | Use the Doc's version history | `tests/test_google_drive.py` — `propose_edit_google_doc` |

## Google Contacts (added 2026-10-26; DIYA-110, -111, -112, -113)

Before these: in your Google project switch on the People API, add `contacts.readonly` and `contacts` under Data access, then on the Connections page press Connect on **Google Contacts (read)** and **Google Contacts (change)**.

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `read_contacts` | "what is YOUR-CONTACT's email?" | The name with its address and number, written by code, no model; two people with the name are listed | Nothing changes | `tests/test_google_contacts.py` — `read_contacts` |
| `propose_add_contact` | "add Diya Test to my contacts: diya.test@example.com" | A card with the name and address; after approval the contact is in Google Contacts | Delete it there | `tests/test_google_contacts.py` — `propose_add_contact` |
| `propose_update_contact` | "add a number to Diya Test's contact: 98765 43210" | A card with the contact and the number; after approval it is saved | Remove it there | `tests/test_google_contacts.py` — `propose_update_contact` |
| `propose_contact_group` | "put Diya Test in my Classmates group" (a group of yours) | A card; after approval the contact is in the group | Take them out (say so) | `tests/test_google_contacts.py` — `propose_contact_group` |
| `propose_delete_contact` | "delete Diya Test from my contacts" | A card that says Diya cannot bring it back (risk level 3); after approval it is gone | Nothing: it was a test contact | `tests/test_google_contacts.py` — `propose_delete_contact` |

Also try "send an email to YOUR-CONTACT saying this is the Diya smoke test": the card should show the contact's address and "(Name, from your contacts)". A name that is two people, or nobody, is refused.

## Google Sheets and Slides (added 2026-10-26; DIYA-101 to -109)

Before these: in your Google project switch on the Google Sheets API and the Google Slides API (the permission is the `drive.file` one the Drive (change) card already has, so there is nothing new to add or press).

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `propose_google_sheet` | "make a Google Sheet called Diya sheet test with rows item, cost; books, 40; =danger, 1" | A card with the rows and "1 cell(s) that began with = + - or @ are kept as plain text"; after approval a Sheet whose cell shows `'=danger` as text, never a formula | Delete the Sheet in Drive | `tests/test_google_sheets_slides.py` — `propose_google_sheet` |
| `propose_sheet_rows` | "add a row to the Diya sheet test sheet: pens, 5" | A card saying after which row; after approval the row is at the end | Delete the row in Sheets | `tests/test_google_sheets_slides.py` — `propose_sheet_rows` |
| `propose_sheet_cells` | "in the Diya sheet test sheet set D2 to 45", then "in the Diya sheet test sheet replace B2 with 99" | The first card says only empty cells; the second says it REPLACES 1 filled cell and what it holds now (and is refused unless you say replace or overwrite) | Use the sheet's version history | `tests/test_google_sheets_slides.py` — `propose_sheet_cells` |
| `propose_sheet_header` | "make the header row of the Diya sheet test sheet bold" | A card; after approval the first row is bold and stays in view | Undo in Sheets | `tests/test_google_sheets_slides.py` — `propose_sheet_header` |
| `propose_google_slides` | "make a Google Slides deck called Diya deck test with slides: Why | spaced practice || Plan | week 1" | A card with every slide's title (and the bullets in its fields); after approval a deck with a title slide and two slides. Look at how it looks in Slides | Delete the deck in Drive | `tests/test_google_sheets_slides.py` — `propose_google_slides` |
| `propose_add_slides` | "add a slide to the Diya deck test deck: Revision plan | mock tests" | A card; after approval the slide is at the end | Delete the slide in Slides | `tests/test_google_sheets_slides.py` — `propose_add_slides` |

## The workflows (added 2026-10-26; DIYA-078, -140, -142)

- Mail with an attachment: "check my inbox" lists the attachment's name, type and size (a `.exe` is flagged), and never its contents.
- Mail to tasks: after "any email from the college?" a *Possible tasks I noticed* list may appear; "put suggestion 1 in my Google Tasks" makes a card to approve.
- Doc to deck: "make a deck from my Diya drive test doc" makes a card with every slide and a last slide naming the Doc.

## Google Forms (added 2026-10-27; DIYA-114 to -117)

Before these: in your Google project switch on the Google Forms API (no new permission: reading a form uses the Drive read card, making one the Drive change card). If Google refuses, the answer says the sign-in does not allow it; tell me.

| Operation | What to say to Diya | What you should see | Undo | Its stand-in test |
|---|---|---|---|---|
| `propose_google_form` | "make a Google Form called Diya form test with the questions: how did you hear of us (a friend or an ad), any comments" | A card with the questions and their kinds, "it is not shared with anyone"; after approval a form with those questions | Delete the form in Drive | `tests/test_google_forms.py` — `propose_google_form` |
| `propose_form_questions` | "add a question to the Diya form test form: would you come again" | A card; after approval the question is at the end | Delete the question in Forms | `tests/test_google_forms.py` — `propose_form_questions` |

Then answer your own form once from another browser, and say "show the responses to my Diya form test form": you should see the answer and no email address.

Two things to try that should be **refused**: "send an email to my boss saying hi" (no address typed: nothing is proposed) and "reply to Sam's email" when two of Sam's emails match (Diya lists them and asks which).

When all eight pass, tell me, and the sheet's DIYA-216 (a smoke run on a real account) and the "needs your real account" rows (DIYA-081, -087, -093, -097) can be marked from what you saw.

**If you connected with "Connect all Google"** (`docs/GOOGLE_SETUP.md`): before the eight steps, look at the Connections page. Each card you allowed on Google's screen should say Connected and "Connected in one sign-in with the other Google cards"; a card you unticked
should say Not connected. Google's screen asked once, listing the permissions in plain words (it will say Diya is unverified: Advanced, then continue). If a step then answers "not connected" for a card you allowed, tell me which, and what Google's screen offered.
