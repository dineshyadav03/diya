# Dreaming: staged memory

Dreaming turns what you say across conversations into candidate facts. They are queued for review;
they reach the model only if you accept them.

## Running it

```bash
python dreaming.py      # one pass, from the repo root; output goes to dream_log.txt
```

One run is one pass and it never loops, so run it on a schedule. The author uses Windows Task
Scheduler every 30 minutes with `pythonw.exe`, which has no console; that is why the script writes
its output to the log file instead of the screen. Nothing else in the repo schedules it.

## What a pass does

1. Reads the user's messages, across all threads, that are newer than the checkpoint in
   `dream_state.json` (the id of the last message it handled). Assistant replies are ignored.
2. Asks the model for genuinely new facts, or `NONE`. The model never sees the profile, so it cannot
   drop what is already known.
3. Appends one JSON record to `dream_pending.jsonl`: timestamp, first and last message id, model
   name and the list of facts. The record is flushed to disk before the checkpoint moves.
4. Moves the checkpoint.

If a run dies between steps 3 and 4, the next run finds the record by its first message id and only
moves the checkpoint, so a batch is never staged twice. An unreadable queue stops the pass and
leaves the checkpoint alone. A torn last line from a crash is skipped, not treated as a batch. If
the model is unreachable, the pass logs it and retries next time.

## What the model is told

In every thread the model is told the **accepted** facts of reviewed memory (the review tool below), as
one system message, and nothing else about you. What Dreaming stages never reaches it on its own.

Dreaming has one mode: it always stages. `DIYA_DREAM_PROFILE_MODE=staged` is still accepted and means
the same as leaving it unset. `direct`, which used to append unreviewed facts to `user_profile.txt`, was
retired (it would now write a file nothing reads, and it was the one way for unreviewed text to reach the
model): setting it is an error that says what to do instead.

`user_profile.txt` is the **old** profile. The first time Diya starts (or first needs it) its lines are
imported as accepted facts, once; the file is never changed and never read again, so editing it no longer
changes what the model knows. Change that with `python diya_review.py add`, `retire`, and so on. At
startup Diya says how many facts it is telling the model and how many candidates wait, and warns if the
old file has lines that are in no fact. A running server keeps its old code: restart the API after
upgrading to this.

## Reviewing staged facts

```bash
python diya_review.py ingest          # copy newly staged facts in as candidates, and check them
python diya_review.py list            # the candidates; `list accepted`, `list all` show the rest
python diya_review.py show 3          # one fact: its flags, the messages it came from, its history
python diya_review.py accept 3        # ...or reject 3, edit 3 reworded text, retire 3, restore 3, reopen 3
python diya_review.py add likes tea   # a fact you type yourself goes in already accepted
python diya_review.py export          # the accepted facts, in the user_profile.txt format
python diya_review.py import-profile  # take the existing user_profile.txt in (the file is never changed)
python diya_review.py verify          # check the store is consistent
```

It needs no model and no network. Each candidate is checked, by plain code, against the messages it was
extracted from: `ungrounded` (few of its words appear in them), `duplicate` or `similar` to another fact,
`previously_rejected`, `instruction_shaped` (it talks to the assistant or gives an order rather than stating
something about you). These are hints beside the fact, never decisions: only you accept. A fact is limited
to 200 characters and the accepted facts to 2,000 in total, so what the model is eventually given stays
small (a fact that would take it over is refused, with the reason, never silently cut); retire a fact to
make room. Nothing is ever deleted: every change is recorded in `fact_events`, and
everything the tool prints from the database has its control and invisible characters shown as escapes.

## Files and settings

| File | Setting | Purpose |
|---|---|---|
| `dream_pending.jsonl` | `DIYA_DREAM_PENDING_PATH` | staged candidate facts |
| `dream_state.json` | `DIYA_DREAM_STATE_PATH` | checkpoint |
| `dream_log.txt` | `DIYA_DREAM_LOG_PATH` | output of scheduled runs |
| `diya.db` | `DIYA_DB_PATH` | reviewed facts (`facts`) and the history of every change to them (`fact_events`), beside the chats |
| `user_profile.txt` | `DIYA_PROFILE_PATH` | the old profile: imported once as accepted facts, then not read |

All of these hold personal data and are gitignored. `milestone4_watcher.py` (a Phase 1 notes
watcher) is a separate job; it is not part of Dreaming and the assistant does not read its output.
