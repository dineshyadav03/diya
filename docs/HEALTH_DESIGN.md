# The Status page: is Diya well? (2026-10-18)

**Why.** The blueprint (DIYA-014, "Live status for API, LLM, DB, queue, Dreaming, OAuth and backup age") asks for one place that says whether Diya is working, instead of finding out when a message fails. Several failures this project met were silent: a notifier task that stopped, a message that was never read for facts, a model that was not loaded.

**What it shows** (System → Status, `GET /api/health`, `diya_health.py`). One line per part, each saying what was actually looked at *just now*, and a state: **working**, **needs a look**, **not working**, or **switched off**.

| Part | What is looked at |
|---|---|
| Diya's API | that this page was answered |
| Memory (database) | opens read-only, SQLite's quick check, how many messages and remembered facts |
| Chat model | Ollama answers (two seconds at most) and lists the configured model |
| Reading messages for facts | the capture queue: waiting, failed after three tries, read, not worth reading (off when automatic memory is off) |
| Dreaming | when its log was last written (a day and a half is stale) |
| Connections | which are connected, and any whose stored sign-in cannot be read here |
| Backup of the memory | the newest checked snapshot and its age (two days is stale) |
| Sign-ins at rest | encrypted for this Windows user, plain because the system cannot, or plain because it was switched off |
| Tools and accounts | how many tool calls in the last day did not work |

**Rules.** Nothing says "working" for a thing it did not look at; a part that is switched off says so and does not make the whole look worse; looking changes nothing (no snapshot is made, no database written); and **a part that cannot be checked is reported as not working, not skipped** (the report never falls over because one part is broken: that would hide the very part). The page refreshes once a minute and keeps what it showed if a refresh fails.

**Proof.** `tests/test_health.py` (13 cases) with a stand-in Ollama; and the report was run against a private copy of the owner's real database.

**Not done.** Per-connector "last successful call" and quota; a history of states over time; a push notification when something turns bad. The "Dreaming" line uses the log file's modification time, which is an approximation of "ran": it does not know whether the run found anything.

## Added 2026-10-20 (task DIYA-017): how fast answers come, the oldest waiting job, and the computer itself

* **How fast answers come** (`turn_stats`, migration 25): every chat turn, plain or streamed, leaves one row of NUMBERS: which route, how long it took in milliseconds, whether it worked, how many tools it called. No
  word of anyone's is in the table (a test checks its columns), the newest 5,000 rows are kept, and a record that cannot be written never fails a chat. The Status line says, for the last 7 days: how many answers,
  how long half of them took or less, how long 19 in 20 took or less, and how many failed. It is a warning when three of the last ten failed and bad when the last five did.
* **The oldest waiting job**: the "Reading messages for facts" line now says how long the message that has waited longest has waited.
* **This computer** (`diya_machine.py`): memory free of the total, how busy the processor was over a quarter of a second, and how much memory Diya's API holds, taken when the page is opened and not stored. Windows
  through the system's own calls, Linux through /proc, anything else says it cannot tell. A warning under a gigabyte free, because the models are then pushed out of memory and every answer is slow.
  On this laptop when first tried: 4.2 of 15.7 GB free, processor 15% busy, the API holding 16 MB.
* **Not done:** CPU and memory are shown when the page is opened, not logged over time, so a spike an hour ago is not on the record. The sheet's wording asks for them "logged"; that part is open.

