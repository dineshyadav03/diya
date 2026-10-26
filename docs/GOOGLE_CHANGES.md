# Changing what is already in your Google account (2026-10-26)

Until now Diya could read your Google account and ADD four kinds of thing to it. The owner then asked for the rest of the Google tasks on the sheet: change, move, rename, send, share, delete. This page says the rules that
hold for all of it, and what is built.

## The rules (the same for every service)

1. **Only a proposal.** Every change is a proposal the owner approves exactly as shown, on the card that says what it is, with the risk level that says what it can do (`diya_catalog.TIERS`): level 2 changes something in a way that can be put back by hand; **level 3 reaches
   other people (send, invite, share) or removes what Diya cannot bring back**. None is ever done straight away: the only kinds that can be are the four additions in `diya_autoapprove.AUTO_KINDS`, and a test says so for every new kind.
2. **Found now, by name.** A change to something that exists is made to the one thing found by the words the person used, looked up while the proposal is made (`ActionKind.resolve`, a read). None found, or several of the same name, refuses the proposal and says so; the model cannot supply an id
   and anything it supplies is replaced. Nothing is changed that was only guessed at.
3. **Still as it was.** The approval carries the thing's id and version. When it is run the thing is read again; if it changed since (renamed, finished, edited in Google, gone), nothing is done and the person is told. After the change it is read back and must be what was asked for; if that cannot be
   confirmed the outcome is `unknown` and is never retried.
4. **Their words.** A new name, new text or a date that the model made up is dropped; a time or day is read by code from what the person said.
5. **Each card has its own permission.** A new capability is its own card on the Connections page with its own narrow Google permission, off until the owner adds that permission in their Google project, switches the API on, and presses Connect. "Connect all Google" connects only the first five cards.
6. **One careful client** for all of it (docs/GOOGLE_CLIENT.md): typed errors, bounded, counted, allowlisted, a change never retried.
7. **What is read from Google is other people's words**: it reaches the model labelled as such (docs/ORIGIN_LABELS.md), and a proposal made after reading it is tainted.
8. **Never built:** permanent deletion, public sharing ("anyone with the link"), transferring ownership, anything about accounts, billing or administration (docs/GOOGLE_ADMIN_POLICY.md). A deletion is a move to the bin (restorable) wherever Google has one.

## What is built

| Service | Reads | Changes (each approved) | Card and permission |
|---|---|---|---|
| Google Tasks | the list across pages with state, due day and id; any list by name; finished tasks | complete, rename / notes / due day, move to the top or under another task, delete (level 3) | the existing Google Tasks card (`tasks`) |
| Gmail | (the existing read card) | save or replace a draft, throw a draft away (level 3); send a new email, reply, forward (level 3); archive, read / unread, star, one of your own labels, the bin and back | three new cards: **Gmail: drafts** (`gmail.compose`), **Gmail: send** (`gmail.send`), **Gmail: organise** (`gmail.modify`) |

| Google Calendar | an event by name, and free time (code answers, no model) | rename / move / change the length of one of your own events with no guests; cancel one (level 3); invite typed addresses (level 3); accept, decline or say maybe to an invitation (level 3); add an event that repeats | two new cards, both on the existing `calendar.events` permission: **Google Calendar (change events)** and **Google Calendar (guests)**; the repeating event is a new kind of the existing "add events" card |

| Google Drive and Docs | search your whole Drive; read a Doc, Slides, a Sheet or a text file with numbered paragraphs and a version; a file's earlier versions | rename, move (with from / to / how to undo shown), bin, bring back, share with one typed address (level 3), stop sharing; add to or change words in a Doc | two new cards: **Google Drive (read)** (`drive.readonly`) and **Google Drive (change)** (`drive.file`: only what Diya made) |

| Google Contacts | a contact's email or number (code answers, no model); a NAME turned into an address for an email, an invitation or a share | add a contact, add an email or number, put in or out of a group of yours, delete one (level 3) | two new cards: **Google Contacts (read)** (`contacts.readonly`) and **Google Contacts (change)** (`contacts`) |

| Google Sheets and Slides | (the Drive read card reads any Sheet as rows and any deck as numbered paragraphs) | on the sheets and decks Diya made: make a sheet, add rows, write cells (replacing filled cells needs the word replace or overwrite), bold and freeze the header; make a deck from an outline, add slides | the existing **Google Drive (change)** card (`drive.file`) |

