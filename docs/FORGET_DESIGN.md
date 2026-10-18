# Forget for good: delete a message or a fact so its words are gone (2026-10-18; decision 234, DIYA-024 and DIYA-214)

**What the owner asked for.** "Keep everything by default, but also give a feature to delete or forget something." Until now "Forget" only *retired* a fact: its words stayed so that "Remember again" worked. That is the right default. This is the other thing: a way to delete for real.

## What you can do

| Where | Button | What happens |
|---|---|---|
| **Memory page**, on any fact (waiting, known, forgotten, rejected) | **Forget for good** | Asks first. Then the fact's words are taken out of Diya's memory. It cannot be undone. |
| **The chat**, under any of your messages | **Forget this** | Asks first, with the real numbers ("Diya will also forget the 1 thing she learned from it. A task made from it stays."). Then your message **and Diya's reply** are deleted, and the facts that were read from that message. |

## What "gone" means

**A fact forgotten for good** (`Memory.purge`): its text; the line it was extracted as; the links to the message and the person it came from; the words kept in its own history (the earlier wordings of an edit, the fact it replaced); its questions; the vector made from it; and its line in the staged-queue file Dreaming writes (`dream_pending.jsonl`) are all removed or replaced by "(forgotten for good)". What is left is that a fact with that number was here, what status it had, and when it was forgotten and by whom: no words. The memory's own integrity check still passes.

**A message forgotten** (`diya_forget.forget_message`): the message and the reply that followed it, their category, and the record that memory had read them. With "also learned" (the default on the page), the facts whose **recorded source is exactly that message** are forgotten for good too. A fact read from a wide batch with no recorded source is **not** guessed at: it is counted ("not sure") and kept. A task, a repeating reminder or an approved action that was *made* from the message is kept and unlinked, and the page says so, because deleting a message is not the same as cancelling what you asked for.

**Really gone from the file.** The deleted words are overwritten inside the database (`PRAGMA secure_delete`), not left in free space; a test reads the raw database file and finds no trace after a message and its facts are forgotten.

## What it cannot reach, and says so

- **Backups made earlier** (`backups/`) still hold the old words until they rotate out (the newest 14 are kept) or you delete them. The confirmation says this.
- **The activity record and Dreaming's receipts** are append-only by design. They hold counts, ids and short previews of what a *tool* was asked (never a reply), and a forgotten message leaves only a line "forgot N messages, M facts". They cannot be edited.
- **A cloud-sync folder's own history** (OneDrive's version history) is that program's, not Diya's.

## Rules it keeps

Only the person's own messages can be deleted (not Diya's alone); an unknown id is a 404; a fact already forgotten is refused; the model has **no tool** for any of this (`tests/test_catalog.py` and `tests/test_red_team.py` fail if a tool with delete, remove or similar in its name appears); a preview (`dry_run`) changes nothing; and the routes sit before the memory page's generic action route so they cannot be shadowed.

**Proof.** `tests/test_forget.py` (14 cases): every place the words lived, the file bytes, status coverage, questions, the staged file, preview, derived rows, only-that-message's-facts, the unsure case, what is kept and unlinked, role and id checks, the next exchange untouched, and the route order.

**Not done.** Saying it in chat ("delete that for good"); forgetting a whole chat or a date range at once; deleting from the activity record; shredding backups (a command for that is easy to add when wanted).
