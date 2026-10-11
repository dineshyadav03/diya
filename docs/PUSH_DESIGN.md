# Telling the phone: one list of what is worth interrupting for, and Web Push (units P3 and P2, design note)

> **Status (2026-10-11):** written before the code, as every unit's note is. The owner asked for the whole roadmap to be built, which is the yes this unit
> needed (`docs/PHONE_CHANNEL_DESIGN.md` section 6); what stays the owner's is switching it on (`DIYA_PUSH=1`), choosing the contact address that goes to the push
> service, and trying it on their own phone. Facts about the outside world below are from general knowledge of the Web Push standards (RFC 8030, RFC 8188,
> RFC 8291, RFC 8292), not checked against a push service's current behaviour: **nothing here has been sent to a real push service.**

## 1. What this is, and is not

It is "B. Tell" of the phone design: Diya reaches the phone first, one way. Four things are worth an interruption, and only four: a reminder is due, a question is
waiting, an action is waiting for approval, and "your day" at a time the owner chooses. It carries no conversation, no memory and no way to answer: tapping it opens
the UI, which is behind the passcode. It is off by default and by one setting.

## 2. One list of events (P3: `diya_events.py`)

Two channels now say "something is waiting": the Windows toast (`diya_notify.py`, which already exists and runs every five minutes on the owner's computer) and
the push. They must not disagree about what is worth saying or how it is worded, so the rules live in one place and both read them:

- **The words.** A reminder is "Diya: Mon 12 Oct, 09:00" over the reminder's own text, or "Diya" over "A reminder is due" when the text is hidden; a question is "Diya has a question
  for you." (never what it is about); an action is "An action is waiting for your approval." (never what it is); the day is "Your day is ready." with, only when text is shown,
  the brief's own headline ("2 reminders later today, 1 task due today."). The reminder and question wording is moved out of `diya_notify.py` unchanged, and
  `diya_notify.py` now calls it.
- **The flood rule.** When more than five things are due at once, the first four are told one by one and one more says how many remain (`MAX_NOTIFICATIONS`).
- **Quiet hours.** Questions, actions and the day are held back in the quiet hours (`DIYA_PUSH_QUIET`, "22-07" by default; the toast keeps using
  `DIYA_QUESTIONS_QUIET` for questions as before). **Reminders are never held back**: a reminder is something the person asked for at a time, and an alarm that does not ring at night is
  not an alarm. (The phone design said push is "off at night"; this is a deliberate narrowing of that, written here.)
- **What counts as pending** is decided in one place for each kind: reminders due, not done, not yet told on this channel; questions that may be shown now (the
  queue's own rules, A5) and are not yet told on this channel; actions with status "proposed" not yet told; the day, once per local date, from the chosen time on.

**What does not change:** the Windows toast keeps its own markers (`reminders.notified_at`, `memory_questions.notified_at`), so nothing the live scheduled task does today changes.
It does not gain the "action waiting" and "your day" events: those are push only until the owner asks for them on the desktop too (disclosed, not hidden).

## 3. Who has been told what (migration 10: `event_deliveries`)

`event_deliveries(channel, key, sent_at)`, unique on (channel, key). A push is recorded here only after the push service ACCEPTED it (HTTP 201), so a failed send is tried
again on the next pass and a delivery is never lost to a crash between "sent" and "recorded"; the cost is that a crash in that gap can send twice, which for a reminder is the
better mistake (as it is for the toast). Keys are `reminder:<id>`, `question:<id>`, `action:<id>`, `day:<local date>`. A "more" summary records every key it stands for.

## 4. Subscriptions (migration 11: `push_subscriptions`)

A subscription is what a browser hands over when the person taps "Notify this device": an endpoint URL at the push service, a public key (`p256dh`, 65 bytes) and an auth
secret (16 bytes). The table holds `id, endpoint (unique), p256dh, auth, created_at, last_ok_at, failures`. Rules, all enforced before anything is stored:

- the endpoint must be `https://`, at most 2,048 characters, with a host name that is not `localhost`, not an IP address at all, and has no credentials or fragment. (The owner is the
  only person who can subscribe, behind the token and the passcode, so this is not a fence against an attacker; it is a fence against a mistake or a hostile page turning the sender into a way
  to make requests to this computer or this network: a push endpoint is always a public host name at a push service.)
- `p256dh` must decode to 65 bytes starting 0x04 and be a point on the curve (checked by loading it); `auth` must decode to exactly 16 bytes.
- at most 10 subscriptions; subscribing again with the same endpoint updates it; unsubscribing removes it. The endpoint is a bearer URL for pushing to that phone: it is never returned by
  any route (the list shows ids, when each was made and last worked) and never written to a log.

## 5. The sending (P2: `diya_push.py`)

- **The crypto is not written here.** Web Push needs ECDH on P-256, ECDSA (ES256) and AES-128-GCM, and none of that is in Python's standard library. Hand-written crypto is how
  mistakes become vulnerabilities, so `cryptography` does the primitives; `diya_push.py` only arranges them as RFC 8291 and RFC 8292 say. It is an OPTIONAL dependency
  (`pip install ".[push]"`, pinned in `pyproject.toml`, not in `requirements.lock`, which stays what the app and the suite need): without it `DIYA_PUSH=1` refuses to start with the line to
  run. The tests that need it are skipped, not failed, where it is absent. HKDF is the small `hmac` construction of RFC 5869, checked against `cryptography`'s own.
- **The message.** `aes128gcm` content coding (RFC 8188): a fresh salt and a fresh P-256 key for every message, one record of at most 4,096 bytes, the payload JSON `{title, body, tag}`.
  The service worker never receives a URL from the payload: a click opens `/`, so the payload cannot send the person anywhere.
- **The identity.** A VAPID key pair (RFC 8292), made on first use and kept in the data folder (`push_vapid.json`, gitignored; the private half never leaves it, no route returns it). Each request
  carries a short-lived (12 hour) ES256 token naming the push service's own origin, and the contact in `DIYA_PUSH_SUBJECT`. **The contact is required and is the owner's to choose**
  (`mailto:` or `https:`): it is the one thing sent to the push service that identifies anyone, so Diya does not invent one or take the owner's from anywhere else.
- **What the response means.** 201 (or 200, 202): accepted. 404 and 410: that subscription is gone for good; it is deleted. 400, 401, 403, 413 and any other 4xx or 3xx: Diya's request was refused;
  counted as one failure for that device in that pass (however many messages it was sent) and said in the log by status only. **A refusal never removes a device**: a wrong contact
  setting or a clock that is off would otherwise cost every subscription, each of which has to be made again on its phone. After five passes in a row with a refusal the device is
  PAUSED (shown in the list, skipped by the sender, said once a pass); a test message that works (`diya_push.py --test`, or "Send a test" in the UI) clears it, and so does subscribing
  again. (An earlier draft of this note removed a device after five refusals; writing the test showed what that would cost.) 429, 5xx, 408 and a network error: try again next pass;
  nothing is recorded. The push service's body
  is never logged. A request has a 10 second timeout, no redirects are followed (a push endpoint that redirects is not a push endpoint), and at most 20 requests are made in one pass (a message goes to every active device or to none of them in that pass, never to some, so a duplicate is never made by the cap).
- **The rate.** At most 12 messages in a rolling hour (a "3 more" message is one), counted from `event_deliveries` rows; beyond that the rest of the pass waits for the next one.
- **Who sends.** One pass of `diya_notify.py` (the scheduled task the owner already has) does the toast first and then, only if `DIYA_PUSH=1`, the push, so there is one place that is
  "the notifier". A failure in the push never undoes or hides a toast that was shown, and a toast failure never stops the push. `python diya_push.py --status` says whether it is
  ready and why not; `--test` sends one hidden-text push to every subscription; `--public-key` prints the application server key (public).

## 6. The browser side

- `frontend/public/sw.js` is the service worker: on `push` it shows a notification from the payload (title and body only, both cut to a fixed length; anything unparseable becomes "Diya has something for you");
  on click it focuses an open Diya tab or opens `/`. It makes no network requests and keeps no data.
- The button is on the Today page ("Notify this device"): it asks the browser for permission, subscribes with the application server key from `GET /api/push/key`, and sends the result to
  `POST /api/push/subscribe`. The page says plainly what it does (a push service run by the browser's maker will be told that a notification is sent, and when; it cannot read it) and
  shows "Turn off" when this device is subscribed. All routes go through the UI's own proxy, so they need the passcode and the token like everything else.
- On an iPhone the page must be added to the home screen first, and the page says so when the browser reports no push support. This is from general knowledge and unchecked.

## 7. What is verified, and how

Tests, with a fake push service (a local HTTP server) and no network: the event list for every kind, the wording shared with the toast, the flood rule, quiet hours, once-per-date for the day;
subscription validation (every refusal above); the encryption by DECRYPTING what was made with an independent receiver written from the RFC, using the `cryptography` package's own HKDF and not this
project's (a second implementation by someone else, `http_ece`, was NOT tried: it is not installed here and nothing was downloaded to try it); the VAPID token by verifying
its signature with the public key and, where PyJWT happens to be installed, with that library too; every response status's consequence; the
rate cap; that no log line, route result or error holds an endpoint, a key or a payload; the routes (off when the switch is off; the token required); the proxy routes. Then a mutation run of the new code.

**Honest limits.** Nothing here has been sent to a real push service, shown on a real phone, or received by a real service worker: the encryption is proven against decryption written by the
same author and (outside the repo) a library, not against Google's, Mozilla's or Apple's servers, whose rules (for example about the contact in the VAPID token) can differ from the standards in
ways only a real send finds. The first real send is the owner's, on their own phone, with the text hidden.

## 8. Turning it on (the owner's steps; none of this has been run)

1. **The package.** `pip install ".[push]"` in the same Python the scheduled notifier uses (it adds `cryptography`, pinned to 45.0.5).
2. **The two settings**, in the environment of BOTH the API and the scheduled notifier task: `DIYA_PUSH=1` and `DIYA_PUSH_SUBJECT=mailto:you@example.com` (or an `https:` address you control). The subject is
   the one thing about you the push service receives; use an address you are happy to give them. Optional: `DIYA_PUSH_SHOW_TEXT=1` (the words of a reminder in the notification: a lock screen can be read),
   `DIYA_PUSH_QUIET` (default `22-07`, `off` for never), `DIYA_PUSH_DAY_AT=08:00` (the "your day is ready" message; empty for none). Whether a scheduled task sees an environment variable set after it was
   registered is not checked here: sign out and in again, or set it where the task will read it, and look at `notify_log.txt`.
3. **Restart the API** (the running one is older code and has no push routes), then open the Today page on the phone (over the VPN or the home network, with the certificate trusted) and choose
   **Notify this device**. On an iPhone, add the page to the Home Screen first and open it from there.
4. **Try it:** `python diya_push.py --test` (or "Send a test" on the page). It says nothing about you. If a device says it is paused, fix what was wrong (the contact, the clock) and send a test: a test that
   works resumes it.
5. **Turn it off:** "Turn off for this device" on the page, or unset `DIYA_PUSH`. The key file (`push_vapid.json`) and the subscriptions stay until you delete them; deleting the key file makes every
   subscribed device renew.
