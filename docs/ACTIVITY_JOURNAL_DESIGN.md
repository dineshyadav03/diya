# The activity journal: what Diya did, in a record she cannot edit (2026-10-18)

**Why.** The blueprint asks for an audit trail the owner can trust more than the model's own account of itself. Diya already logs connector calls to a text file and keeps each action's history in the approval system; nothing recorded the *tools* she ran for a message (searching the web, reading a note, reading mail, proposing a task), so "what did Diya just do?" had no honest answer.

**What is recorded** (`tool_journal`, migration 21; `diya_journal.py`): one row per tool call or flow, with the time, the tool, whether it was a **tool** or a **flow** (the code-decided paths: notes search, mail reading, repository study, web search), where it came from (**chat**, or **unattended**: a scheduled run with a restricted tool list), the chat and message ids, a digest of the arguments, a short preview of them, the outcome (**ok**, **error**, **refused**), how many characters came back, how long it took, and a note.

**What is not recorded.** The result itself (only its length), and any argument whose name looks secret (`token`, `password`, `secret`, `key`...), which is shown as `[hidden]`. The preview is one printable line with invisible and direction-changing characters made visible.

**Append-only, enforced by the database.** `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `the journal is append-only`, so neither Diya's code nor a bug can rewrite a row. (The owner can still delete the database file; this guards against mistakes, not against the owner.)

**Never breaks a chat.** `diya_journal.record` never raises: a journal that cannot be written must not stop an answer.

**Where to see it.** `GET /api/journal` returns the last 100 entries and the last day's counts; the **Activity** page (System → Activity) shows them in plain words, refreshed once a minute. It sits behind the same token as every other route.

**Proof.** `tests/test_journal.py` (append-only, secrets hidden, a refused call recorded, flows recorded, unattended origin, never raises), the route and page pins in `tests/test_token.py`, `tests/test_frontend_proxy.py` and `tests/test_actions_format.py`.

**Not done.** Journalling approvals and runs of actions (they already have their own history in `docs/ACTIONS_DESIGN.md`'s table); export; filtering by tool in the page; a retention rule.
