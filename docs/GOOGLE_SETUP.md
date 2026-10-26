# Connecting Google Calendar: one setup, then a normal sign-in

Claude's Google connection is one click because Anthropic registered a Google app once, for everybody, and runs the servers it signs in through. Diya runs on your computer with no server of its own, so
**you register a small Google app of your own, once** (free, about ten minutes), and paste its two codes on the **Connections** page. After that, connecting is the usual Google sign-in and an **Allow**.
Diya only asks to read your calendar (`calendar.readonly`); nothing here can change an event.

## Once, in Google Cloud

1. Open <https://console.cloud.google.com> and create a project (any name).
2. **APIs & Services, Library:** search for **Google Calendar API** and press **Enable**.
3. **OAuth consent screen** (called **Google Auth platform** in the newer console): choose **External**, give it a name (Diya) and your email, and add your own Google address as a **test user**.
   Then, under **Audience**, set **Publishing status** to **In production**. Left on *Testing*, Google ends your sign-in after 7 days and you would have to connect again every week.
   The app stays *unverified* (verifying is for apps with many users), so Google shows a warning on first sign-in: choose **Advanced**, then **Go to Diya (unsafe)**. It is your own app, on your own account.
4. **Credentials** (**Clients** in the newer console): **Create credentials, OAuth client ID**, application type **Desktop app**. Google shows a **Client ID** (ends in `.apps.googleusercontent.com`) and a **Client secret**.

## Then, in Diya

1. **Connections** page, **Google Calendar:** paste the Client ID and the Client secret and press **Save**. They are checked for the shape Google gives them, stored in a file of their own in the connector
   tokens folder (not in the database), and never shown again.
2. Press **Connect**. Your browser opens Google's own page; sign in, press Allow. The page says "Diya is connected" and you can close the tab.
3. Ask Diya what is on your calendar. **Disconnect** removes the sign-in; **Use a different app** forgets the pasted codes (and disconnects, because a sign-in belongs to the app it was made with).

`DIYA_GOOGLE_CLIENT_ID` and `DIYA_GOOGLE_CLIENT_SECRET`, if you set them, win over what was pasted (and the page then says the codes come from the environment).

## What is not verified

The page, the storage and the checks are tested; the sign-in flow was tested against a stand-in for Google. **Nobody has signed in through it against the real Google yet.** If the sign-in stops, the exact
message on the page is what is needed.

## Adding things: events, tasks, folders, documents (each when you approve it)

Diya can also *add* to your Google account, one thing at a time, only after you press Approve on the Actions page. Each is its own card on the Connections page with its own narrow permission, so you switch on only what you want:

| Card | Enable this API in the project | Add this scope under *Data access* |
|---|---|---|
| Google Calendar (add events) | Google Calendar API (already on) | `https://www.googleapis.com/auth/calendar.events` |
| Google Tasks | Google Tasks API | `https://www.googleapis.com/auth/tasks` |
| Google Drive and Docs (new things) | Google Drive API **and** Google Docs API | `https://www.googleapis.com/auth/drive.file` |

The Client ID and secret you pasted are shared; press **Connect** on each card you want. `drive.file` lets Diya see only files she made herself, never the rest of your Drive. Nothing is edited or deleted, and no mail is sent or invites go out. What each does, how it is kept safe, and what is not verified against a real account: `docs/GOOGLE_WRITE_DESIGN.md`.

## Gmail too (read-only)

The same Google app serves Gmail: in the same project enable the **Gmail API**, add the scope `https://www.googleapis.com/auth/gmail.readonly` under *Data access*, and press **Connect** on the Gmail card (the Client ID and secret you pasted for Calendar are shared). Diya can then look through your mail when you ask and can never send, change or delete any. What it does and does not do, and what is not yet tried against a real account: `docs/GMAIL_DESIGN.md`.

## All of it in one sign-in: "Connect all Google"

