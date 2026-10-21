# Time in Diya's memory (2026-10-21)

Written after reading Mem0's article on time in memory. Its point: a memory has two clocks, **when something happened** and **when it was written down**, and an assistant that mixes them up gets
"last weekend" wrong the moment it is read a month later. This page says what Diya already did, what was missing, what was built today, and what was left alone on purpose.

## What Diya already had

| The article's idea | Diya before today |
|---|---|
| Keep when it was written | Every fact has `created_at`; every message has its time; every change is a dated line in `fact_events`. |
| Facts that change: keep the history, use the latest | A correction retires the old fact and says what replaced it (`supersede`, `replaced`, `undo_replace`); the old words stay readable and can be restored. |
| Facts that expire | Passing states fade (`diya_fade.py`); event days retire themselves after the day (`retire_gone`). |
| "Now" as an input | `diya_time.py` takes the clock as an argument; tests never depend on the real date. |
| Turn a stored moment into the person's day | Local-time conversion in the places that show a time. |

## What was missing, and what was built

1. **"Last weekend" stayed "last weekend".** A fact saved as "ran a 10K last weekend" in June was told to the model in October with the same words, so the model could read it as last weekend *now*.
   `diya_when.py` reads relative phrases (yesterday, last night, last weekend, last week, last month, 3 weeks ago, in 2 months, last Friday, ...) against the day the **message** was written, and
   `Memory.render_for_model` adds the answer in brackets: "ran a 10K last weekend (that was the weekend of 14-15 Jun 2025)". The stored words are never rewritten; the Memory page and the exports still
   show the person's own words. A fact written today is told as it is. At most three phrases per fact are annotated.
2. **Precision is kept honest.** A month stays a month ("September 2026"), a week a week, "2 weeks ago" is "about Wed 7 Oct 2026". A phrase that cannot be told without guessing (next Friday, next weekend,
   a bare Friday, "this Monday" after Monday has passed, a month with no year) is **left alone** rather than turned into a wrong date.
3. **Facts that say when they end.** "Has a pass until 31 Jan" now fades the day after 31 Jan, a date fixed by the sentence itself (saying it again does not move it; Keep still protects it). A date that has
   already passed is ignored, so "lived in Pune until 2019" does not fade. The Memory page says "It says it lasts until ... so it fades the day after unless you keep it", and the "how do you know" answer says the same.
4. **Questions about a time.** In episodic recall (`diya_episodic.py`), a question that names a time ("what did I say last week?") gets a small ranking boost for earlier messages from those days (it can never
   lift a message over the closeness threshold), and a question that is only about *when* returns the newest messages from those days with no embedding at all.
5. **"What did you know on 12 Oct?"** `Memory.as_of(moment)` replays the history: a fact counts if its events up to then leave it accepted, in the words it had then. The question is answered by code in
   `diya_provenance.py` (no model, so nothing is invented), says what has been added or dropped since, and can be narrowed by a topic ("about my dog"). The same from the command line:
   `python diya_review.py as-of 2026-10-12`. This is the "you forgot" case: it shows whether Diya ever knew a thing, and since when.

## Left alone, on purpose

* **No stored event-time columns.** The article stores an event time next to the write time. Diya computes the event day when the fact is *read*, from the message it came from, so nothing in the database
  changed (the real database is at schema 25 and stays there) and an improvement to the reading rules improves old facts at once.
* **No time zones beyond this computer's.** Days are the person's local days on this computer. Travel across zones would need a stored zone; it is not built.
* **No decay-by-use ranking.** The article reorders by how often a memory is used. Diya's fading removes passing states and Keep protects what matters; ranking by use only matters once memory is larger than
  the room the model has (`docs/RECALL_DESIGN.md`), which the real memory is nowhere near (12 accepted facts on 2026-10-21).
* **No "latest only" switch.** Diya's reads already return only accepted facts; the old ones are reached through the history, not mixed in.
* **Who a fact is about** in a replay is as it is now, not as it was on that day.

## How it is proved

`tests/test_when.py` (about a hundred labelled phrases across days of the week, month and year edges, a leap year, New Year), `tests/test_told_dates.py` (the real memory and database), `tests/test_fade.py`
(explicit end dates), `tests/test_episodic.py` (time ranking, with stand-in vectors: the real embedding model was not measured on this), `tests/test_as_of.py` (the replay, the question, the command line and the chat).
