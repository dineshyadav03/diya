# Memory as an Agent Memory Repo (2026-10-20)

Applied from the study of Devin's memory (`docs/STUDY_DEVIN.md`). `python diya_review.py export-repo FOLDER` writes what Diya remembers as a folder of Markdown notes in the shape of Cognition's open
**Agent Memory Repo** standard (https://cognition.com/agent-memory-repo, read 2026-10-20), the format Devin's own Memory is built on.

## The shape
```
FOLDER/
  MEMORY.md          the entry point: the lasting facts about you (up to 2,000 characters), then "## Index" with [[links]]
  about-you-more.md  only if the lasting facts do not all fit in MEMORY.md
  people/<name>.md   one note per named person
  passing.md         facts that sound like they will not last, each with the date it fades
  retired.md         facts Diya no longer uses
```
Every entry is one bullet on one line with its metadata at the end, as the standard says: `- Has a dog named Hog. [source: message 218; added: 2026-10-14; by: you]`. `source` is the number of your message it
was read from (as far as the record says), `typed` or `old profile`; `by` is `you`, `typed`, `auto` (Diya took it on her own under the memory rules) or `imported`; `said-again` and `fades` appear only when they apply.
Links are `[[people/mom]]`, starting at the root and without `.md`, and every link in the Index points at a file that exists (tested).

## What it is for
* Reading your memory in any editor, keeping it in Git (`git init` in the folder is your choice; **do not put it in a public repository**: it is everything Diya knows about you) and diffing it month to month.
* Showing it to another tool that understands the format, **on this computer**. Decision 232 (local only) still holds: Diya does not send it anywhere, and nothing in this work calls any other tool.

## What it is not
* **Not a second store.** Diya's database is the only truth; the folder is written once and never read back (the one-file copy in `docs/MARKDOWN_MEMORY_DESIGN.md` is the one that restores). Editing a note changes nothing in Diya;
  change a fact on the Memory page.
* **Not complete.** Facts still waiting for a decision, facts you turned down and facts forgotten for good are not in it.
* **Not Devin's Dreaming.** Devin's agent edits the notes by itself (merges, removes, resolves contradictions). Diya's Dreaming only stages candidates and a person or the written rules decide; see `docs/STUDY_DEVIN.md`.

## Safety
A person's name becomes a file name only as lowercase letters, digits and hyphens (`../../Evil Name` is `evil-name`; a name with no plain letters is `person`; two names that would collide get `-2`), a fact's
`[[` and `]]` are spaced apart so it can never create or break a link, the folder must not exist or be empty (nothing is ever overwritten), and files use LF line endings.

## Proved (tests/test_memory_repo.py, 12)
The shape and the Index; every entry's format; the metadata; passing states with their dates; what is left out; the size limit and the overflow note; names, links and collisions; nothing changed in the database and
nothing overwritten; an empty memory; the command line. **Not proved:** that another tool reads the folder: the standard is a convention, and no other tool was run against it.