Once the Client ID and secret are saved, the Connections page shows **Connect all Google** above the cards. It sends Google ONE sign-in that asks for the five permissions above (and no others), so there is one Google screen and one **Allow** instead of five.
Before pressing it, do the project preparation once: enable the five services (Calendar, Gmail, Tasks, Drive, Docs), add the five scopes under *Data access*, and keep *Publishing status* on **In production**.

- Google's screen lets you untick any permission. A card whose permission you unticked stays off (or stays as it was), and the page says which were left off. Nothing is connected unless Google says it granted that card's permission.
- Google gives back one sign-in. Diya keeps it under each card that was granted, so every card still **disconnects on its own** (Diya then stops using that permission). Google is told to forget the whole permission when the **last** Google card is disconnected.
- Every change Diya would make still waits for your Approve on the Actions page, one at a time, exactly as with five separate sign-ins.
- The five separate **Connect** buttons stay, for connecting one card by itself (it then no longer shares the sign-in).


## The newer cards (added 2026-10-26 and 2026-10-27)

Beyond the first five, Diya has more Google cards. Each is its own card with its own narrow permission, **off until you add its permission in your Google project and connect it**, and every change any of them makes still waits for your Approve, one at a time.

**Once, in the Google Cloud console** (the same project): under *APIs & Services, Library* switch on, if they are not on yet: **Gmail API, Google Drive API, Google Docs API, Google Sheets API, Google Slides API, Google Forms API, People API** (Calendar and Tasks are on already). Under *Google Auth platform, Data access* add the permissions in the table below that you want. Keep *Publishing status* on **In production**.

| Card | Permission to add (Data access) | What it lets Diya do |
|---|---|---|
| Gmail: drafts | `https://www.googleapis.com/auth/gmail.compose` | Save, replace and throw away drafts. It never sends. |
| Gmail: send | `https://www.googleapis.com/auth/gmail.send` | Send, reply to or forward ONE email you approved, to an address you typed (or one contact). At most 20 a day. |
| Gmail: organise | `https://www.googleapis.com/auth/gmail.modify` | Archive, mark read, star, label, bin and bring back ONE email at a time. Never deletes for good. |
| Google Calendar (change events) | `https://www.googleapis.com/auth/calendar.events` (already added) | Rename, move or cancel one of your own events that has no guests. |
| Google Calendar (guests) | `https://www.googleapis.com/auth/calendar.events` (already added) | Invite typed addresses, answer an invitation. Google emails the people involved. |
| Google Drive (read) | `https://www.googleapis.com/auth/drive.readonly` | Search your whole Drive and read a Doc, Sheet, Slides or text file when you ask. Changes nothing. |
| Google Drive (change) | `https://www.googleapis.com/auth/drive.file` (already added) | Rename, move, bin, share, edit Docs, and make Sheets, Slides and Forms, on what Diya made only. |
| Google Contacts (read) | `https://www.googleapis.com/auth/contacts.readonly` | Look someone up; turn a name into an address for an email you approve. |
| Google Contacts (change) | `https://www.googleapis.com/auth/contacts` | Add a contact, add an email or number, put in a group, delete one. |

**Then on Diya's Connections page**: once the Client ID and secret are saved, a second button **Connect the newer Google cards** sends Google ONE more sign-in that asks for exactly these permissions (each once). Google's screen lets you untick any; that card just stays off. You can also press **Connect** on one card by itself.
Each card can be disconnected on its own; Google is told to forget the permission when the last Google card goes.

**Two of these are the broad ones, so read this before adding them:** `drive.readonly` lets Diya see every file in your Drive (to search and read; it cannot change any) and `contacts` lets Diya change your address book (each change approved). Skip either if you do not want Diya to have it; the rest still work.

What Diya keeps because of Google can be shown, exported and removed at any time: `python diya_google_data.py show` (and `export --out FILE`, `purge --what actions|activity|replies|connections`; see `docs/GOOGLE_CHANGES.md`).
