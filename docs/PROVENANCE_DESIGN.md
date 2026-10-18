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
