# "How do you know that?": provenance answered from the record (2026-10-18; DIYA-022)

**Why.** A memory the owner cannot question is a memory they cannot trust. A model asked "how do you know I have a dog?" will produce a confident, plausible history that may be false. The blueprint (Part VI) asks that every recall show who told it, when, and how far it is trusted.

**What it does** (`diya_provenance.py`, called first in `Agent._ask`). A question in one of these forms is answered **by code from the memory's own record, and the model is never asked**:

- "how / why do you know ...", "how come you know ...", "how do you remember ..."
- "where did you get / learn / hear ...", "who told you ...", "when did I tell you ...", "what is your source for ..."
- "how do you know that?" with nothing named: tied to the words of Diya's last answer.

For each of at most three matching facts it says: the fact; **the person's own message it was read from, quoted, with its date**; how it got in (typed by the person, imported from the old profile file, read from a message and taken on by Diya under the memory rules, or accepted by the person) and when; whether it is retired, waiting or rejected; and where to change or forget it (its number on the Memory page). Matching is by words (with plural and tense endings taken off), live facts first; a retired fact is explained only when no live fact matches.

**Honesty rules.**
- If nothing in the memory matches and the question is about the person ("how do you know my favourite colour is blue?"), it says it can't find a remembered fact, and that the answer may have come from general knowledge, the web or a tool (the Activity page shows tools), none of which is kept as a memory. It does not invent a source.
- A question that is not about the person ("how do you know the weather in Pune?") is not taken: the model answers it as before.
- The question is recorded in the activity journal as a flow (`explain_memory`).

**Proof.** `tests/test_provenance.py` (32 cases), including the Hog scenario end to end with the real memory, and a run of the answer against a copy of the owner's real memory ("has a dog named hog": it quoted the owner's message from 14 Oct and the time they accepted it).

**Not done.** It does not show provenance in every reply (that would be noise: it is on request and on the Memory page); fuzzy or semantic matching of the question to a fact; provenance for knowledge pages and for what the model used from the notes.

## The benchmark (2026-10-20, task DIYA-027): `tests/test_provenance_bench.py`

Sixteen invented facts are made by the real pipeline (a message saved, read by live capture with a scripted model, put through the memory policy), so each carries a real source; 13 of them were accepted on the
first try and the rest were reworded to the first-person statements the live gate reads (the benchmark's own setup found that "The mess dinner is at 8 pm" and "My library card ..." in the third person are left
to the scheduled pass). Thirty-two questions of the "how do you know ...", "where did you learn ...", "when did I tell you ...", "who told you ..." kinds, two per fact, are scored: **correct** when the first
message quoted is the one the fact was read from, **wrong** when it is another fact's, **missed** when the answer has no history. Eight questions about things never said are scored for an **invented** history.

| | First run | After the fix |
|---|---|---|
| Correct | 31 of 32 | **32 of 32** |
| Wrong attribution | 1 | **0** |
| Missed | 0 | **0** |
| Invented a history for something never said | 1 of 8 ("where did you learn that I own a motorcycle?" was answered with the history of the guitar, on the shared word "own") | **0 of 8** |
| A corrected fact described as current | yes ("how do you know I live in Delhi?" after moving to Pune described the Pune fact and hid the retired Delhi one, on the shared word "live") | **no**: it says it no longer uses it |

**The defect and the fix.** Matching a question to facts needed only one shared word, so a very common word attached the wrong history. `_matching` now needs at least one word that tells facts apart (not in `WEAK`: own,
live, like, want, use, play, work, ...), unless the question is made only of such words ("where do I live?"). The 28 older tests of provenance still pass.
**What this does not show.** Thirty-two questions about sixteen invented facts, asked in the wordings the patterns recognise; a real person's phrasing will find questions it does not recognise (`asks_where_from` then
returns nothing and the model answers as it would have). No language model writes any of these answers, so this measures the code, not a model.
