# Memory as a Markdown copy (2026-10-18, task DIYA-033)

**The question in the task sheet:** can memory be exported as Markdown, without replacing SQLite as the truth, with a round trip that keeps references and authority?
**Answer: yes, built.** `python diya_review.py export-markdown [PATH]` writes the copy; `python diya_review.py restore-markdown PATH` brings back what it holds and memory does not.

## Why
Devin's memory (read about secondhand today, `docs/RESEARCH_REVIEWS_2026-10-18.md`) is Markdown notes in a Git repository with an index and a link from each note to where it was learned, and supermemory's
open `company-brain` has a Markdown export of its memories (`src/memory/markdown.ts`, Apache-2.0, read). For the owner it means three things the database alone does not give: memory they can *read* in any
editor, memory they can keep in Git and *diff* month to month, and a second copy that does not need Diya's code to be understood.

## What the file is
Plain Markdown: a heading per person ("About you", "About Mom"), a bullet per fact, and a section for facts Diya has stopped using. After each bullet, a hidden comment (`<!-- diya {...} -->`, invisible when the
file is rendered) holds the record: who it is about, the date it was first taken in, who took it in (**typed** by you, **you** accepted it, **auto** = Diya under the rules, **imported**), the number of the
message it was read from, how many times you said it again, and whether you kept it. The first line says the format and the date. `<` and `>` are escaped inside the record so that nothing, including a
name or a fact that contains `-->`, can close the comment early.

**Not in the file, on purpose:** facts still waiting for a decision (nobody has said they are true), facts you turned down (you said no, and a file is the wrong place to keep that), facts forgotten for good
(their words are gone), and the messages themselves.

## What a restore does and does not do
* Adds only what is not already there. A fact is skipped if an accepted, retired or turned-down fact already has the same words: **a decision made in this database is not undone by a file.** Run it twice and the
  second run changes nothing.
* **Authority is recorded, never forged.** Each restored fact has an `imported` event by the importer whose detail says "from a Markdown export, originally taken in by <typed / you / auto / imported>". It never
  looks as if the owner accepted something on a day they did not, and "How do you know that?" says "restored from a Markdown copy" and quotes no message.
* **References are kept as numbers, not links.** The message a fact was read from is in the trail and not in the fact's flags, because in another database that number is a different message and quoting it would
  be a lie.
* Dates: the date first taken in is kept (a date in the future is not believed). A passing state ("for now") starts its fading clock from the day it was restored, so a restore does not retire it on the first
  Dreaming pass. A fact you had *kept* stays kept. How many times it was said again is kept as a number in the trail; the individual repeats are not recreated.
* A file that is not an export is refused whole. A damaged line is reported ("line 14: ...") and skipped; nothing is guessed. More than 5,000 facts is refused as "not a memory".
* The command line never overwrites a file without `--force`; the file uses LF line endings.

## What was proved (tests/test_markdown.py, 24)
Grouping and what is left out; export changes nothing; the round trip (words, people, statuses, first-taken-in dates, kept marks, an intact trail); authority and references as above; idempotence; existing
decisions are not undone; kept facts do not fade and restored passing facts get a fresh clock; non-exports and damaged lines; future/garbled/zoneless dates; fact text that looks like the format; the size cap;
the command line.

## What was not done
* No Memory-page button or API route to download the copy. The command line is enough for a monthly check and keeps the route list (and its token tests) unchanged; add one if the owner wants it.
* No Git integration: keeping the file in a repository is the owner's choice. **Do not put it in a public repository:** it holds everything Diya knows about the owner.
* The Markdown copy is not read by Diya as memory, and nothing in it is ever treated as an instruction.
