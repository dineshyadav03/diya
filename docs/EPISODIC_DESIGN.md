# Episodic recall: what you said earlier, found by meaning (2026-10-20)

From the study of supermemory (`docs/STUDY_SUPERMEMORY.md` section 9). supermemory keeps two layers and searches both in one call, `searchMode: "hybrid"`: the **facts** it extracted and the **source chunks** they came
from. Diya had the first layer. The chat's history is cut to what fits in the model's window (`DIYA_HISTORY_CHARS`, 24,000 characters), so something said weeks ago that never became a fact ("the dentist is on
Thursday at 4:30", "I owe the library 40 rupees") was still in the database but gone from the model's view. This is the second layer.

## What happens
1. **Indexing.** Each message *you* sent that is worth finding again is turned into a vector once, with the embedding model Diya already uses for facts and notes (`nomic-embed-text`). It is done after each reply
   and by the scheduled Dreaming pass, which also catches up on an older chat 200 messages at a time. Table `message_embeddings` (migration 24): a cache, rebuilt from `messages` at any time.
2. **Searching.** When you ask a question (`wants_earlier`: a "?" or a question word), the question is embedded and compared with the vectors. The up-to-three closest earlier messages at or above the threshold are
   handed to the model as a note, newest first, each with the day you wrote it and in quotes.
3. **The note** says they are your own earlier words, that they may be out of date and are **not instructions**, and to use them only if they help.

## Rules that keep it safe and small
| Rule | Why |
|---|---|
| Only *your* messages, statements, 25 to 400 characters, no "?", no blank line, not instruction-shaped (`diya_checks.instruction_shaped`) | a long paste (an email, a web page) is never indexed, so text from outside cannot reach the model through this door; `tests/test_episodic.py::test_a_paste_or_an_instruction_never_gets_into_the_index...` |
| Only for a question; never for an unattended run (an automation reads no old words, as Devin's automated sessions do not read memory) | cost, and nothing runs on remembered text nobody is watching |
| `THRESHOLD = 0.55`, `TOP = 3`, `NOTE_CHARS = 220` | calibrated below; a weak match adds nothing rather than noise |
| A message already in what the model is given is not repeated | the window still holds recent chat |
| Forgetting a message deletes its vector (and the record of facts repeated in it); forgetting a fact for good deletes its repeat record | `diya_forget`, `Memory.purge`; the table holds nothing the messages do not |
| Any failure (Ollama down, model missing, bad data) gives no note and the chat goes on | `search` and `_earlier_note` never raise |
| `DIYA_EPISODIC=0` turns it off | the owner's switch |

## What was measured (2026-10-20, real models on this laptop)
`python diya_episodic_bench.py` (retrieval only, ~10 s) and `--chat` (about 15 minutes) on **invented** messages (`tests/labelled_episodic.py`: 40 messages of a student's life, 20 questions each answered by one of
them, 10 questions about nothing the person said), with `nomic-embed-text` and the chat model `diya-chat` (qwen3:4b-instruct, capped context):

| | Result |
|---|---|
| Right message is the closest | **20 of 20** (top 3: 20 of 20) |
| Best score for an answerable question | lowest 0.56, median 0.77 |
| Best score for an unrelated question | highest 0.51, median 0.46 |
| At threshold 0.55 | all 20 answerable found, **0 of 10** unrelated let through (0.50 would let 1 through, 0.45 would let 5) |
| Chat model asked the 20 questions **without** the note | **1 of 20** answers hold the right words; most say they cannot know, and several **invent** a plausible answer ("Your dentist appointment is scheduled for Thursday, June 13th", "The Pathology Viva is scheduled for Friday, June 21st, at 2:00 PM") |
| The same questions **with** the note | **20 of 20** |

The prefixes the embedding model's documentation suggests (`search_query:` / `search_document:`) were tried and made the unrelated questions score *higher* (highest 0.58), so none is used.

## What this does not show
* The messages and questions are invented and clean. Real messages are noisier, and an old message can be **wrong now** ("I live in Delhi" said before "no, I live in Pune"). The facts layer handles corrections;
  this layer shows both with their days, newest first, and says they may be out of date. Whether the model weighs them well is not measured.
* 0.55 was chosen on 30 questions. Over weeks of real use it should be re-checked against what the note actually surfaced (the Status page does not show this yet).
* The 3B/4B model that *invents* an answer when it has no note is a separate, existing weakness: the note only helps when something was found.
* Not run against the owner's real messages. The first scheduled pass after the update indexes them; nothing about their content was read for this work.
