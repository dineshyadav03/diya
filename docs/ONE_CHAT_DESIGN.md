# One chat that sorts itself

The owner's idea (2026-10-16): **Diya has one chat, and it puts what is said into categories on its own; the categories can be looked at, but there is one chat.** Three steps, each one something that can be seen.

| Step | What the person sees | State |
|---|---|---|
| 1. One chat | The chat page always shows the same conversation, on every device. No "New chat". Earlier chats can be read, not written in. | built (this document) |
| 2. Sorting | Each message gets exactly one category after the reply, from a list that has no "Other". Measured on the owner's real messages first. | built (below) |
| 3. Browsing | Chips under the chat bar filter the chat by category; a tag under each message of the person's changes it with one click. | built (below) |
| 4. Managing | A Categories page: add, rename and merge categories, look inside one (from every chat), sort the earlier chats, and answer the new categories Diya suggests. | built (below) |

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

## Step 2 and 3: what was built (2026-10-16)

The owner's rule: **no "Other"; it has to somehow categorize.** Every message gets exactly one category.

- **The list** (`diya_categories.STARTER`, table `categories`, migration 18): Weather, Reminders & tasks, About me, About Diya, Learning, Chat. Every one of the owner's first 110 real messages fits one of them. A starter category that is renamed is still found by the name code knows it by (`origin`).
- **Code decides what code can know**, in this order: the tool that ran (weather tool: Weather; reminder or task tool: Reminders & tasks; notes search: About me; file listing: About Diya; web search: Learning), then the shape of the message (a greeting, a question about Diya, a reminder or task request, a fact the person shares about themselves, a weather word, a short "quick check"). A "check" that is about something else ("check the weather", "remind me to check the audit") is placed by the earlier rules.
- **The model decides the rest**, after the reply, one short question: which of these categories is the message in? Its answer is accepted only if it names exactly one category on the list; otherwise it is asked once more. If it still gives no usable answer (or is not running), the message takes **the category of the person's message before it** in the chat (a conversation stays on its subject), else Chat. Nothing is ever left without one.
- **It cannot make up a category while sorting.** The first version let the model answer "NEW: <name>" when nothing fit; measured on the owner's real messages it named one "File access limits". Disclosed deviation: I had told the owner "when nothing fits, Diya makes a new category herself". That is not safe to do quietly, so the closest category is used, and **new categories are meant to be proposed to the person** (a question with examples, like the memory questions) rather than made by the model. Not built yet.
- **The person can change anything:** `POST /api/categories` assigns a message to another category, adds a category, or renames one (starter ones too); `GET /api/categories` gives the list and where the newest messages are. On the page the tag under each of the person's messages is a menu that moves it (put back with a message if it could not be kept); the chips under the chat bar show the chat by category (All, or one). Adding and renaming categories has no page of its own yet (the API has it).
- **After the reply, never before it** (both chat routes): one exchange is sorted at a time, in a thread of its own; a failure to sort leaves the message untagged and breaks nothing. `DIYA_CATEGORIES=0` turns it off (what was sorted stays).

### Measured (real model `diya-chat`, 2026-10-16)

| Set | Code places | Code right | Model alone | Code first, then the model |
|---|---|---|---|---|
| The owner's real messages (85 distinct; the rules were shaped on these, so this is the optimistic number) | 41 | 41 of 41 | 78 of 85 (92%) | **80 of 85 (94%)** |
| 48 messages written by the author, never used to shape a rule (`tests/labelled_categories.py`; several on purpose fit nothing well: "book me a table", "play some music") | 13 | 13 of 13 | 43 of 48 (90%) | **45 of 48 (94%)** |

The misses are the kind a click fixes ("play some music" went to Reminders & tasks; "can you read my emails" to Chat; "what should I do this weekend" to Reminders & tasks). Before the rules were added the first real-message run gave 78 of 85 and two wrong calls the rules now catch ("final check" taken for a task; "my library card expires ..." for a task). End to end on a throwaway database with the real model: "hey", "how does a transformer neural network work", "my sister's wedding is in December", "which model are you running on" and "what's the weather in Pune" all landed in Chat, Learning, About me, About Diya and Weather.

### Not built after step 3 (all three are built in step 4 below)

- A page to add, rename and merge categories.
- Proposing a new category when a lot of messages sit badly in the broad ones.
- Sorting the 38 earlier chats.

## Step 4: the Categories page, suggestions, and the earlier chats (2026-10-16)

### What was built

