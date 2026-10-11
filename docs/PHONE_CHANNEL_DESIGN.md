# A phone channel: design spec (nothing here is built; every step needs the owner's yes)

> **Status (2026-10-11):** designed only. It is the "reach" item of the daily-driver list (`ROADMAP.md`, item 6, point 3; `docs/SCHEDULE_DESIGN.md` D9).
> It is the biggest gap for daily use (`RESEARCH.md` entry 16: every comparable product lives in the chat apps people already open) and the
> one that most needs the security rules of entry 17 first. This document says what "a phone channel" can mean, which rules it must keep, what each
> choice costs, and what has to be decided before anything is written. Facts about outside services below are from general knowledge, not checked
> against today's documentation: **each one is to be checked before it is relied on.**

## 1. Where things stand

The UI already works on a phone on the same Wi-Fi: `npm run dev:lan`, the certificate trusted on the phone, a passcode (`docs/lan.md`,
`docs/UI_LOGIN_DESIGN.md`). What is missing is not the page, it is three separate things that "a phone channel" tends to mean at once:

| | What it is | Today |
|---|---|---|
| **A. Reach** | opening Diya from the phone when away from home Wi-Fi | not possible: the UI listens on the home network only |
| **B. Tell** | Diya reaches the phone first: a reminder is due, a question is waiting, an action needs approval | the Windows toast (`diya_notify.py`, scheduled by the owner) reaches the computer only |
| **C. Talk** | the owner writes to Diya from a chat app and Diya answers there | not possible |

They are different risks and can be built, or refused, one at a time.

## 2. The rules any channel must keep

These are fixed before any option is weighed; an option that cannot keep one is out.

1. **A message is the owner's only if it comes from the paired owner.** Everything else is dropped without an answer. This is D2 of
   `docs/AUTO_MEMORY_DESIGN.md` carried to the phone: with memory that remembers on its own, a message from the wrong sender would become a
   fact. A channel never makes an unpaired sender's text a "user" message in the database.
2. **Approvals are never given by chat.** A proposed action (`docs/ACTIONS_DESIGN.md`) can be announced ("2 actions wait for you") and
   never approved, rejected or edited from a channel. Approval stays in the UI, behind the passcode, on the exact arguments.
3. **The channel runs the same code as the UI's chat.** One path (`Agent.ask`, the same gates for reminders, tasks and tools), not a second,
   looser one. Nothing a channel adds can call a tool the chat cannot.
4. **Rule of Two** (`RESEARCH.md` entry 17): an inbound channel is untrusted input; so while it is on, nothing it can trigger may both read private
   data and send something out without the person approving. Replies to the paired owner are the one allowed outward path.
5. **What leaves the computer is the minimum**, chosen by the owner and off by default: a notification says "A reminder is due" and not what it
   is, as the Windows notifier already can (`DIYA_NOTIFY_SHOW_TEXT=0`).
6. **It is switched off by default and by one setting**, and a channel that fails closed (a token that does not verify, an unknown sender) says
   nothing rather than guessing.
7. **No file, link or attachment from a channel is fetched, opened or stored.** Text only, a fixed length limit.

## 3. The options

