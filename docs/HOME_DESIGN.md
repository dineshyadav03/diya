# Home: the cards Diya found for today (2026-10-27)

Home is the front page of the UI (the first tab, `/home`). It has the shape of Hark's Home: a column of cards at the left, the one chat beside it. The look is option A of
`docs/mockups/home-mockup.html` (a headline that counts what needs you, one thing per card, a dashed edge for a card that only asks), drawn with the app's own tokens so the light and dark themes work.

## What a card is

A thing Diya FOUND, by code, in rows and accounts it can already read. No model writes any of it: the words are the person's own reminder, task and calendar title, or a sentence made in `diya_home.py`.

| Card (chip) | Found in | Buttons (the routes that already exist) |
|---|---|---|
| Do: a reminder that has come due | reminders | Mark done, Snooze to tomorrow 9:00 |
| Finish / Do: a task overdue or due today | tasks | Mark done |
| Reply: mail waiting for a reply | Gmail, read only (`diya_mail_waiting.py`) | Draft a reply: asks Diya in the chat; the draft is asked about in the chat before it is saved |
| Approve: an action waiting for your yes | the actions table | Open the chat |
| Next: the next event within 8 hours | Google Calendar, read only | Remind me 30 minutes before |
| Soon: a reminder later today | reminders | Mark done |

A card that `needs` the person is counted in the headline ("Three things need you today."); the Next and Soon cards are only coming up. "Not now" hides a card for the rest of the day in that browser.
The panel under the cards counts the day: needs you, coming up, next event.

## Approvals are answered in the chat

An action that would change another service (send, add, delete) is still staged by code and still carries the exact words, and it is still done only when the person says yes: that gate is what stops an email
or a web page from making Diya act. What changed on 2026-10-27 is where the yes is given: in the chat, in the strip under the message where Diya asks (`WaitingActions`), not on a separate page. A Home card
for such an action only says it is waiting and opens the chat. Nothing on Home can approve anything.

## Mail waiting for a reply

The rule is narrow on purpose. A thread counts only when it is a conversation the person is in (an earlier message of it is the person's own), its last message is from a person (not no-reply, notification or
bulk mail) and is neither the person's own nor a draft, and it is in the Primary inbox and under three days old. The first look at the real mailbox (2026-10-27) found six threads that passed every other test and
were all offers and surveys marked Important by Gmail, so "the person has written in it" is required: a first message from a new real person is not found, on purpose. Only headers and labels are read.
The button's sentence holds only the sender's name with everything but letters, spaces and . ' - taken out, never the subject or any text of a mail, and it is said as the person's own message in the chat
(`diya-ask`, or `/?ask=` on a narrow screen); Diya reads the mail itself, so the draft that follows is asked about like any other action.

Gmail and Calendar are slow (nine seconds for the mailbox), so Home never waits for them: it shows the local cards at once, reads the accounts in a thread of their own, and the page asks again after four seconds
while the API says `looking`.

## Memory without questions

DIYA_ASK_MEMORY=0 (set for the owner on 2026-10-27): what automatic memory used to hold back to ask about (private-looking, doubtful, like a known fact) is remembered instead (`diya_autonomy.settle`), a conflict
replaces the older fact with the old kept in the trail, and no question card is made or shown, on Home or in the chat. Secrets, copies and what the person never said are still never kept; limits and failures
(full memory, the daily cap, the breaker) still leave a candidate waiting on the Memory page.

## Categories

Sorting is off (DIYA_CATEGORIES=0) and the chat shows no category: the chips, the tags, the Categories page and its menu entry are gone. The backend (`diya_categories*.py`) is still in the repository, unused.

## The weather and the sky

The Weather panel asks for the place with a button, as Hark does ("Share your location"): the browser asks, the place is rounded to two decimals, kept in this computer's database and sent only to Open-Meteo. The
sky behind every page follows it (`<html data-sky data-daytime>`, `components/WeatherProvider.jsx`, `diya_weather.py`): a tint over the usual sky for clear, cloudy, fog, rain, snow and storm, and a veil at night
in the dark theme. Every tint stays on the safe side of the page background, so the text contrast the theme proves still holds (`tests/test_weather.py` checks the numbers). With no place shared there is no weather
and the sky is the usual one.

## What is not here yet

Bills and websites: nothing in Diya touches a website. Custom panels, Projects. A typed "yes" in the chat that approves the waiting action (it would have to be read by code, never by the model, and never for an
action that came from outside text). A weather place from the person's own words ("I live in Pune").

## Parts

`diya_home.py` (the cards, pure), `diya_home_api.py` (`GET /api/home`; Calendar and Gmail read in the background; a source that cannot be read is named in `problems`), `diya_mail_waiting.py`, `diya_weather.py` and `diya_weather_api.py`,
`frontend/components/HomeCards.jsx`, `frontend/app/home/page.js` (the column and the chat, the same chat as the Chat tab), `tests/test_home.py`.
