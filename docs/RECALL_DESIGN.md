# Relevance recall: telling the model the facts for THIS message

> **Status (2026-10-13):** built (`diya_recall.py`, `diya_memory.open_memory` / `Memory.render_for_model`, migration 16, `DIYA_RECALL`, `DIYA_MEMORY_STORE_CHARS`). Unit R1 of `docs/RESEARCH_PLAN_2026-10.md`.
> Needs the API restarted to take effect. With 7 live facts it changes nothing today; it is for the weeks after automatic memory has been on.

## The problem

Every accepted fact was told to the model in every message, in one list of at most 2,000 characters (about 35 short facts). A memory at that limit **refused any new fact**. That is the right design while the
memory is small (ConvoMem, `RESEARCH.md` entry 28: a short history in the prompt beats a retrieval system), and it stops being possible once automatic memory has been running for a few weeks. Past that point
there are two bad choices: stop learning, or tell a 4B model so much that the fact it needs is lost in the middle (LongMemEval, Lost in the Middle).

## What changed (only what is TOLD, never what is KEPT or accepted)

- **Under the limit, nothing is different.** Every accepted fact, in the same order, no embedding asked for. This is the case today.
- **Over it, the model is told two groups**, together never more than the same 2,000 characters:
  1. **The lasting facts about who the person is** (a name, a place, an allergy, a job, family; `diya_recall.is_core`, a short pattern in code), up to 45% of the room, told whatever the question.
  2. **The rest, ranked by closeness to what the person just said** (their last two messages, at most 400 characters), using `nomic-embed-text`, the model Diya already uses for notes. A fact that shares a word
     with the question gets a small extra push. Filled in, best first, until the room is used.
- **What may be kept is larger than what is told.** With recall on, up to `DIYA_MEMORY_STORE_CHARS` (default 20,000) characters of facts may be accepted; with `DIYA_RECALL=0` the old limit applies and a full
  memory refuses new facts as before. The Memory page says "N of M characters used" and, once more is kept than told, how much the model is told per message.
- **It cannot fail a chat.** If the embeddings cannot be had (Ollama down, the model missing) the model is told the lasting facts and then the newest ones.
- **Embeddings are kept** in `fact_embeddings` (one row per fact and embedding model, with the fact's `text_key`): made the first time they are needed, again only for a fact whose words changed. Nothing is
  sent anywhere; a row can always be made again from the fact. No model writes anything here: ranking is arithmetic over vectors.

## Measured (real `nomic-embed-text`, invented memory of 68 facts, 2,816 characters; questions I wrote while looking at the facts)

| Room per message | Needed fact told, with recall | Needed fact told, newest facts only (the fallback) |
|---|---|---|
| 2,000 characters (71% of the facts fit) | 12 of 12 | 10 of 12 |
| 800 characters | 12 of 12 | 3 of 12 |
| 500 characters | 12 of 12 | 1 of 12 |

Cost: the first question after a restart embeds the facts that have no stored vector (about 3-5 seconds for 68 on this computer); every later question costs one embedding (about 0.1 s).

**Not measured, so not claimed:** the questions were written with the facts in front of me, so they are friendlier than real ones; "was the model's *answer* better" was not tested (recall only decides what it
is shown); facts that mean the same in different words ("my sister's job" versus "Maya works as an architect") worked here, but twelve questions is not a benchmark. The real test is the owner's own memory after
a few weeks, and the Memory page will show when more is kept than told.

## What it does not do

- It does not forget, merge or summarise facts: that is Dreaming and the review pipeline's job, unchanged. A fact still has to be reviewed or automatically accepted by the same rules.
- It does not change the notes search (`search_notes`) or the questions queue.
- It does not make a 20,000-character memory free: the Memory page, Dreaming and the review commands read the whole store.

## Turning it off

`DIYA_RECALL=0` restores the old behaviour: the old 2,000-character limit on what is kept, and every fact told. Facts kept above 2,000 characters while recall was on stay in the memory, and with recall
off the model is told all of them, however long: that is the long list recall exists to avoid, so turn it off only while the memory is still under the old limit.

## Tight mode (2026-10-27): the facts for THIS message, even when everything fits

Found when the owner asked for a joke and got a dog and a favourite colour: the 4B model was told every accepted fact on every message and kept wanting to use them. With recall on, a message is now told
only the always-on facts (`diya_recall.is_always`: a name, an allergy or condition, pronouns, a time zone; at most 25% of the room) and the facts whose meaning is close to the message
(`diya_recall.pick`: cosine at least `THRESHOLD` = 0.52, at most `TOP` = 6). Measured with nomic-embed-text on the 13 real accepted facts: facts that were for a message scored 0.52 to 0.68, facts that were
not scored up to 0.49; of 18 messages none brought in a fact it was not about. "What do you know about me?" is still told everything. The partial note stays. If the embedding model is slow or down (6 seconds,
`Agent.embed_in_time`), a fact that shares a meaningful word with the message is added instead.

The message is `Agent.with_profile(history, message=...)`: the web page and the phone add the new message to the history only after the profile is built, so they pass it. A history that already ends with
the person's message (the benches, an automation) needs no `message`. A history that ends with an answer (the terminal chat, set up once) has no message yet and is told everything.

Cost: the profile now changes with the topic, so the first turn after it changes re-reads the tools and the chat after it (measured 4 s for a one-message chat). Turn it off with `DIYA_RECALL=0`.