| Option | A | B | C | What leaves the computer | What it needs | Main risk |
|---|---|---|---|---|---|---|
| **VPN to the home computer** (a WireGuard-based one such as Tailscale, or a router's own) | yes | no | via the UI | nothing but VPN traffic; with Tailscale the coordination service learns that the devices exist | the VPN on both ends; the UI already works over it | the UI becomes reachable from every device on that VPN: the passcode is the only gate (it is built for exactly that) |
| **Web Push from the API** (the phone's browser gets a push through the browser vendor's push service) | no | yes | no | the push payload is encrypted for the phone (RFC 8291); the vendor's push service still sees that a push was sent, when, and to which subscription | the UI served over a certificate the phone trusts (already needed for LAN mode), a service worker, a VAPID key pair, a stored subscription; on iPhone the page must be added to the home screen | metadata, and a subscription that outlives the person who made it |
| **ntfy** (a small push service: publish by HTTP, subscribe in an app) | no | yes | no | the text, to the ntfy server: **self-hosted** only if it should stay private, and then it must be reachable from the phone (see VPN) | a server and the app | text visible to whoever runs the server; unauthenticated topics are public |
| **A Telegram bot** (long polling, so no inbound port) | no | yes | yes | every message in both directions, readable by Telegram (bot chats are not end-to-end encrypted) | a bot token from BotFather, the owner's own Telegram account | the content is no longer local; a stolen Telegram account is a stolen channel |
| **WhatsApp, iMessage, Signal** | | | | | no official, practical bot interface for a personal assistant (WhatsApp's is for businesses and needs an approved account; iMessage needs a Mac and unsupported tricks; Signal has none): **check before dismissing** | |
| **A self-hosted Matrix server** | no | yes | yes | stays with you if the server is yours | running a server | the most work for the least benefit |

## 4. Recommendation: three steps, each stopping on its own

1. **A (no code).** Write down how to reach the UI over a VPN, and what the passcode protects and does not (it does not make plain HTTP
   safe; the VPN is the encryption). Nothing is built. The owner decides whether to install a VPN.
2. **B, one-way, content-light.** Web Push, for four things only: a reminder is due, a question is waiting (`docs/AUTO_MEMORY_DESIGN.md` D5), an
   action is waiting for approval, and "your day" at a time the owner chooses. The text defaults to "Diya has something for you" and never
   carries memory; opening it opens the UI (behind the passcode). It is the same four events the Windows notifier knows, sent from the same place,
   so there is one list of "what is worth interrupting for". Its rate is capped (the pacing rules of D5) and it is off at night.
3. **C only if the owner accepts that the words pass through a third party.** The design is written here so the choice is informed, and not built
   until asked for:
   - *Pairing:* the owner starts it from the UI, which shows a one-time code (random, six words or 12 characters, valid ten minutes, single use,
     compared in constant time). The owner sends the code to the bot from their own account; the bot records that account's numeric id and answers
     nobody else. A second pairing needs the UI again, and unpairing is a button.
   - *Everything else is dropped:* an unknown id, a group, a forwarded message, a reply to someone else, an edited message, a non-text message.
   - *A message from the paired owner* is added to a thread named for the channel and answered by the same `Agent.ask` as the chat's. A fixed
     reply (never the exception text) is sent when it fails.
   - *No approvals, no commands that change settings, no links or files (rules 2 and 7)*; a message that asks for one is answered with where to do it.
   - *Live memory capture (unit A4)* treats the message like any chat message because it is stored like one; the pairing is what makes that safe.
   - *Rate limits:* at most 30 messages an hour from the owner; a burst is answered once.

## 5. What would be built, in order, behind one switch each

| Unit | What | Verified by |
|---|---|---|
| P1 | `docs/lan.md` gains the VPN section (step 1); no code | read by the owner |
| P2 | `diya_push.py`: the one list of events worth interrupting for, the text rules, the rate and quiet-hour limits; a subscription table (migration); the routes to subscribe and unsubscribe; the service worker in the UI; `DIYA_PUSH=1` | unit tests with a fake push service; mutation tests; the real thing tried on the owner's own phone with the content hidden |
| P3 | the Windows notifier and the push read the same event list, so one rule decides both | tests that the same event gives the same decision |
| P4 (only on a yes) | `diya_telegram.py`: pairing, long polling, the drop rules, the reply path, the limits | a scripted fake of Telegram's API for every drop rule and the pairing; a mutation run; nothing run against the real service without the owner present |

Each unit gets a design note of its own before it is built, as every earlier unit did, and is measured before it is called done.

## 6. What needs the owner's yes

- **Whether to do A, B, C at all, and in what order.** The recommendation is A, then B, and C only if asked.
- **Whether a VPN is acceptable** (Tailscale needs an account with an identity provider; a router's own VPN needs none).
- **Whether what Diya says may pass through a third party.** B can keep it to "something is waiting". C cannot: the words go through the chat service.
- **The text default for B** (hidden is recommended).
- **For C: which service**, and the owner's own account on it. Nothing is created in anyone's name without the owner doing it.

## 7. What this does not do

It does not give the phone more power than the UI has, does not let anyone but the paired owner talk to Diya, does not approve anything by
message, does not send memory to a third party unasked, and does not open the computer to the internet: every option above only makes outbound
calls or rides a VPN. It does not make a stolen unlocked phone safe: whoever holds that phone is the owner as far as the passcode and the pairing
can tell, and unpairing is the answer.
