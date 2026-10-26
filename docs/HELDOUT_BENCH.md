# Where does Diya really stand? A held-out benchmark and a speed benchmark (2026-10-26; DIYA-191, DIYA-194)

Hamel Husain's post of 2026-10-26 says public benchmarks are often poor, that the way to know is to **run one and read the cases it marked wrong**, and points to Epoch AI's benchmark hub, which does that
for the big ones (it reports contamination, large score changes from small changes of settings, strict graders that give some models below-chance scores, and developers' own scores that its runs did not
reproduce). The same questions apply to Diya's own benchmarks, and the honest answer is: they are good at what they were built for, and weak on exactly the thing the post is about.

## What the existing benchmarks are, said plainly

- They are **written by the person who wrote the guard they measure**, and several guards were built after looking at the model's mistakes on those same messages (`tests/labelled_repeats.py` says so at its top).
  So a high number says "the guard and the model handle THESE phrasings", not "Diya handles what a person types".
- They are **small** (9 evals; 82 task messages; 80 memory messages; 45 repeat messages), graded by **words that must or must not appear**, so a good answer in other words fails and a lucky one passes.
- They are checked by **code that does not move** (the guards), which is why the "must be zero" safety lines are meaningful even at a small size: a secret kept, an order accepted as a fact, an unasked reminder saved.
  Those do not depend on how the model is feeling today.

## The two new ones

**`python diya_heldout_bench.py`** (45 messages, `tests/labelled_heldout.py`): messages written in one sitting in the way a student types on a phone (no capitals, shorthand, two things at once, and the
tricky ones: "remind me what i wrote about the vet", which is **not** a reminder; a plain statement that must not become a task), before being run against any model, and never tuned on. The same prompts, tools,
fixture notes, temperature 0 and seed for every model (`--model a,b` compares). Routing (right tool or none, none forbidden, the words that must be in the call) and answer (words, length) are counted apart.
The report ends with every failure in full so it can be read. **Rules:** never change a guard, a prompt or a tool because of how one of these did; if the fix is worth making, move that case to the
development sets and write a new one; if a label was wrong, fix the label and say so below. `tests/test_heldout_bench.py` checks that no message repeats one in another labelled set (it caught three on the
day it was written, which were replaced before any model saw them).

**`python diya_latency_bench.py`**: first word, whole answer and tokens a second for four fixed prompts, several trials, quiet or with half of the processor's cores kept busy (`--load`), and a cold start
(`--cold`). It reports the half-way time and the slow end, and says that the slow end of a few trials is only the slowest one or next to it.

## What neither shows

- A real person's messages. The best held-out set is the owner's own messages after the owner has labelled what each should have done; that file would hold private words, so it must live outside the
  repository (it is not built). Until then, the held-out set is a better guess, not the truth.
- Quality of the model's writing, or whether an answer is true (the weather cases are graded on the call alone). The memory benchmarks cover facts.
- Anything about a different computer: the speed numbers are for this laptop, today, with the memory that was free.

## What the first runs found (2026-10-26, model `diya-chat`)

45 messages, temperature 0, seed 7. First run: **35 of 45** passed, routing right on **43 of 45**. Two real faults were found and fixed (tests in `tests/test_found_by_the_heldout_bench.py`): the mail check mistaking a to-do item with the word "email"
for a look through the mailbox, and phone-style statements not being read as statements. The three cases that led to those fixes (ho-11, ho-15, ho-37) were **moved to the development tests** and three new ones written (ho-46, ho-47, ho-48). Second run: **37 of 45**, routing **44 of 45**.
The new cases did what a held-out set is for: ho-46 and ho-48 (the same kinds of fault, new wording) now pass, ho-47 ("also my roommate moved out...") still fails, as an unseen phrasing should.

## Label corrections found by reading failures

Made after the second run, said here so the number can be trusted: the same saved answers score **40 of 45** with them and 37 of 45 without.
- **ho-34, ho-40, ho-41** (the meeting that makes me late for dinner, "i need to finish chapter 5 before friday", "ugh i still have to clean my room") asked for a one-sentence reply (`max_words: 30`). They are plans and needs, not plain facts, and Diya's design gives those a normal reply (a need
  is a request). What must hold is that nothing unasked is saved, which the `forbidden_tools` line still checks. The length limit was the wrong label, and is removed.
- **ho-33** ("got a doctor visit on wednesday morning") expected no tool at all; the model looked at the calendar, which is read-only and does no harm. The case now allows that one tool (`allowed_tools`); its length limit stays and it still fails on length (107 words).
- **Not changed, the model was wrong:** ho-25 (it asked for a folder called `notes` that does not exist), ho-13 and ho-16 (plain statements answered with paragraphs), ho-47 (a statement, answered with a paragraph), ho-33's length.

## The fix round (2026-10-26, later the same day) and what it showed

The failures above were fixed in code (tests in `tests/test_fixes_from_the_benchmarks.py`), and the four cases that led to the fixes (ho-13, ho-16, ho-25, ho-47) were **moved to the development tests** and four new ones written before the fixes
were run (ho-49 to ho-52). Third run: **41 of 45**, routing **45 of 45**. The new cases did what a held-out set is for, and not all of them passed:
- ho-51 ("i prefer studying in the library after 6pm") passed: the new statement words work on an unseen sentence.
- **ho-52** ("whats in my notes directory": the folder is not there) failed again: the first fix told the model to look in `.`, and it answered "there is no folder, only files". So the fix was too narrow and was redone: the reply
  now says there is no such folder **and lists what the main folder holds** (files, folders marked with `/`, nothing secret-shaped, never a path on this computer). ho-52 moved to the development tests and **ho-53** ("show me whats inside my documents folder") was written first.
  Fourth run: ho-53 passed. **42 of 45**, routing **45 of 45**.
- **ho-49** ("i dropped my maths elective this term") and **ho-50** ("my flatmate took a night job at the hospital last month") **still fail**: plain statements with verbs the statement words do not include ("dropped", "took a job"), answered with a paragraph
  (41 and 40 words, over the 30). Nothing is saved and no tool is called, so nothing unsafe happens; only the reply is longer than it should be. **Left open on purpose:** every unseen phrasing needs one more word, which is the limit of a word list, and adding
  words until these two pass would turn them into development cases again. A model that decides "is this a statement?" was measured (docs/BENCHMARK_2026-10-26.md, the gate benchmark) and was worse than the code on the cases it was built for (42 of 47 against 47 of 47), so the honest
  position is: the code is right on what it knows, and the next unseen verb will be a miss.
- **ho-33** ("got a doctor visit on wednesday morning") still fails on length only (107 words after a read-only calendar look, which is allowed).

Score history on this set, which changes as cases are replaced (so the numbers are not strictly comparable): 35 → 37 → 40 (labels corrected) → 41 → **42 of 45**. Case set hash `f0d54c21f3f0`.