More follow below as they are built.

## Gmail (diya_google_mailwrite.py; DIYA-075, -076, -077, -078, -113)

* **Three cards, so that each permission can be switched on alone.** Google's own `gmail.compose` and `gmail.modify` both include sending, which is wider than what the drafts and organise cards do; Diya's code gives each card a list of the exact
  requests it may make (`diya_google_client.allow`) and a test pins that the drafts and organise cards have no way to send and that no card can delete mail for good.
* **Who an email goes to.** Only an address the person typed in their own message. A name, a guess, an address from an email it read, or an address the model invented is refused when the proposal is made, and nothing is recorded. A reply goes to the Reply-To (else From) of the one
  message found, and the card shows that address. At most 5 recipients, a copy only to a typed address, **no hidden copy and no attachment, ever**. A forward is text only.
* **Finding the one email.** By the sender and/or the words the person used (the model's guess is used only if it is in their words), searched now with Gmail's own search over the last 60 days or the days they named. None found, or several, refuses the proposal and lists the candidates;
  "the latest" is the one thing that picks, and the card says which email it picked.
* **What is shown.** The card's arguments are shown as fields: every recipient, the subject and the whole text, and the approval is bound to exactly that. The text is one paragraph (Diya keeps an approval as one line). A forward sends the original's text as Gmail has it when it is sent, and sends nothing
  if the subject is no longer what was proposed.
* **Limits.** At most 20 emails sent a day, counted when Google answers (and when it might have). Never straight away. A send that may or may not have gone is `unknown` and is never retried; otherwise the message is read back (with the Gmail read card) and must be in Sent, to those addresses, with that subject.
* **Filing** (archive, read / unread, star, label, bin, bring back) changes exactly the labels named, only on an email still as proposed, and is read back. A label must be one of the person's own that already exists (Diya makes none), and the system labels cannot be put on or taken off by name.
* **A request to write mail** when the card for it is not connected is answered by code with the name of the card to connect; a request for many emails at once is refused ("one at a time"); neither asks the model.
* **The text of an email is other people's words** when it is read, as everywhere else (docs/ORIGIN_LABELS.md): a proposal made in a turn that read mail is marked on its card.

## Google Calendar (diya_google_calchange.py, diya_calendar_find.py; DIYA-080, -082, -083, -084)

* **Two cards on the permission already added** (`calendar.events`), so nothing new to add in Google: **change events** can only PATCH or DELETE one event and read events; **guests** can only PATCH one event and read events. Neither can create an event or touch another calendar (a test pins this),
  and the existing "add events" card cannot change or cancel (its allowed requests did not grow, except to read the calendar's time zone).
* **Whose event.** Only an event on your main calendar that you made, with **no guests, not one of a series, and (for a move) with a time**. An event that has guests is refused with "do that in Google Calendar", because changing or cancelling it would tell other people; Diya does not decide that for you. A series that
  repeats is refused too (changing a series is its own design). An event someone else made can only be answered (accept, decline, maybe).
* **Found now.** The event is found among the next 90 days by the words the person used (a day they name narrows it, but the NEW day in "move it to friday" is not the day it is on). None, or several, refuses the proposal and lists them; "the next one" is the one thing that picks.
* **Their words.** A new name, time or length the model made up is dropped; the time is read by code. A guest is only an address typed in the message, at most 5 at a time and 10 to an event. An answer to an invitation needs the person's own yes, no or maybe; a repeat needs their words for how often and for how many times (2 to 52).
* **Versions.** The proposal carries the event's etag; it is checked when the action runs and sent as `If-Match`, so a change made in Google in the meantime means nothing is done. Changes and cancels send `sendUpdates=none`; inviting and answering send `sendUpdates=all` (that is the point, and the card says Google emails them).
* **A repeating event** is written in your calendar's own time zone (read from the calendar) when this computer is in it, so a daylight-saving change does not shift later events; otherwise in UTC, which does not shift but is not the wall clock after such a change.
* **Questions** ("when is my dentist appointment?", "when am I free tomorrow?", "find an hour on friday", "am I free at 3pm?") are answered by code from the read-only card: gaps between 9:00 and 18:00, with events marked free by Google and cancelled ones not counted. A question that finds nothing and did not say "calendar" is left to the chat.
* **Not built:** moving or cancelling an event that has guests, changing one event of a series or the whole series, an event with guests created in one step, all-day events moved, and other calendars.

## Google Drive and Docs (diya_google_drive.py; DIYA-086, -088, -089, -090, -091, -092, -094, -095)

* **Reading** needs its own permission, `drive.readonly`, the one place Diya asks to see the whole Drive. It is a read card (it changes nothing); a Doc or Slides comes back as numbered paragraphs (so an answer can cite "[¶3]") with the file's version and date; a Sheet as rows; a text file as text (up to 200 KB, then cut
  to 3000 characters); a PDF, picture or video by its name and details only. File text is other people's words, so **the Drive is not offered to the model as tools at all**: like the mail, code reads and a model with NO tools words the answer (a search is listed by code with no model). That keeps the whole Drive, other people's words and the web search out of one turn (docs/AUTHORITY_MODEL.md, the one open accounting); a test pins that no Drive tool exists.
* **Changing** uses the narrow `drive.file` permission, which only ever sees what Diya made. So rename, move, bin, restore, share and Doc edits work on the files and folders Diya made, and cannot reach anything else in your Drive: that is Google's rule, and the code does not try to go round it. Changing files you made yourself needs the broad Drive permission, which Diya does not ask for.
* **Dry run for a move**: the card says which folder it is in and which it goes into and how to put it back; the move is refused if the file is no longer where it was proposed from.
* **The bin, not deletion**: Diya puts a file in Drive's bin (kept 30 days) and brings it back. It has no request that deletes for good (a test pins that). A folder that holds files is not binned.
* **Sharing**: one address the person typed, a role they said (view, comment or edit), the type always "user" (never "anyone with the link", never a whole domain, never ownership). Google emails them. Stopping the sharing is its own kind (level 2).
* **Conflicts and lost access**: a file's version is checked again when the action runs. A file changed since, in the bin, gone, or no longer visible means nothing is done, with the reason in words. A Doc is edited with `requiredRevisionId`: an edit made by anyone since means Google refuses the write and the document is exactly as it was. The words to change must be the person's own, found in the Doc 1 to 10 times, and the count is shown.

## Google Contacts (diya_google_contacts.py; DIYA-110, -111, -112, -113)

* **A name is not an address.** Until now an email, an invitation or a share went only to an address the person typed. A NAME ("email Maya", "invite Sam") is now turned into an address only when exactly one contact has that name and exactly one email saved (`diya_google_mailwrite.people`, one door for all three). Two
  people, nobody, or one person with two addresses refuses the proposal and lists them; the name must be one the person said; the card says "(Maya Rao, from your contacts)". An address the person typed is used as typed, and an address they did not type is never used. This is DIYA-113: no email goes to a target that was ambiguous.
* **Asking.** "What is Maya's email?" and "find the contact Sam" are answered by code from the contacts with no model and no tool (contacts can hold what anyone shared). When no one by that name is in them the chat goes on as before: the person may have told Diya.
* **Changing.** Add a contact (only details the person typed; a duplicate by name or address is refused), add an email or number to one found now (against its version), put one in or out of one of the person's own groups (built-in groups cannot be changed and Diya makes none), delete one (level 3). All read back.

## Google Sheets and Slides (diya_google_sheets.py, diya_google_slides.py; DIYA-101 to -109)

* **On what Diya made.** They use the `drive.file` permission of the Drive (change) card, so they work on sheets and decks Diya made and cannot reach any other. Reading any sheet or deck is the Drive read card (values as shown, rows numbered; a deck's text as numbered paragraphs). Formulas are not read: only what a cell shows.
* **No formula injection (DIYA-104).** Everything is written as plain text (`valueInputOption=RAW`, so `=1+1` is text), and a value that starts with `=`, `+`, `-` or `@` and is not a plain number is also kept with an apostrophe in front so that it stays text when exported and opened elsewhere. The card says how many cells were kept as text. A test pins this for
  formulas, hyperlinks and the classic `+cmd|...` shape, and that a plain `-5` stays a number.
* **Overwrite guard (DIYA-105).** Cells are shown with what they hold now; replacing filled cells needs the word *replace* or *overwrite* in the person's own message, and the cells are read again when the action runs: if they are not what the card showed, or the sheet's version moved, nothing is done. Rows are added after the row the card named and the sheet must still have that many rows.
* **Decks (DIYA-107, -109).** An outline (`Title | bullet || Title | bullet`) is shown whole; every slide uses Google's own title-and-body layout, so the layout is always valid; no images (so no image licence to record: images are not built). The deck is read back: the slide count and every title must be what was asked for. Diya does not draw the slides to look at them, so how they LOOK is for the person to check in Slides.
* **Not built:** charts, named ranges, other formatting, formulas, several sheets in one file, images in slides, and anything on a sheet or deck Diya did not make.

## Workflows that join two services (DIYA-078, -140, -142)

* **Attachments (DIYA-078).** The mail look-through lists each attachment of the messages whose text it read by name, type and size, and flags a file that can run code (an executable, a script, a macro document, a disk image, a shortcut) and an archive that can hide one, also behind a second extension (`invoice.pdf.exe`). An attachment
  is never downloaded, opened or described by its contents, so no size cap or file-type rule is needed to keep one out: there is no request that fetches one (a test reads the source to pin that). Sending never attaches anything.
* **Mail to Google Tasks (DIYA-140).** After a look through the mail, sentences that ask for something to be done ("please submit ... by", "you must bring", "the deadline is") are listed by code under the report as *possible tasks*, copied as written, with who they are from. Nothing is proposed by being listed. "Put suggestion 2 in my Google Tasks" turns that one
  into a proposal made by code, which the owner approves like any other; it is never done straight away, because its words are the email's and not the person's.
* **Doc to deck (DIYA-142).** "Make a deck from my Study plan doc": the Doc the person named (the explicit source) is read by code, cut into slides by its blank lines, and PROPOSED as a deck with a last slide naming the Doc and its version; the card carries every slide (the preview), the proposal is marked as made after reading a file, and nothing is published or shared.

## Forms, planning and tidying, the workflow runner, and your data (DIYA-114 to -117, -139, -141, -143, -146)

* **Forms (diya_google_forms.py).** No new permission: the Drive read card reads a form's questions and its answers (never the respondent's email address, at most 20 answers, each cut short, by code with no tool for the model) and the Drive change card makes a form and adds questions to a form Diya made, with every question on the card
  and the number and each question's title read back. Diya never shares or publishes a form. Whether Google lets the Drive permissions do these Forms requests is from Google's documentation and is not yet tried on a real account; if Google refuses, the card says the sign-in does not allow it.
* **A weekly plan (diya_weekly_plan.py).** "Plan my week: study physics 3 times for 1 hour" places each session in the earliest free gap of the calendar (9:00 to 18:00, never on an event, never in the past, one thing on different days first), says which did not fit, shows the plan, and proposes the first three sessions as ordinary events to approve (one message may lead to three actions).
* **A tidy-up of the Drive (diya_drive_tidy.py).** "Tidy my Drive" shows a manifest (every file, where it is, where it would go, the line that puts it back) for the files Diya made at the top of the Drive whose name begins with, or says, the name of a folder Diya made; the first three moves are proposed as ordinary moves. Nothing is renamed, binned or deleted.
* **Steps undone when a later one fails (diya_saga.py).** A runner for several approved steps: a step that fails cleanly undoes the earlier ones newest first by the undo each declared; a step whose outcome is not known stops the run and undoes nothing; an undo that fails is said and the others still run; nothing is retried. Tested end to end with Docs, Drive and Gmail stand-ins, the failure at each of the three points.
  **No plan kind is registered for it yet:** approving several steps as one plan is a different gate from approving each, and that is a decision for the owner.
* **Your data (diya_google_data.py).** `show`, `export --out FILE` (a new file only, no secret in it) and `purge --what actions|activity|replies|connections [--yes]`: what Diya keeps because of Google can be seen, taken away and cut off, each separately and only with `--yes`.
* **What is decided and not built:** `docs/GOOGLE_DECISIONS_2026-10-27.md` (one account, direct calls and not a Google tool server, no filters or permanent deletion, no calendar making, no sync between lists, no queue of writes, and the services Diya does not have), pinned by `tests/test_google_decisions.py`.
