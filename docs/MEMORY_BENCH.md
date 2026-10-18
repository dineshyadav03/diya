# How good is Diya's memory? A question-and-answer measurement (2026-10-16)

**Why this exists.** The owner asked for memory as good as supermemory's, and supermemory's claim is a score on published long-term-memory benchmarks (LongMemEval, LoCoMo, ConvoMem). Diya had no such score: its earlier measurements (`docs/AUTO_MEMORY_DESIGN.md`) say what the memory *stores*, not whether it *answers correctly later*. This is that, at Diya's scale, so that improving the memory is something measured and not guessed.

**What it does** (`diya_memory_qa_bench.py`, cases in `tests/labelled_memory_qa.py`): for each of 30 cases, on a throwaway database, the person TELLS Diya things in order (each read the way the chat reads a message the moment it is said, then Dreaming's scheduled pass, with the privacy judges and the lanes, using the real local models), then ASKS one question to the real agent with the memory in its prompt. The answer is graded by the words it must contain (every group) and must not contain; the memory itself is checked for what it must not hold (an old fact that should have been replaced, a secret). Eight kinds: recall, update, addition, person, noise, abstain, privacy, similar.

```bash
python diya_memory_qa_bench.py --model diya-chat        # all 30, about 15 minutes on this laptop
python diya_memory_qa_bench.py --kinds update,addition  # some kinds
```

**What it is not.** Written by the author, in the manner of those benchmarks and at a hundredth of their size: it says how Diya does on these phrasings, not on the owner's own words, and **not how it compares with supermemory's published numbers**, which were measured on different, far larger tests with a hosted engine. A score here is for tracking Diya against itself.

## Results (model `diya-chat`, second privacy judge `qwen2.5:3b`, the owner's real setting)

| Kind | First run | After the update fixes |
|---|---|---|
| recall (one thing said once) | 10 / 10 | 10 / 10 |
| noise (the fact survives a lot of small talk) | 2 / 2 | 2 / 2 |
| person (a fact about someone else) | 3 / 3 | 3 / 3 |
| privacy (a secret or medicine is neither kept nor said back) | 3 / 3 | 3 / 3 |
| abstain (never told: says it does not know) | 3 / 3 | 3 / 3 |
| similar (look-alike facts, the question picks one) | 3 / 3 | 3 / 3 |
| addition ("another dog", "I also play...") | 1 / 2 | **2 / 2** |
| update ("I started a new job at a bank") | 1 / 4 | **2 / 4** |
| **All** | **26 / 30 (86%)** | **28 / 30 (93%)** |

## What the first run showed, and what was changed

All four failures had **one cause**, found by printing why the new fact was left waiting (its flags): the memory had **noticed** the change and then **waited for the person to answer a question card** while the old fact kept being told to the model. "You work at a bakery" was still the answer after the person said they had started at a bank. Safe, and stale.

- **"started a new job", "just bought an iPhone" were not on the list of words that mean "I am changing something I told you"** (`diya_intent._CORRECTION`). They are now (new job/role/phone/laptop/car, "just bought/started/moved/switched/joined/upgraded", "started working/studying", "replaced", "upgraded"). A word alone replaces nothing: the model must also name which known fact it replaces, and the replacement is shown with Undo.
- **A second dog was held up for looking like the first** ("has a dog named Hog" resembles "dog named Rocky", and the `similar` check, which is about copies, asked). The person's own words, "another dog", say it adds; `diya_autonomy.apply(adds=...)` now lets such a fact past the *similar* check (not past a privacy or any other check).
- **Safety did not move.** The earlier safety measurement (`diya_autonomy_bench.py`, 80 messages in 8 days, read live, `diya-chat` with `qwen2.5:3b` judging privacy) was run again and is **CLEAN**: secret kept 0, order accepted 0, the assistant's own words accepted 0, sensitive accepted 0, known fact wrongly replaced 0. Updates in that bench: asked 1, replaced 2, one wrong fact extracted ("using a Mac" from "I'm using a Mac now, my laptop is a MacBook Air": a poor extraction, not a wrong replacement).

## Round 3 (2026-10-18): the Hog regression, the capture queue and 33 cases

The owner's "I got another dog named Hog" was the first real failure. Writing it as a permanent test (`tests/test_hog_regression.py`) found two more bugs, both fixed (`docs/MEMORY_DURABILITY_DESIGN.md`): **a correction with a pronoun ("Actually his name is Hogg, not Hog") was never read**, and a correction that looks like the fact it corrects was **held for a question** by the copy check. Three correction cases were added to the bench (30 to 33) and the run repeated with the real models:

| Kind | Round 3 |
|---|---|
| recall | 10 / 10 |
| update (now including pronoun corrections) | 7 / 7 |
| addition | 2 / 2 |
| person, noise, privacy | 3 / 3, 2 / 2, 3 / 3 |
| abstain | 3 / 3 |
| similar | 2 / 3 |
| **All** | **32 / 33 (96%)** |

**The safety measurement was repeated after the correction path was loosened** (`diya_autonomy_bench.py`, 80 messages in 8 days, read live, `diya-chat` with `qwen2.5:3b` judging privacy): **CLEAN**. Secret kept 0, order accepted 0, the assistant's own words accepted 0, sensitive accepted 0, code-sensitive accepted 0, **known fact wrongly replaced 0**. Plain facts 21 of 24 remembered (88%), 18 of 18 sensitive asked, 10 of 10 secrets discarded, 13 of 13 small talk ignored. Updates: asked 1, replaced 2, one wrong *extraction* ("The user no longer lives in Delhi" for "I moved to Pune last month, so I no longer live in Delhi": a negation kept instead of the new fact; not a wrong replacement).

The one miss ("When is my maths exam?" with a guitar exam on Friday and a maths exam on Tuesday in memory) is **the model, not the memory**: memory held both facts correctly, and `diya-chat` answered "Friday" by mixing the two. It is a look-alike-fact reading error that a bigger model would probably not make; it is not a staleness or storage defect. The two update failures listed below (grounding of "I just bought an iPhone", the negation-only extraction) passed in this run; I did not investigate why, and one run of a small model is not evidence that they are fixed, so they stay listed as open.

## What still fails (and why)

- **"I just bought an iPhone" after "my phone is an old Android".** The extractor wrote "Owns an iPhone", a rewording the grounding check could not tie to the message (`ungrounded`), so it was asked instead of replaced. The fix is in the grounding check or the extraction wording, not in the update rule; not done.
- **"Actually I switched to tea, I stopped drinking coffee"** (marked `gap?`). The extractor kept only the negative ("stopped drinking coffee"), which looks like a copy of "drinks coffee" (`similar`) and so is asked. A negation is not a replacement in the policy's eyes. Not done.

## What this says about "do we need supermemory for memory?"

On these 30 cases Diya's memory is **right 28 times in 30** with a 4B model running on this laptop, and perfect on recall, secrets, other people, small talk and "I don't know"; the weak spot was staleness, now much reduced. That is not a claim of parity with a hosted engine on a large benchmark. What a hosted engine has that Diya does not is **scale** (millions of facts, graph-wide retrieval), **extraction by a bigger model** and **connectors and file ingestion**; none of those is a memory-quality problem at the size of one person's life, which is where Diya works. The honest gaps are in `docs/STUDY_SUPERMEMORY.md`: Gmail and Drive, files, and the stable-versus-recent split.

## Next measurements, if wanted

- The two failures above (grounding, negation).
- Time: a fact whose day has passed ("exam next Tuesday") asked about after the day, with a fake clock.
- More cases written from the owner's own phrasing, once there are more of them.
- The same 30 cases on `qwen2.5:3b` and on newer models, once the owner agrees to download them.
