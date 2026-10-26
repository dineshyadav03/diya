# Changelog

What changed for the person using Diya, newest first, from the git history (commit ids are in `git log`). It starts on 2026-10-10, when the project began to be used day to day. Each release that changes the database says
which migration it carries; the table below the notes says what each migration holds and how to come back from one.

## 2026-10-26
* **Gmail beyond reading, three new cards.** *Gmail: drafts*, *Gmail: send* and *Gmail: organise* (each its own Google permission, off until you add it and press Connect). Diya can save or replace a draft, send an email, reply or forward, and archive,
  mark read or unread, star, label and bin one email, each only when you approve exactly what the card shows. An email goes only to an address you typed; the email a reply or forward is about is found from your words (several matches: it asks which);
  at most 20 sent a day; never a hidden copy or an attachment; every send is read back from Sent. (`docs/GOOGLE_CHANGES.md`, `docs/GOOGLE_LIVE_SMOKE.md`)

* **Calendar, beyond adding.** Rename, move or cancel one of your own events (no guests), invite typed addresses, accept or decline an invitation, and add an event that repeats (two new cards on the permission already added). Ask "when is my dentist
  appointment?" or "when am I free tomorrow?" and the answer comes from the calendar by code, not from the model. (`docs/GOOGLE_CHANGES.md`)
* **Google Drive and Docs.** Ask "search my drive for ..." or "read my study plan doc" and code reads it (a *Google Drive (read)* card; a model with no tools words the answer, as for mail). Rename, move, bin, bring back and share the files Diya made, and change the words in a Doc Diya made (a *Google Drive (change)* card), each only when you approve it. Sharing is with one address you typed, never public.

## 2026-10-20
* **Episodic recall.** A question is answered with the few earlier messages of yours closest in meaning to it, even if they are weeks old and no longer in the chat window. On invented data with the real models, the
  right message was found 20 times in 20 and the chat model went from 1 right answer in 20 to 20 in 20 (`docs/EPISODIC_DESIGN.md`). *Migration 24.* `DIYA_EPISODIC=0` turns it off.
* **"Forget everything about <a topic>"** now retires the facts that say all of the topic's words (at most 8), not only a person's; each can be taken back from the line under the reply.
* **Memory as an Agent Memory Repo** (`python diya_review.py export-repo FOLDER`): `MEMORY.md` plus one note per person, in the open format Devin's memory uses. (`docs/MEMORY_REPO_DESIGN.md`)
* **"How fast answers come" on the Status page**: the middle and the slow end of the last 7 days of answers, and how many failed, from numbers only (no text is kept); and how long the oldest message has waited to be
  read for facts. A **"This computer" line** says how much memory is free, how busy the processor is and how much Diya's API holds, and warns under a gigabyte free. *Migration 25.*
