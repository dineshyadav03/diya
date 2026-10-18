# Dreaming's receipts: what each scheduled pass read and did (2026-10-18; DIYA-030)

**Why.** Dreaming runs on a schedule every half hour, with nobody watching. Until now the only record was a text log, and the only way to know it was healthy was to read the log. The blueprint asks for a receipt per run: which messages it read, what it produced, what was held, whether anything went wrong, and how long it took.

**What is recorded** (`dream_runs`, migration 22; `dreaming.run_cycle`). One row for every pass, busy or idle:

| Field | Meaning |
|---|---|
| `started_at`, `duration_ms` | when, and how long |
| `first_message_id`, `last_message_id`, `messages_read` | the range of messages the pass looked at, and how many of the person's it actually sent to the model (those read live, and ones that only ask something, are not read again) |
| `staged` | how many possible facts the model proposed |
| `remembered`, `asked`, `not_kept`, `held`, `replaced`, `questions` | what the memory policy did with them (accepted, left to ask, a secret not kept, held because the profile was full, replaced as a correction, new questions made) |
| `categories_sorted` | messages put into a category |
| `outcome` | one plain sentence: "nothing new", "staged facts for the memory policy", "the model could not be reached: the checkpoint did not move", and so on |
| `errors` | what went wrong, if anything (a list) |

**Rules.**

- **Append-only.** Triggers refuse any `UPDATE` or `DELETE` (`the receipts are append-only`), like the activity journal.
- **A failure is a receipt, not a gap.** A model that cannot be reached, a staging failure, a memory-policy failure and an unexpected crash are each recorded with the reason, and the checkpoint is described (it did not move past what failed, so the next pass tries again; `docs/STAGE2_DESIGN.md`). A crash is still raised afterwards, so the scheduler sees the failure.
- **A receipt that cannot be written never fails the pass.**
- **Idle passes are counted, not listed.** About 48 a day would bury the ones that did something. The Activity page lists the busy passes and says how many idle ones there were in the last 24 hours.

**Where to see it.** `GET /api/dreaming` and the "What Dreaming did" section of the **Activity** page; the **Status** page's Dreaming line is taken from the newest receipt and says when the last pass went wrong (before this it was guessed from the log file's time).

**Proof.** `tests/test_dream_receipts.py` (14 cases): idle, busy, no facts, already read live, model unreachable, staging failure, crash, memory pass failure, append-only, receipt-write failure, the scheduled entry point, the route, safe text, the Status line.

**Not done.** Per-fact "merged" and "linked" counts (Dreaming does not merge or link yet: DIYA-031 and DIYA-147 to -150), and a receipt for the *live* reading of each message (those are in `memory_captures` and the capture queue).
