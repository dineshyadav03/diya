# Memory durability: a message is not lost because another was being read (2026-10-18)

**The failure.** Diya reads each message the person sends for facts, in the background, one at a time, with a small local model. Before this change, a message that arrived *while a read was running* was **skipped** (it was never read again), because the reader's lock was busy. "I got another dog named Hog" could be lost simply for being said right after another sentence. The blueprint's "Hog test" (section 16) is exactly this: tell Diya something, and it must be right the next turn and after anything that could lose it.

**The change.**

- **A queue in the database** (`capture_queue`, migration 20): when a message is sent and automatic memory is on, its id is put in the queue in the same moment, before any model runs. States: `pending`, `done`, `skipped` (not worth reading, by code), `failed` (gave up).
- **A drain loop** (`diya_web.read_for_facts`) reads the queue oldest first, in batches of 50, one message at a time, with at most `MAX_CAPTURE_TRIES = 3` attempts each. Only one drain runs at once; after it releases the lock it **looks again**, so a message queued in the gap is not left waiting.
- **A restart loses nothing.** The queue is in SQLite; the next start (or the next message) drains what is pending. A message the model could not read three times is marked `failed` with the last error, and stays visible.
- **The model is given context for a correction.** "Actually his name is Hogg, not Hog" has no "I" or "my" in it, so before this it was never read. A correction of four words or more is now read, and for a correction without a first-person word the model is also given **the person's message before it**, so that "his" is somebody. Only then: other messages are read alone.
- **A correction that looks like what it corrects is no longer held up** by the "looks like a copy" check, but only when the model clearly names the fact it replaces; anything else still waits for a question, as before.

**Proof.** `tests/test_capture_queue.py` (the queue and drain), `tests/test_hog_regression.py` (told once → reaches the model next turn; still there after the chat's own history is cut off; survives a cold restart; a correction replaces and leaves the old fact in the trail; "forget" removes it; an email saying "your dog is Max" cannot change it; a question about the dog is never itself a fact), `tests/test_pronoun_correction.py`, and the rewritten `tests/test_live_capture.py` case ("arrives while a read is running → read next, not skipped").

**Measured with the real models** (2026-10-18, `diya-chat`, privacy judge `qwen2.5:3b`): the memory question-and-answer bench went from 28/30 to 32/33 (`docs/MEMORY_BENCH.md`), and the live safety bench is re-run after this change because a correction path was loosened (result recorded there).

**Not done.** A visible "reading..." state in the UI; retry of `failed` messages from a button (`Store.retry_capture` exists, nothing calls it yet).

## Two windows, one memory (DIYA-032)

The Memory page can be open on a laptop and a phone while the scheduled pass changes facts too. Every change to a fact is made in one transaction that first checks the fact is in the state the change applies to, so a decision (accept, reject, retire...) made on a fact something else already decided is **refused with a 409**, never flipped back. Rewording a waiting fact now also carries **the wording the person saw** (`expected_text`): if the fact has changed since, the edit is refused (`ChangedUnderYou`, HTTP 409: "was changed since you opened it, so your edit was not saved. Reload the page...") and nothing is written, instead of silently overwriting the other change. Two edits sent at the same moment cannot both win. An older client that sends no `expected_text` behaves as before. Proof: `tests/test_memory_concurrency.py` (7 cases, including two threads released together).
