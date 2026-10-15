# One chat that sorts itself

The owner's idea (2026-10-16): **Diya has one chat, and it puts what is said into categories on its own; the categories can be looked at, but there is one chat.** Three steps, each one something that can be seen.

| Step | What the person sees | State |
|---|---|---|
| 1. One chat | The chat page always shows the same conversation, on every device. No "New chat". Earlier chats can be read, not written in. | built (this document) |
| 2. Sorting | Each exchange gets a category after the reply (a fixed list the person can edit, plus "Other"). Measured on the owner's real messages first. | not built |
| 3. Browsing | Category chips filter the chat; one click fixes a wrong one. | not built |

## Why

An assistant that knows you is one continuing conversation, not a pile of chats. The owner's month of use is 38 chats, one of which (36 messages) did most of the work; a new browser, a new phone or the Telegram channel each started a chat of its own, and "new chat" looked like amnesia. Diya's memory (facts, recall, knowledge pages) already carries what matters between chats, so one chat costs nothing in what she knows.

## What step 1 does

- **The one chat is chosen once and kept** (`Store.main_thread`, table `app_state`, migration 17): the chat with the newest message the first time, or a new chat called "Diya" when there are none. Chosen under one write lock, so the page, the phone and the notifier asking at the same moment get the same chat. A kept chat that no longer exists is chosen again.
- **Reading never makes a chat.** `Store.current_main_thread` only looks; the chat list and the history of an earlier chat use it, so listing an empty database leaves it empty.
- **A message that names no chat goes into the one chat** (`/api/chat`, `/api/chat/stream`). A message that names a chat still goes there (the API stays what it was); the page never names one.
- **Everything of Diya's lands in it:** the morning and evening messages (`diya_proactive`) and the Telegram channel (`diya_telegram.AgentAsker`) used to make or keep chats of their own; both use the one chat now, so the laptop, the phone and Diya's own first messages are one conversation.
- **`GET /api/history/main`** gives the one chat (made if need be): `{thread_id, is_main, more_before, messages}`, the newest 300 messages (`MAX_PAGE_MESSAGES`), with `more_before` true when older ones were left out (the page says they are in History). `GET /api/history/<number>` reads an earlier chat whole, as before, with `is_main: false`. The model's own window did not change: it was already cut to the newest messages that fit (`DIYA_HISTORY_CHARS`), so a chat that never ends does not slow it.
- **The page keeps no chat id in the browser** (it used to, in `localStorage`, which is what made a second chat on every other device). It asks for `main`. A link that names an earlier chat (History, an old action) opens it **read-only** under a bar that says so, with a link back; the composer is off and says why.
- **No "New chat".** Nothing in the composer starts another chat. History is now "Past chats": the chats from before, still searchable and nameable, with the current one marked "Your chat now".

## Not changed, on purpose

- Nothing is deleted or merged: the 38 old chats stay exactly as they were. The one chat is the one that had the newest message.
- Automations ("every morning at 8am tell me the weather") post through the same path as the morning message (`diya_proactive`), so their answers now land in the one chat too. The access rules are as before: every route is behind the token.

## Open questions for steps 2 and 3

- The categories should come from what the person says. In the owner's 110 real messages about half are quick checks and small talk, and the rest are weather, reminders, facts about themselves, questions about Diya, and curiosity: there is almost no school or health talk yet. Starting list: Weather, Reminders & tasks, About me, About Diya, Learning, Chat, Other (the person edits it). A fixed list, not categories the model invents, because invented ones drift and multiply.
- Code decides what code can know (a reminder was made, the weather was looked up); the model is asked only for the rest, after the reply, and measured on the owner's real messages before a category is shown.
