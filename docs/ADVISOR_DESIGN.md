# A harness advisor that proposes fixes and never applies them (unit H1, step 1)

> **Status (2026-10-13):** step 1 built (`diya_advisor.py`, `DIYA_ADVISOR_DIR`). Unit H1 of `docs/RESEARCH_PLAN_2026-10.md`; the research is `RESEARCH.md` entry 30 (harness learning, MASS, VERA).

## What it is for

Every gate in `diya_intent.py` was found the same way: run the real model, see what the code got wrong, fix the rule, keep the case so it can never come back. The research of the week says that loop (an agent
reading its own failures and editing the program around a frozen model) is where the gains are. H1 is the loop's safe form for Diya: **a script that finds the failures, proposes an edit as a patch, tests the
patch against everything known, and then stops.** It never changes a file of Diya's. You read the patch and apply it (or do not).

## What step 1 covers, and why only that

- **One gate: "is this message asking for a reminder?"** (`diya_intent.is_reminder_request`). It is one regular expression, it has a labelled set of 71 messages (`tests/labelled_requests.py`), 50 everyday messages added by this unit (`tests/labelled_everyday.py`) and six
  documented misses ("Ping me at 5 about the call", "Wake me up at 7", ...), and a miss is the safe direction (the person can say "remind me to ..."). More gates are one entry in a table (`GATES`).
- **One kind of failure: a request the gate refuses** (a false refusal). A false allowance ("How do I set a reminder on my phone?") needs a *guard*, not another phrase, and is only listed.
- **No model.** The proposer is a plain search over small edits (a new alternative taken from the start of the missed message). A 4B model asked for a patch would be slower, vaguer and no easier to check;
  the evidence that decides is arithmetic over cases.

## The thing this had to get right

A first try, measured on 2026-10-13 before any design: for the six misses, **dozens of candidate edits fix the miss and break none of the 71 labelled cases**, including ones no one would accept:
`\bcall\b`, `\blunch\b`, `\bit's\b`, `\blet\s+me\b`. Seventy-one cases cannot tell a good generalisation from a harmful one, because they hold no message that contains "call" without being a request.
So "fixes it and breaks nothing labelled" is **not** enough, and a proposer that stopped there would hand you patches that turn "let me know the weather" into a saved reminder.

What the advisor does instead:

1. A candidate is only the **start of the missed message** (its first two to five words, up to the first number, containing "me"/"us"/"myself"): the shape of a request, not any word in it.
2. A candidate must break **none** of the labelled cases (the 71, the 50 everyday messages, plus any you have added with `add`). The everyday messages are the fix for the weakness above: they are ordinary
   sentences that contain the words a careless edit would add ("Let me know what the weather is like", "Tell me at least three facts about otters", "Wake me up inside is a good song").
3. A candidate is then counted against a **background of your own past messages** (read-only, from your chat history, nothing sent anywhere): how many messages that were *not* matched before would now be.
   The best candidate is the one that matches the fewest, then the shortest. If every candidate that fixes the miss would also newly match more than a few of your own past messages (`MAX_NEW`, 2), the
   advisor says so and proposes nothing: **no safe fix is a result**, not a failure.
4. The report shows, for each proposal, what it fixes, what it newly matches in the background (a few examples, so you are the judge), and what else has to change if you accept it.

## Measured

On the real reminder gate, 2026-10-13, with no background (the first two rows) and with the 87 messages in the owner's history (the last):

| Labelled set the search had | What it proposed for the six misses |
|---|---|
| the original 71 only | `ping me`, `alert me`, `wake me`, **`let me`**, `buzz me`, `tell me at`: the fourth would turn "let me know the weather" into a saved reminder |
| plus the 50 everyday messages | `ping me at`, `alert me`, `wake me up at`, `let me know at`, `buzz me`, `tell me at noon`: all six fixed, none breaks any of the 119 cases |
| the same, plus 87 of the owner's own messages as background | the same six: none of the 87 would be newly matched, which says little (see below) |

With `--run-tests` the combined patch was applied to a **private copy** of the repository and the gate's tests were run there: 43 passed and 1 failed, and the one that failed is
`test_the_known_failures_are_measured_not_hidden`, which pins the six misses as still refused. That is the expected result of a good fix, and why the report tells you which lists and tests to update.
The whole run takes about seven seconds. Nothing of Diya's was changed: the repository's files are hashed before and after in a test.

**What this does not show.** The labelled messages and the everyday set were written by the person who wrote the gate and the advisor, so they show that the loop works, not that the patches are right for
real use. Eighty-seven past messages is too few to reject a harmful edit: it never contains "let me know the weather" unless you happened to type it. The background only becomes a real check as the history
grows, and until then the everyday set does that job; add the messages that go wrong with `add` and they are tested on every later run.

## What it writes (and nothing else)

`DIYA_ADVISOR_DIR` (default `advisor/`, git-ignored: it can quote your own messages) holds `report.md`, one `proposal-N.patch` for each proposal, and `cases.jsonl` (the messages you added with `add`).
It reads the notes of no folder and changes no file outside that folder: a test hashes the real source files before and after.

## Commands

    python diya_advisor.py propose [--gate reminder]    find the misses, search, write the report and patches
    python diya_advisor.py add reminder "Ping me at 5" yes|no    record a message the gate got wrong (yes = it IS a request); next `propose` has to get it right too
    python diya_advisor.py list                          the gates, how many cases each has, and how many are known misses

To accept a proposal: read `report.md`, run `git apply advisor/proposal-1.patch` (it changes `diya_intent.py` only), then move the cases it fixed in `tests/labelled_requests.py` from `LIMIT_REFUSED` to
`REQUESTS` and update the counts the tests pin (the report says which). Those tests pin the known misses on purpose, so a good fix **will** fail them until you do; that is the proof they are watching.

## Limits, plainly

- It cannot fix a false allowance, a gate made of logic instead of one pattern, or a message whose request is in the middle ("Tomorrow at 9, ping me").
- The background is only as good as your history: with a short history almost nothing is ever newly matched, so a patch looks safer than it is (measured: 87 messages rejected nothing). The report says how many past messages it looked at.
- It proposes patches for the pattern; it does not write the test changes.
