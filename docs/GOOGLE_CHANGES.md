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

More follow below as they are built.
