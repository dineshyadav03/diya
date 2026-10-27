# Home: the cards Diya found for today (2026-10-27)

Home is the front page of the UI (the first tab, `/home`). It has the shape of Hark's Home: a column of cards at the left, the one chat beside it. The look is option A of
`docs/mockups/home-mockup.html` (a headline that counts what needs you, one thing per card, a dashed edge for a card that only asks), drawn with the app's own tokens so the light and dark themes work.

## What a card is

A thing Diya FOUND, by code, in rows and accounts it can already read. No model writes any of it: the words are the person's own reminder, task and calendar title, or a sentence made in `diya_home.py`.

| Card (chip) | Found in | Buttons (the routes that already exist) |
|---|---|---|
| Do: a reminder that has come due | reminders | Mark done, Snooze to tomorrow 9:00 |
| Finish / Do: a task overdue or due today | tasks | Mark done |
| Check: a question about memory | the memory question queue (automatic memory on) | Yes / No / Keep, as worded for the chat ("Edit it" stays in the chat) |
| Approve: an action waiting for your yes | the actions table | Open the chat |
| Next: the next event within 8 hours | Google Calendar, read only | Remind me 30 minutes before |
| Soon: a reminder later today | reminders | Mark done |

A card that `needs` the person is counted in the headline ("Three things need you today."); the Next and Soon cards are only coming up. "Not now" hides a card for the rest of the day in that browser.
The panel under the cards counts the day: needs you, coming up, next event.

## Approvals are answered in the chat

An action that would change another service (send, add, delete) is still staged by code and still carries the exact words, and it is still done only when the person says yes: that gate is what stops an email
or a web page from making Diya act. What changed on 2026-10-27 is where the yes is given: in the chat, in the strip under the message where Diya asks (`WaitingActions`), not on a separate page. A Home card
for such an action only says it is waiting and opens the chat. Nothing on Home can approve anything.

## What is not here yet

Mail ("Priya asked for the lab notes"): needs a rule for "waiting for a reply" that is right often enough to trust. Bills and websites: nothing in Diya touches a website. Custom panels, a weather panel,
Projects. A typed "yes" in the chat that approves the waiting action (it would have to be read by code, never by the model, and never for an action that came from outside text).

## Parts

`diya_home.py` (the cards, pure), `diya_home_api.py` (`GET /api/home`; Google Calendar asked at most once in 2 minutes; a source that cannot be read is named in `problems`),
`frontend/components/HomeCards.jsx`, `frontend/app/home/page.js` (the column and the chat, the same chat as the Chat tab), `tests/test_home.py`.
