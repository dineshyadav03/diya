# The activity journal: what Diya did, in a record she cannot edit (2026-10-18)

**Why.** The blueprint asks for an audit trail the owner can trust more than the model's own account of itself. Diya already logs connector calls to a text file and keeps each action's history in the approval system; nothing recorded the *tools* she ran for a message (searching the web, reading a note, reading mail, proposing a task), so "what did Diya just do?" had no honest answer.

**What is recorded** (`tool_journal`, migration 21; `diya_journal.py`): one row per tool call or flow, with the time, the tool, whether it was a **tool** or a **flow** (the code-decided paths: notes search, mail reading, repository study, web search), where it came from (**chat**, or **unattended**: a scheduled run with a restricted tool list), the chat and message ids, a digest of the arguments, a short preview of them, the outcome (**ok**, **error**, **refused**), how many characters came back, how long it took, and a note.

**What is not recorded.** The result itself (only its length), and any argument whose name looks secret (`token`, `password`, `secret`, `key`...), which is shown as `[hidden]`. The preview is one printable line with invisible and direction-changing characters made visible.

**Append-only, enforced by the database.** `BEFORE UPDATE` and `BEFORE DELETE` triggers raise `the journal is append-only`, so neither Diya's code nor a bug can rewrite a row. (The owner can still delete the database file; this guards against mistakes, not against the owner.)

**Never breaks a chat.** `diya_journal.record` never raises: a journal that cannot be written must not stop an answer.

**Where to see it.** `GET /api/journal` returns the last 100 entries and the last day's counts; the **Activity** page (System → Activity) shows them in plain words, refreshed once a minute. It sits behind the same token as every other route.

**Proof.** `tests/test_journal.py` (append-only, secrets hidden, a refused call recorded, flows recorded, unattended origin, never raises), the route and page pins in `tests/test_token.py`, `tests/test_frontend_proxy.py` and `tests/test_actions_format.py`.

**Not done.** Journalling approvals and runs of actions (they already have their own history in `docs/ACTIONS_DESIGN.md`'s table); export; filtering by tool in the page; a retention rule.

## Approved actions are in the record too (2026-10-26, DIYA-056)

Running an approved action now writes one line here, named `approved:<kind>`: how it came out (ok; error for a failure or an outcome that is not known; refused for one that could not even start), which chat and message it came from, and how long it took. As for every tool, only the length of the result is kept, never its words, and arguments named like a secret are hidden. The Activity page says it as "carried out what you approved", and the Status page's "Tools and accounts" counts a failed one among the last day's failures. The Actions page still holds the full receipt. `tests/test_actions_journal.py`.

## Saying less, and forgetting (2026-10-26, DIYA-215)

The record kept a short preview of what each tool was asked ("query=garden") for ever, and 'Forget for good' said it could not reach it. Three changes, all tested in `tests/test_journal_privacy.py`:

- **Hidden wherever it is.** A value that looks like a credential (an API key, a Google token, a login token, a long run of letters and digits), an email address, or a card-like or phone-like number is hidden in a preview and in a note whatever the argument is called, not only when its name says "token" or "password".
- **Previews off** (`DIYA_JOURNAL_PREVIEWS=0`): nothing that says what a tool was asked is kept: only that it happened, when, which tool, how it came out, how long the result was and how long it took, and the digest (two equal calls look equal).
- **Forgetting.** 'Forget for good' blanks the preview and the note of the rows that came from the forgotten messages, in the same transaction that deletes the messages, and nothing else; the rows stay (that it happened, when, how it came out). `DIYA_JOURNAL_KEEP_DAYS=N`
  removes the rows older than N days when the API starts (0, the default: all are kept, which is the owner's standing decision). Each of these writes a **receipt** (`journal_receipts`: when, whether blanked or pruned, how many; counts only, never words), and the receipts themselves can never be changed or deleted.

How "append-only" still holds: migration 29 turns the two triggers that refuse an UPDATE or a DELETE of the record into triggers that refuse **unless** one named switch (`journal_edit_allowed` in `app_state`) is set inside the same transaction. Only the two functions that blank and remove set it, and they clear it before they commit; a failure rolls the
transaction back, switch included (tested). A program that opens the database file and sets the switch itself could change the record, as it could always have dropped the triggers: the guarantee is that the application cannot do it by accident or by a bug, and that every deliberate change leaves a receipt.