* **Playbooks**: steps you write once in `playbooks/<name>/SKILL.md` (Devin's open Agent Skills layout) and hand to the model with `@name` or when a request is close in meaning. They grant no tool and skip no approval.
  A read-only Playbooks page lists them and any file that cannot be used. (`docs/PLAYBOOKS_DESIGN.md`)
* Forgetting a message or a fact for good now also removes the record of the times a fact was said again.
* `scripts/probe_supermemory.py` and `docs/SUPERMEMORY_LOCAL_TRIAL.md`: how to run supermemory's local server in a throwaway container and measure it against Diya with invented messages. Diya did not run it.

## 2026-10-18
* **Facts fade unless said again.** A fact that says it is a passing state ("for now", "currently reading") is retired after a while unless you say it again or press Keep; a repeated sentence is now counted as a mention of the
  fact it repeats. Retired, never deleted; Restore brings it back. *Migration 23.* (`docs/FADING_DESIGN.md`)
* **A Markdown copy of memory.** `python diya_review.py export-markdown` / `restore-markdown`. (`docs/MARKDOWN_MEMORY_DESIGN.md`)
* **Recall says when it is partial**: when the memory is bigger than one message can hold, the model is told how many facts it was not shown.
* **Forget for good.** Delete a message and its reply, or a fact's words, so that nothing is left in the database file. (`docs/FORGET_DESIGN.md`)
* **Every waiting action shows its risk, what it reaches and how far it can be undone**; every connection shows what it can do and what Google granted.
* **A Google change counts only after it is read back; two windows can no longer silently overwrite each other's edit of a fact.**
* **A Pause switch** that stops actions, automations and Diya writing first; a catalogue of what every tool can do; a red-team test that assumes the model obeys every injected instruction.
* **"How do you know that?"** is answered from the record. **Every Dreaming pass leaves a receipt.** *Migration 22.*
* **A message and its reading job are saved together; a database is copied before it is migrated.** (`docs/BACKUP_DESIGN.md`) Found later the same day, by looking at the real database: migration 23 had reached it through a
  scheduled job with no copy taken, because the rule lived only in the API's start-up. It is now one function (`diya_backup.guard_migration`) that Dreaming, the notifier, the review and actions tools, the Telegram bridge and the
  terminal chat call first.
* **Checked automatic backups and a Status page** that says whether each part is working. **Sign-ins are stored encrypted with Windows**, the Google sign-in uses PKCE, Disconnect takes the permission back.
* **Google writes (calendar event, Google Task, Drive folder, Google Doc) after your approval; Gmail, read-only.** None tried against a real account.
* **No message is lost while another is read; an append-only activity journal.** *Migrations 20 and 21.*
* The task sheet (298 tasks) is kept up to date from `docs/tracker/progress.csv`; `scripts/smoke.py` checks a fresh clone; `docs/CAPABILITIES.md` says what kind of proof each capability has.

## 2026-10-16
* Categories you can manage, and a skill that studies a repository. One chat instead of many. A remembered event whose day has passed is retired by itself. A question-and-answer measurement of memory.
  *Migrations 17 to 19.*

## 2026-10-14
* Diya knows what she is (asked how to connect Google, she answers from what is built). Automatic memory remembers ordinary facts (two privacy judges). A greeting no longer invents a name. MCP client (read-only tools you
  approve one at a time). The chat answers "what do my notes say about X?". A harness advisor that proposes tested patches and never applies one.

## 2026-10-13
* Knowledge pages from your notes. Relevance recall once memory outgrows the room. Answers to general questions with a web lookup. Google set up from the Connections page. Tap-to-talk fixed. *Migration 16.*

## 2026-10-11 and earlier in October
* Automations; reminders that remember when they were ticked off (*migration 15*); Diya has a voice and writes first (*migration 13*); a phone channel (Web Push, Telegram; *migrations 10 to 12*), switched off; one command to
  start everything; questions Diya raises herself (*migration 9*); memory that is read the moment it is said (*migration 8*); the audit of 2026-10-10 and its fixes (a passcode for the UI, one data folder, a model switch).

## Migrations
The schema only moves forward. Each step runs in one transaction that is rolled back whole if it fails (`diya_db.apply_migrations`), and **before any step is applied to a database that has data, a checked snapshot of it is
taken** (`diya_backup.before_migrating`); if the snapshot cannot be made, Diya does not migrate.

| No. | Holds | Doc |
|---|---|---|
| 1–2 | messages, threads; reviewed memory (`facts`, `fact_events`) | `docs/STAGE2_DESIGN.md` |
| 3 | reminders get a real due time | `docs/PROACTIVITY_DESIGN.md` |
| 4 | who a fact is about (`people`) | `docs/PERSON_MEMORY_DESIGN.md` |
| 5 | actions and their trail | `docs/ACTIONS_DESIGN.md` |
| 6 | the to-do list | `docs/TASKS_DESIGN.md` |
| 7 | repeating reminders | `docs/SCHEDULE_DESIGN.md` |
| 8–9 | messages read for facts at once; the questions Diya raises | `docs/AUTO_MEMORY_DESIGN.md` |
| 10–12 | who was told what; Web Push devices; the Telegram bridge | `docs/PUSH_DESIGN.md`, `docs/TELEGRAM_DESIGN.md` |
| 13 | what Diya said first | `docs/PROACTIVE_DESIGN.md` |
| 14 | automations | `docs/AUTOMATIONS_DESIGN.md` |
| 15 | when a reminder was ticked off | `docs/PROACTIVITY_DESIGN.md` |
| 16 | the embedding of each fact (a cache) | `docs/RECALL_DESIGN.md` |
| 17–19 | small app settings; categories; merged categories and suggestions | `docs/ONE_CHAT_DESIGN.md` |
| 20 | the capture queue | `docs/MEMORY_DURABILITY_DESIGN.md` |
| 21 | the activity journal (append-only) | `docs/ACTIVITY_JOURNAL_DESIGN.md` |
| 22 | Dreaming's receipts (append-only) | `docs/DREAMING_RECEIPTS_DESIGN.md` |
| 23 | mentions (a fact said again) and a count of facts that faded | `docs/FADING_DESIGN.md` |
| 24 | the embedding of each message you sent (a cache) | `docs/EPISODIC_DESIGN.md` |
| 25 | how long each chat turn took and whether it worked (numbers only) | `docs/HEALTH_DESIGN.md` |
| 26 | which messages a category merge moved, so the merge can be undone | `docs/ONE_CHAT_DESIGN.md` |
| 27 | what you thought of a reply: helpful or not, a reason, a note | `docs/FEEDBACK_DESIGN.md` |
| 28 | how the computer was doing every few minutes: memory free, processor busy, what the API held (numbers only) | `docs/HEALTH_DESIGN.md` |
| 29 | the activity record can forget: the words of what a forgotten message made a tool do are blanked, rows older than a limit you set are removed, each with a receipt (counts only) | `docs/ACTIVITY_JOURNAL_DESIGN.md` |

`MIGRATIONS` in `diya_db.py` is the authority on the exact numbers.

## Coming back from a bad update
1. Stop Diya: `python diya_run.py --stop`.
2. `python diya_backup.py list` shows the snapshots, newest first. The one taken just before the migration is the newest one made at the time of the update.
3. `python diya_backup.py verify <snapshot>` checks it opens and passes SQLite's check and the memory's own trail check.
4. `python diya_backup.py restore <snapshot> --to <a new path>` puts it at a **new** file (it never overwrites). Point `DIYA_DB_PATH` (or move the file into place) at it, and start the **previous** version of the code
   (`git checkout <the earlier commit>`): an older Diya reads a database that an older schema wrote.
5. Run `python scripts/smoke.py --live https://127.0.0.1:8080 --token <token>` and look at the Status page.

What this does not cover: anything written after the snapshot (messages sent since the update are not in it), and the sign-ins, which are kept apart from the database (`docs/SECRETS_DESIGN.md`) and are not touched by a restore.

Proved in `tests/test_backup.py`: an older database gets a checked snapshot before it is migrated and the snapshot is the way back; a migration that fails changes nothing; a snapshot that cannot be made stops the migration.
