# Devin's memory and skills, studied with REA's method (2026-10-20)

**Target:** Devin (Cognition), a closed, hosted coding agent. **Method:** REA's, applied by hand (`docs/STUDY_REA.md`): every statement is **observed** (read from a named page today), **inferred** (a guess, with its
basis) or **not established**. Nothing of Devin was run or installed (there is nothing to run: it is a hosted product).
**Sources read today:** https://cognition.com/agent-memory-repo (the open standard), https://docs.devin.ai/product-guides/memory and https://docs.devin.ai/product-guides/skills (Cognition's own pages), and a
third-party write-up (memorylake.ai, which promotes its own product). The pages were fetched through a tool that summarises with a small model, so a detail may be worded differently from the page; where a detail
matters it is marked. Earlier notes: `RESEARCH.md` entries 21 and 26.

## 1. Memory (observed, docs.devin.ai/product-guides/memory)
* Notes are **Markdown files in a Git repository** (the "memory drive"); a top-level `MEMORY.md` holds general preferences and indexes the rest; each session gets its own checkout and reads `MEMORY.md` first.
* **Saved:** preferences, corrections with the rule to follow, decisions and their reasons, gotchas about repos and environments. **Excluded:** session summaries, task state (PR numbers, statuses), things cheap to
  rediscover, secrets and credentials. **Automation-started sessions neither read nor write memory.** New memories affect later sessions, not the one that made them.
* **Dreaming:** a background session about once a day while you are active: merges overlapping notes, removes transient details and stale notes **no session used**, adds missed lessons, reorganises the index;
  keeps source links and explicit preferences; the first dream seeds memory from recent sessions.
* **Control:** you browse it (with the dreaming history) but files are **read-only in the app**; to change or delete a memory you ask Devin in a session. You can switch personal memory off (notes are kept).
  Memory is personal to you within an organisation and is not shared with teammates.
* **Memory vs Skills:** memory is learned automatically and personal; skills are deliberate, repeatable procedures people write; "skills supply the procedure and memory supplies the context".

## 2. Skills (observed, docs.devin.ai/product-guides/skills)
* A skill is a `SKILL.md` file (the open **Agent Skills** layout): a `---` block with `name`, `description` (what it is for, shown in the list), `allowed-tools`, `argument-hint`, `triggers` (default user and model;
  `["user"]` stops automatic use), then the steps. Found in `.agents/skills/<name>/` (and several other folders).
* **Chosen** by the model from the list of names and descriptions, or by `@skills:name` with arguments (`$ARGUMENTS`, `$1`..`$9`). **Only one skill is active at a time**; no chaining. Scopes: repository, or plugins
  at personal / organisation / enterprise level. Devin may **suggest** creating or updating a skill, showing the proposed file and a "Create PR" button.
* **Not established** (the page does not say): how `allowed-tools` is enforced; how the shell-command blocks a skill may hold are run and with what rights; size limits; precedence between two skills of one name.
* Playbooks (managed in the web app, attached by hand) are mentioned; **Knowledge is not mentioned on either page, so nothing is known here about it** (a third-party write-up says Knowledge is being migrated to skills; that
  is unverified).

## 3. The Agent Memory Repo standard (observed, cognition.com/agent-memory-repo)
`MEMORY.md` at the root is loaded at the start of every session ("keep it short: include only what every session needs, plus links to everything else"), with an optional `## Index` of `[[links]]`; each entry is one
bullet on one line with optional metadata at the end as `[key: value; key: value]` (recommended `source`, a link to the session it was learned in, and `added`, `YYYY-MM-DD`); links are `[[path]]` from the root without
`.md`; several repos can be loaded at once and each memory is written to the repo of the person it belongs to; a Dreaming agent merges duplicates, removes outdated entries and checks sources to resolve contradictions;
git rejects a second push to the same line. **Not specified:** a formal schema, the format of the `source` link, access control, encryption, how the agent decides what is worth saving, deletion policy.

## 4. Against Diya
| Devin | Diya | Taken? |
|---|---|---|
| Memory as a Git folder of Markdown with a short `MEMORY.md`, one bullet per entry, `[source; added]`, `[[links]]` | One SQLite database; a flat export only until today | **Built:** `python diya_review.py export-repo FOLDER` writes exactly that shape (`docs/MEMORY_REPO_DESIGN.md`); the database stays the truth |
| Skills: `SKILL.md`, description, triggers, `@name`, arguments, one at a time | "Skills / procedures: not built" (`docs/MEMORY_TAXONOMY.md`) | **Built as Playbooks** in the same layout, with the guarantee that a playbook grants no tool and skips no approval (`docs/PLAYBOOKS_DESIGN.md`) |
| Skills are written by people; Devin only *suggests* one | Diya does not even suggest: a suggested playbook would be text written by a 4B model entering your own instructions | **Deliberately not taken** |
| Saved: preferences, corrections, decisions. Excluded: task state, cheap-to-rediscover, secrets | Facts about the person only; requests, reminders and tasks are never read as facts (`diya_intent.is_worth_capturing`); secrets are never kept; what a tool owns (reminders, tasks) is read from the tool | Already the rule; no change |
| Dreaming edits the notes by itself (merge, remove, resolve contradictions) | Dreaming only **stages**; the written rules and the person decide; a possible replacement is asked about, never applied silently | **Deliberately not taken** (a "compaction-driven write" is the poisoning risk of `RESEARCH.md` entry 17). A merge *proposal* the owner approves is the safe form: **not built yet** |
| Removes notes "no session used" | Every accepted fact is in every prompt while memory fits, so there is no "used" signal; passing states fade by rule (`docs/FADING_DESIGN.md`) | Partly: fading is the time-based half |
| Automation sessions neither read nor write memory | An automation is read-only and can write nothing, but **it is given the profile** (`Agent.briefing`) | **A difference worth deciding.** Today an automation's answer can mention what Diya knows about you; Devin forbids that. Not changed without the owner's say |
| New memories apply to later sessions only | The opposite on purpose: a fact told now reaches the model on the next turn (the "Hog" regression, `tests/test_hog_regression.py`) | Not taken |
| Files read-only in the app; ask Devin to change one | The Memory page edits, retires and forgets directly | Not taken: direct control is Diya's point |
| Several repos, one per person, memory written to the owner's | One person; a fact can be tagged to a named person (`docs/PERSON_MEMORY_DESIGN.md`) | The per-person note files in the export are the same idea, read-only |

## 5. What was not done
* No Devin account, so nothing about how Dreaming or skills *behave* was observed; only what the pages say.
* The Cognition pages could not be opened directly here; the summaries come from a fetch tool, and the third-party write-up is a promotional page.
* No other tool was run against the exported folder or the playbook files: that they follow the same conventions is a claim from reading the specs, not a test.
