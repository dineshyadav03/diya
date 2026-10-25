# Taking your data out (DIYA-214; written 2026-10-25)

Your data is yours, so you can have all of it as plain files, whenever you like, without asking Diya or anyone:

```bash
python diya_export.py
```

It makes a new folder, `exports/diya-export-DATE-TIME/`, in Diya's data folder (or the folder you name with `--out FOLDER`), and tells you what is in it.

## What you get

| File | What it is |
|---|---|
| `conversations.md` | every chat, to read, with the day and time of each message |
| `messages.jsonl` | the same messages, one per line, for a program to read |
| `memory.json` | everything Diya remembers about you (and what she was told about other people), with who it is about, where it came from and each step of its history |
| `memory_profile.txt` | just the facts she uses now, as a short list |
| `tasks.json`, `reminders.json`, `repeating_reminders.json`, `automations.json` | your tasks, reminders (one-off and repeating) and automations |
| `categories.json` | which of your messages is in which category |
| `feedback.json` | the replies you rated, why, and your notes |
| `actions.json` | what you asked Diya to do at a service, what you approved, and how it came out |
| `activity.json` | what Diya did with a tool or an account |
| `proactive.json` | what Diya wrote first |
| `README.txt` | how many of each, and what is left out |

## What is not in it, on purpose

The access token's hash, the sign-in tokens of every connection and your Google client secret, the keys of the devices that get notifications, the Telegram bridge's state, the numbers Diya uses to find similar
facts, and her own queues and timings. Those are secrets or Diya's working data, not yours, and a copy of your chats should be safe to put in a drawer. (The files are still your private words in the clear: keep
them with your own documents. `exports/` is ignored by git here, so it cannot be published by accident.)

## Safe by construction

- It only **reads**: the database is opened read-only and never migrated, so an export cannot change or damage anything, and a database from an older Diya just gives empty files.
- It is written beside its place and moved in whole, so a run that fails leaves no half-folder, and a new export **never replaces** an old one.
- Invisible and control characters (other than line breaks) are written as visible `\uXXXX` escapes, as everywhere else Diya shows your words.
- A message you **forgot for good** is not in it: it is gone from the database, and an export is made from the database.
- Nothing goes over the network.

`tests/test_export.py` checks each of these. Deleting your data is separate and already built: "Forget this" on a message, "Forget for good" on a fact, and Disconnect on a connection (`docs/FORGET_DESIGN.md`).
