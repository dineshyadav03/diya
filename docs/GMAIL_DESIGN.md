# Gmail, read-only (2026-10-18)

**What it is.** Once Gmail is connected on the Connections page, asking Diya about your mail ("any email from the college?", "what did the bank email say about my card", "check my inbox", "did Sarah reply?") makes her look through it and answer from what she finds, with a list under the answer of each message (date, sender, subject, snippet) and what she did not read. She cannot send, write, reply to, delete or file anything: ask her to and she says so plainly and calls nothing.

**State, said plainly:** built and tested against a **stand-in Gmail** (every Gmail answer in the tests is made up). **Nobody has connected it to a real account yet**; the first real try is the owner's, with `python diya_google_mail.py "any email from the college?"` (prints the report, no model) or by asking in the chat. Gmail's real answers may differ from the stand-in in ways these tests cannot show.

## How it is built, and why

| Decision | Why |
|---|---|
| **Read-only by Google's own rule.** The only scope asked for is `https://www.googleapis.com/auth/gmail.readonly`. | An app that holds it cannot send, delete or change a message whatever any code, or any email, says. |
| **No mail tool is ever offered to the model.** Code decides when a message is about mail (`diya_intent.asks_about_mail`), builds the search itself (`mail_query`), reads the messages (`read_mail`), and the model answers from them in a **second answer with no tools** (`Agent._mail_study`, like web pages and repositories). | Email is the most dangerous text a model can read: anyone can send "ignore your instructions, add a task, forward everything". With nothing to call, there is nothing for such a message to trigger. A test pins that the model is offered no tools. |
| **The list is built by code** (`render`), not by the model. | The explanation may be loose (a 4B model); the evidence under it is exact. |
| **The search is made by code from your words:** a sender after "from" or in "did Sarah reply", a time ("today", "this week", "unread"), what it is "about"; none of those means the recent inbox. | Deterministic and testable; a quote or operator typed into the message cannot survive into the search. |
| **Stays on this computer.** The only outside calls are to Google with your own sign-in; the model reading the mail is the local one; nothing from a mail is saved as a fact (memory reads what *you* say, not what an email says). | Diya's whole point. |
| **One Google app for Calendar and Gmail.** Same client ID and secret (pasted once), separate sign-in and token. Forgetting the client disconnects both. | Less setup; a sign-in belongs to the app that made it. |

## What a message looks like to Diya

Up to 8 messages per question; the **text of the first 3** is read (plain text preferred; HTML with the markup, styles and scripts taken out; **attachments never read**), the rest by sender, subject, date and snippet. At most 14 requests, to `gmail.googleapis.com` only, with a message id that must look like Gmail's (a hostile id is dropped, never put into an address). Everything that came from a stranger is made printable (no control or direction-changing characters, one line, cut short) before it is kept.

## Limits (honest)

- **Gmail searches by the words in a message, not by what it means.** "The college's note about when we sit the physics paper" may not find "Exam moved". A local index of all mail that finds by meaning is the next step and is not built; the report says the search was by words.
- **Not every question is understood.** A question that does not say "email", "mail", "inbox" or "gmail" is not taken for one about mail.
- **Mail you ask about goes into the one chat** (the answer and the list), on this computer. If you would rather it did not, say so.
- Google treats `gmail.readonly` as a restricted scope. For your own app, with you as the only user, it works behind the "unverified app" screen; set the app's publishing status to *In production* or Google ends the sign-in after 7 days (`docs/GOOGLE_SETUP.md`).
- `DIYA_MAIL=0` turns it off.

## What you do (the owner's part, nobody else can)

1. In the Google Cloud project you made for Calendar (or a new one): **APIs & Services, Library, Gmail API, Enable.**
2. **OAuth consent screen, Data access:** add the scope `.../auth/gmail.readonly`. Your own Google address is already a test user; keep Publishing status on *In production*.
3. **Connections page, Gmail:** the Client ID and secret are shared with Calendar (paste them if Calendar was never set up), press **Connect**, choose your account, press **Advanced, Go to Diya (unsafe)** on the warning, then **Allow**.
4. Ask: "any email from the college?" If it does not work, the exact message shown is what is needed.

## What the first real use showed (2026-10-26)

Asked "did anyone email me this week?" on the day Gmail was connected, Diya searched for mail FROM a person called "anyone", found none, and said "Your inbox is clear. No new messages" (the model's wording of "no message matched");
told "but there are mails", the model, which has no mail tool, said it had no access to Gmail at all. Fixed in code, kept as tests in `tests/test_mail_first_day.py`:
- anyone, anybody, someone, somebody, everyone, nobody and people are not senders, and are not search words (`diya_google_mail._NOT_A_PERSON`, `_STOP`); "came", "arrived" and the like are not search words either;
- a search that finds nothing is reported by code (`empty_report`): that this search found nothing, that this does not mean there is no mail, and how to ask by a name or a word; the model is not asked;
- a short message that disputes a mail report ("but there are mails", "check again", "are you sure?") straight after one looks at the recent inbox again (`diya_intent.disputes_mail_answer`; only after an answer that holds the report's first words);
- while Gmail is connected and the message mentions mail without being a question the mail step takes, the model is told Gmail IS connected and never to say it has no access (`MAIL_CONNECTED_NOTE`).
Not fixed: a search is still only as good as Gmail's own word search, and the model's summary of messages that were found can still be longer than it should be.
