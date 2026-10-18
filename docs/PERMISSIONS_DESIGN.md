# What each connection can do, and what you are told before you approve (2026-10-18; DIYA-048 and DIYA-072)

**Why.** Trusting an assistant with accounts needs two answers that do not depend on the assistant: *what can each connection do?* and *what am I agreeing to, right now?* Both are built from facts in the code and the record, never from what a model says.

## On the Connections page, for every connection (DIYA-072)

- **What it can do**, in plain sentences the code declares next to the connector, and **what it cannot** ("Cannot send, draft, change, label or delete a message", "Cannot invite anyone", "Can see only the files Diya made herself"). A test fails if a connection says it can add something but has no approval-gated action behind it, or the reverse.
- **The permission it asks the service for**, exactly as the service names it (`calendar.readonly`, `gmail.readonly`, `calendar.events`, `tasks`, `drive.file`). A test fails if a broad permission (`mail.google.com`, the full `drive`) is ever asked for.
- **What the service said it granted.** When a Google sign-in finishes, Google's answer lists the permissions it actually granted; that is kept (`<name>.granted`, not a secret) and shown next to what was asked, and flagged if they differ. A sign-in from before this was kept says nothing rather than guessing.
- **Connected since**, from when the stored sign-in was written; **last used**, from the newest row of the activity journal for a tool that belongs to that connection, with whether it worked; and the **last approved action** run through it.
- `GET /api/permissions` is read-only, behind the token, and never contains a token or credential.

## On every waiting action, before you approve (DIYA-048)

Under the exact arguments, the card now says: **Risk level N of 4** and what that level means, **what it reaches** (the hosts), **how far it can be undone** ("by hand in Google Calendar: Diya cannot remove it"), and **which connection it uses**. These come from `diya_catalog.py`, the same source as `docs/AUTHORITY_MODEL.md`. The sentence you approve, the arguments and the hash it is bound to are unchanged.

## What is not shown, and why

- **Which Google account.** Diya does not keep the email of the account that signed in (that needs an extra `openid email` permission, DIYA-066). The card says which *connection* it uses; with one Google account that is unambiguous.
- **Recipient.** Nothing Diya can do reaches another person yet, so there is no recipient to show; when sending exists, the recipient will be part of what is approved.
- **Expiry of a Google sign-in.** A refresh token has no fixed expiry; an app left in Google's "testing" state has its sign-ins ended after 7 days, which is why `docs/GOOGLE_SETUP.md` says to publish the app. If a sign-in stops working the connection shows as not usable and Connect again is the way back.

**Proof.** `tests/test_permissions.py` (12 cases) and `tests/test_google_write.py::test_a_waiting_google_action_carries_its_risk_its_reach_and_how_far_it_can_be_undone`.
