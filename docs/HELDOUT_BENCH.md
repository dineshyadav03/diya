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
