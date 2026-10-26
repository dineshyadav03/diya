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
