# Playbooks: how you want a kind of request done, written once (2026-10-20)

Applied from the study of Devin's Skills (`docs/STUDY_DEVIN.md`). Devin keeps two kinds of memory apart: what it **learns** about you (Memory, refined by itself) and **procedures people write on purpose** (Skills: a
`SKILL.md` with a name, a description of when it applies, and the steps). Diya had the first. `docs/MEMORY_TAXONOMY.md` listed "skills / procedures: not built". This is the second kind, in the same open
layout (Agent Skills), so a file can be read by a person, by Devin's tooling and by Diya.

## A playbook
A folder with a `SKILL.md` in the playbooks folder (`playbooks/` beside the code, or `DIYA_PLAYBOOKS_DIR`; `sample_playbooks/` holds three invented examples to copy):

```
playbooks/study-plan/SKILL.md
---
name: study-plan
description: Use when I ask for a study plan, a revision schedule, or how to prepare for an exam or a test
triggers: [user, model]
argument-hint: the subject and the exam date
---
1. If I have not said which exam and when it is, ask me that first and nothing else.
2. Count the days left. Split them into blocks of 25 minutes with a 5 minute break after each.
...
```
* `name`: lowercase letters, digits, hyphens (the folder's name if left out). `description`: 10 to 300 characters, what it is for. `triggers`: `user` (you write `@study-plan`), `model` (a request close in meaning to
  the description starts it), or both (the default). `argument-hint` is shown on the page. `$ARGUMENTS` and `$1` to `$9` in the steps are filled from what you wrote after the name; if the steps use none, what you
  wrote is added once after them as "The user's request, for these steps".
* The steps are at most 1,500 characters, the file 8,000 bytes, and there can be 30 playbooks. A file that is wrong (no `---` block, a bad name, steps too long, a control character, a name used twice) is **not
  used**, and the Playbooks page and `python diya_playbooks.py list` say which file and why. `python diya_playbooks.py check FILE` tests one before you save it.

## When one is used
1. If the message names one (`@name`, not inside an address like `ana@study-plan.com`, and only if its triggers include `user`): that one. The first mention wins.
2. Otherwise, only among playbooks whose triggers include `model`: the request must share at least one meaningful word with what the playbook is for, be at least **0.56** close in meaning to it (embedding), and
   beat the next playbook by **0.03**. Otherwise none.
3. One at a time, never for an unattended run (an automation runs no playbook, as Devin's automated sessions neither read nor write memory), never when `DIYA_PLAYBOOKS=0`, and if anything fails the chat goes on
   without it. The use is journalled as the flow `use_playbook` with its name and whether it was named or matched, never the steps.

## What a playbook cannot do (in code, not by asking the model nicely)
* **It grants nothing.** It cannot add a tool, widen an action or skip an approval. `allowed-tools` in a file is ignored (a test proves the tools offered to the model are identical with and without a playbook).
  The note the model gets says so too, but the guarantee is that the tool list and the approval gate are code.
* **Only you write them.** Diya never writes, edits or saves a playbook, and nothing from the web, mail, a note or a model becomes one. (Devin *suggests* a skill and shows a Create PR button; Diya does not
  even suggest: you would be approving text written by a 4B model into your own instructions.)
* **The page shows what is active.** Playbooks page: each one, what it is for, how it starts, its steps, and the files not used.
* A file reached through a link that leaves the folder is not followed.

## What was measured (2026-10-20, real embedding and chat models)
Picking by meaning, on 24 invented requests (`tests/labelled_playbooks.py`) against the three samples: **8 of the 10 requests that should pick a playbook picked the right one; 0 of the 14 that should pick none
picked anything** (near misses included: "plan my day tomorrow", "how did my week go?", "write an email to my professor"). The two misses ("make a timetable to revise for statistics", "summarise this: ...")
fall back to typing `@name`, which always works. The threshold came from comparing five ways of embedding the descriptions; the one used (the description without its "Use when I ask for") gave 9 of 10 with no
false pick before the shared-word guard and 8 of 10 with it: the guard was kept because a false pick starts a procedure nobody asked for.
Following, with the chat model `diya-chat`: `@summarise-notes <paragraph>` produced five bullets of under 15 words and a "Not covered:" line exactly as the playbook says; `@study-plan chemistry exam on Friday,
I have 4 days` followed the steps loosely (it restated them as a list before planning). A 4B model follows a procedure approximately; it is not a script runner.

## Not done
* Chaining (a playbook calling another), `allowed-tools`, shell blocks inside a file, plugin scopes: not supported, on purpose.
* Writing or editing a playbook from the page. A file in an editor is the whole interface for now; the page is read-only.
* No measurement on the owner's own requests: the folder starts empty.
