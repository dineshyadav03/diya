# Talking to Diya from Telegram: design note and what was built (unit P4)

> **Status (2026-10-11):** written before the code, then built (`diya_telegram.py`, `tests/test_telegram.py`). **Nothing has ever been sent to or received from Telegram.** No bot exists, no
> account was made, no token was seen: every test runs against a scripted stand-in for Telegram's Bot API. This is "C. Talk" of `docs/PHONE_CHANNEL_DESIGN.md`, the one part of the phone
> channel that sends WHAT YOU SAY through a third party. The phone design said it was to be built only if the owner accepts that, and "the owner asked for the whole roadmap" is not
> that acceptance: the code is switched off (`DIYA_TELEGRAM=1`), needs a bot token the owner makes themselves, and does nothing until they pair it. Facts about Telegram's API below are from
> general knowledge, **not checked against its current documentation: check each before relying on it.**

## 1. What is built and what it is for

A long-running program (`python diya_telegram.py`) that asks Telegram for new messages (long polling, so nothing listens on this computer and no port is opened), keeps only the ones that come
from the one paired owner in a private chat, answers each with the same `Agent.ask` the chat page uses, and sends the answer back as plain text. Everything else is dropped.

## 2. The rules, and where each one lives

1. **A message is the owner's only if it comes from the paired owner.** The owner's numeric Telegram id is recorded by pairing and nothing else records one. An update from any other id, in any
   kind of chat, is dropped **without an answer** and without being stored: a stranger learns nothing, not even that a bot is there. (The one thing an unpaired sender can do is send the pairing
   code; see 3.)
2. **Approvals are never given by chat.** The module never calls the actions store's approve, reject or resolve (a test reads the source for it), has no route to it, and answers a message that
   starts with `/` with a fixed line pointing at the app. An action the model proposes during a chat is announced in the reply like any other text and is decided only in the UI.
3. **Pairing** is started on this computer, not in the chat: `python diya_telegram.py --pair` makes a one-time code (12 letters and digits without the confusable ones, valid 10 minutes), shows it on
   the terminal once, and keeps only its hash. The owner sends that code to the bot from their own account; if it matches (compared in constant time) the sender's numeric id becomes the owner and the
   code is gone. Five wrong guesses void the code. Pairing from a command rather than a UI button is a deliberate narrowing of the phone design: whoever can run a command on this computer is the owner
   by construction, and a button would need a route, a proxy and a page for something done once. `--unpair` forgets the owner (and any code); after it the bot answers nobody.
4. **The same code as the chat** (`Agent.ask`, the same history window, the same gates for reminders, tasks and tools), in one thread called "Telegram". Nothing here adds a tool.
5. **What leaves the computer is what the owner types and what Diya answers**, both readable by Telegram (bot chats are not end-to-end encrypted). That is the price of this channel and the reason it
   is off by default. Nothing else is sent: not memory, not the database, not a file.
6. **Fails closed and quiet.** A bad token, a network error, a Telegram error: one line with the kind of failure (never the token, never a URL, never a message), then a wait that grows, then another try.
7. **Text only, a fixed length.** A photo, a file, a voice message, a sticker, a forwarded message, a message sent by a bot, a message with a "via bot" or "sender chat", an edit and a group message are not
   read; the owner is told in a fixed line what is not read (unknown senders are told nothing). Nothing is downloaded, opened or stored. A link in a text is just text: this program never fetches it. At most 2,000
   characters are read; the reply is cut at 4,000 and sent with no formatting and no link preview.

**Rate:** at most 30 owner messages an hour; the 31st is answered once with a fixed line and the rest are dropped until the hour has room. **Order of work:** the update's number is saved BEFORE it is
handled, so a crash in the middle loses that one message and never runs it twice (a reminder added twice is worse than a message that needs sending again).

## 3. What is stored (migration 12: `telegram_state`)

A small key-value table: `owner_id`, `offset` (the last update number handled), `thread_id` (the Telegram thread), and while pairing `pair_hash`, `pair_expires` and `pair_attempts`. The bot token is NOT here:
it is in its own file (`telegram.token` in the data folder, made by `--set-token`, which reads it without echoing it, checks its shape, and saves it readable by the owner only; the file name is
gitignored). Nothing prints, logs or returns it; the one place it must appear is the request address Telegram's API requires, and every error from that request is reduced to the name of its
kind before it is said, because the library's own message would contain the address.

## 4. What is not built

No commands (settings, approvals and pairing are in the app or on this computer), no groups, no files in or out, no inline buttons, no webhooks (they would need a public address), no live memory capture of
what is said here (Dreaming reads it on its next pass like any other thread, because it is stored like one; the instant reading of unit A4 is a thing the API does after a chat reply and this program does not), and no
notification of questions or actions over it (that is Web Push, `docs/PUSH_DESIGN.md`).

## 5. Verified, and not

Tests drive the module with a scripted Telegram (every drop rule, the pairing, the limits, the order of work, the redaction of errors, the no-approval source check) and a mutation run of the code. **Not
verified, and only the owner can:** that Telegram's real API answers the shapes the stand-in uses (the field names for forwards and replies have changed over versions; the module checks the old and the new),
that long polling behaves as described, that the token file works on this machine, and that a real bot made by BotFather accepts the requests. The first real run should be with a bot the owner made for
this, a private chat, and the owner watching.

## 6. Turning it on (the owner's steps; none of this has been run)

1. In Telegram, talk to `@BotFather`, `/newbot`, and keep the token it gives you to yourself. A bot is its own account and can be deleted there.
2. `DIYA_TELEGRAM=1` in the environment of the program, then `python diya_telegram.py --set-token` (the token is asked for without being shown, and saved in `telegram.token` in the data folder).
3. `python diya_telegram.py --pair`, and send the code it shows to your bot from your own account within ten minutes. The bot will not answer anyone until then.
4. `python diya_telegram.py` and leave it running (it is not scheduled and nothing starts it; `diya_run.py` does not know about it). Ctrl+C stops it. `--unpair` makes it answer nobody again.

The one command to avoid: sending the bot token to anyone, or typing it into a chat: the file is the only place it belongs.