- **The Categories page** (`/categories`, in the sidebar under Chat): every category with how many messages are in it; **Rename**; **Merge into...** (the messages move and the category leaves the list; a hidden row is kept, migration 19, so code that still says "Weather" finds where Weather went); **Add**; **Look inside** (the person's newest messages in it, from every chat, each linking to its chat, and whether Diya or the person put it there).
- **Sort my earlier chats:** puts every message that is in no category into one, the same way a new message is sorted (code first, then the model, then the one before it), oldest first, one at a time, as a background job that says how far it is ("23 of 65"). Dreaming also does it by itself, up to 200 messages a cycle. An earlier chat opened from History now shows its messages' tags too (read-only chat, changeable tag).
- **New categories Diya suggests.** Sorting never makes a category up (step 2). Instead, once a day (Dreaming) or when asked ("Look for a new category") Diya looks at the newest messages **no rule could place** and asks the model one thing, for a **name**: "what one more specific subject do at least five of these share that no category describes well?". If it names one that is not already a category and was not refused before, code asks the model, for each message, "does this clearly talk about X?" and counts the yeses. Fewer than five and nothing is suggested. The suggestion shows the messages with a tick each; the person unticks any that do not belong and presses **Make the category**, or **No thanks** (the name is not suggested again). Only one suggestion waits at a time. The chat's chip bar says "A new category is suggested" when one waits.

### Measured (real model `diya-chat`, 2026-10-16)

- **Sorting the earlier chats**, on a copy of the owner's real database (the live one was only read): **110 messages in 49 seconds**, 54 decided by code and 56 by the model; where they landed: Chat 51, About me 19, Reminders & tasks 12, Weather 11, About Diya 10, Learning 7. Against my hand labels of the 84 distinct messages: **79 right (94%)**.
- **Suggesting a category** (48 everyday messages mixed with a hidden topic, 3 runs each, order shuffled each time). The first design asked the model for the name **and** the message numbers in one go: it named good topics but chose the messages sloppily (13 chosen, of which 4 or 6 of the 8 real ones; or 4 chosen, of which 3) and, on a control with no topic at all, **invented one every time** ("Personal goals"). The two-step design above, with its final wording, three runs each: **control (no topic): no suggestion in 3 of 3**. **Fitness topic (6 messages): found in 3 of 3** ("Health": all 6 real messages plus 3 others that are health-adjacent). **School topic (8 messages): found in 1 of 3** ("Exams": 4 of the 8 plus 1 other); in the other two it found nothing, because the model's name did not gather five clear yeses. So it is **conservative**: it would rather say nothing than suggest a wrong category, and it can miss a real one. The messages in a suggestion are noisy (about one in three is borderline), which is why the person ticks and unticks before anything moves.
- **Embeddings do not work for this.** Grouping short everyday messages by the local embedding model was tried first and measured: the messages of a hidden topic are only slightly closer to each other (mean 0.51) than to everything else (0.39), with overlap, so no cut-off separates them. Dropped.
- **The page**, in the design rig on desktop and phone sizes: the list with counts, a suggestion with ticks, looking inside a category, rename and merge, answering a suggestion with one message unticked, a running job and a failed load: all checks pass, no contrast failures.

### Limits (honest)

- The model's calls on messages no rule can place are right about nine times in ten on the data measured, not always; the tag is one click to fix, and nothing in Diya depends on it.
- A suggestion can be noisy (it is a 4B model); that is the reason the person decides and unticks.
- The measured data is the owner's own early use: half of it is quick tests and small talk, so "Chat" is half of everything. How it does on a life with more school, health and people in it has not been measured because that data does not exist yet.
- ~~Merging cannot be undone from the page~~ It can, since 2026-10-21 (below).

## Taking a merge back, and searching by words (2026-10-21; tasks DIYA-156 and DIYA-160)

**Undo.** A merge now leaves a row in `category_merges` (migration 26): which category went into which, their names, and for each message it moved only the message's number, who sorted it and when
(never its words). The Categories page lists the newest merges with an **Undo** button. Undoing is one act: the category is shown again under its own name (a starter category in its own place, and
found by its starter name again), and each message the merge moved goes back to it **unless it has been changed since** (moved by the person, or sorted again): the page says how many came back and
how many were left. A message that joined the target after the merge stays there. An undo is refused, changing nothing, when it was already undone, when the category it went into was itself merged away
since (undo that later merge first), or when another category has taken its name (rename that one). `tests/test_category_undo_search.py`.

**Search.** `Book.search` finds the person's words and Diya's that contain the words typed (case ignored; `%` and `_` are only themselves; at least two characters), newest first, each with the day and the
category, across the one chat and every earlier one. A reply counts as the category of the message it answers. It can be narrowed to a category and to the person's own calendar days, either as two dates or as
a phrase (yesterday, last week, last month) read by `diya_when.window`. It looks for the words, not the meaning: for the meaning of an earlier message, chat recall (`docs/EPISODIC_DESIGN.md`) does that. On the page: **Search your messages**.
Both are in `diya_categories_api.py` (`undo_merge`, `search`) behind the same access token as the rest.
