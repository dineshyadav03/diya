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

## Gmail too (read-only)

The same Google app serves Gmail: in the same project enable the **Gmail API**, add the scope `https://www.googleapis.com/auth/gmail.readonly` under *Data access*, and press **Connect** on the Gmail card (the Client ID and secret you pasted for Calendar are shared). Diya can then look through your mail when you ask and can never send, change or delete any. What it does and does not do, and what is not yet tried against a real account: `docs/GMAIL_DESIGN.md`.
