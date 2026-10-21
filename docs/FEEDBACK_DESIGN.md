# Helpful / not helpful: what you think of Diya's replies (2026-10-21; migration 27)

**Why.** The weakest part of Diya was the one that tells her she got something wrong. Nothing recorded a bad answer, so every measurement so far was made on invented data, and the owner's own bad answers (a model that said it
was not connected when it was, a year written as "2.020") were found only because the owner happened to look. This keeps what you think of each reply, so the first real numbers are your own.

**What you see.** Under each of your messages in the chat, two small buttons: **Helpful** and **Not helpful**, about Diya's reply to that message. Press one again to take it back. After **Not helpful** a menu asks what was wrong:
*The answer was wrong · It made something up · It did not do what I asked · It was too slow · It showed or asked for something private or unsafe · Something else*. (A note field is in the store and the API; the page does not show one yet.)

**What is kept.** One row per message of yours (`reply_feedback`): the rating, the reason, the note, a version and the times. Nothing else, and never the model's text. Forgetting a message takes its row with it.

**Safe by construction.**
* It is never given to the model, and never changes what Diya says or remembers: it is read by you and counted by the scorecard (`python diya_scorecard.py`, "Replies rated not helpful").
* A change from a page that is out of date (another tab, another device) is refused and shows the item as it now is (409), never written over.
* Only a message of yours can be rated; a reason must be one of the list; a note must hold words and is at most 2,000 characters, kept exactly as written.

**Where the idea comes from.** The shape (a positive or negative rating, an optional reason from a fixed list, an optional note, a version on each item) follows the feedback package of DeepSeek's harness (MIT; `harness/LICENSE`; `THIRD_PARTY_NOTICES.md`).
The list of reasons, the words and the code are Diya's own.

**Not done.** A page that lists all the replies you marked not helpful with their notes; a note box on the chat page; a use of the numbers to change anything (Diya is not changed by them, on purpose: a change goes through you and a test).
