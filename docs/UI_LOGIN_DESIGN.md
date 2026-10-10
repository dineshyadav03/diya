# A login for the UI (audit finding F1)

`docs/AUDIT_2026-10-10.md` F1: the UI's server forwards every call to the API and adds the API's access token itself
(`frontend/lib/proxy.mjs`), so the token protects nothing against anyone who can reach the UI. On this computer that is only you.
With `npm run dev:lan` the UI listens on every interface, and anyone on the same network who can open port 3000 (and click through the
certificate warning) could read your chats, edit memory and approve an action as you. This note says what is added, what it does not
cover, and how it is checked. Nothing here changes the API.

## Decisions

**D1. A passcode you choose, in the UI's own environment.** `DIYA_UI_PASSCODE`, set where `DIYA_TOKEN` already goes: the terminal that
starts the UI, or `frontend/.env.local` (gitignored). Unset, the UI behaves as before: loopback only, no login. That default is
deliberate: on loopback the only callers are programs already running as you.

**D2. LAN mode needs it.** `npm run dev:lan` refuses to start without a passcode of at least 12 characters. A weak or missing one is the
whole problem this fixes, so it is a refusal, not a warning. Outside LAN mode a passcode shorter than 12 only warns.

**D3. A signed session cookie, not a password on every request.** Signing in with the right passcode sets `diya_session`: an expiry time
and an HMAC-SHA256 of it. The key is derived from the passcode, so nothing else needs storing and *changing the passcode ends every
session*. 30 days. `HttpOnly` (no script can read it), `SameSite=Strict` (a page on another site cannot make the browser send it), `Secure`
whenever the connection is HTTPS, `Path=/`. The cookie is never forwarded to the API (the proxy already drops every browser header but the
content type).

**D4. Everything is behind it except the way in.** A `middleware.js` runs before every page and every route. Public: `/login`, `/session`
(sign in, sign out, ask whether signed in), and the framework's static files and images. Everything else, including the `/api/*` routes
and the development server's own endpoints, needs the cookie. A page request without one is redirected to `/login?next=...`; an `/api/*`
call gets a `511` with a JSON body (a status nothing else here uses, so the pages can say "sign in again" and not "token wrong").

**D5. Guessing is slowed, whoever is guessing.** The passcode is compared in constant time (both sides hashed first). A wrong one waits
0.4 s before the answer. After 5 wrong ones in a row the sign-in is locked for 5 minutes, doubling at each further lock up to an hour;
a right one resets it. The count is **global**, not per address, because the caller's address is whatever a header says it is and cannot
be trusted. The cost: someone can lock you out. The way back is to wait or to restart the UI (the counter lives in the server's memory).

**D6. A forged request from another site is refused twice.** `SameSite=Strict` is the first; the second is that any request that changes
something (not GET or HEAD) and carries an `Origin` header must have the same host as the request itself, else `403`.

**D7. The way out.** A "Sign out" button at the foot of the sidebar (only when a passcode is set and you are signed in) clears the cookie.

## What this does not do

- It does not protect a loopback-only UI from other programs on the same computer (they could already read the database).
- It does not make plain HTTP safe: it is meant to be used over the HTTPS the launcher already provides, where the passcode and the
  cookie are encrypted in transit.
- `dev:lan` runs Next.js's *development* server. The middleware covers its endpoints too, but a production build served over HTTPS by a
  small server of our own would be a smaller thing to expose. That is a separate piece of work.
- The passcode sits in a plain file, like `DIYA_TOKEN` does; anyone who can read `frontend/.env.local` has it.
- One person, one passcode: no accounts, no per-device sign-in list.
- The lock-out counter is in memory, so it resets when the UI restarts.

## How it is checked

- The decisions are pure functions in `frontend/server/ui-login.mjs`, run under plain Node by the tests: passcode check, session
  make/verify (tampering, expiry, a different passcode), the redirect target (no open redirect), the guard for every kind of request, the
  sign-in/out handler with its delay and lock-out (time and sleep are passed in), the launcher's refusal.
- The wiring (`middleware.js`, `app/session/route.js`, the login page, the sidebar button) is checked from its source, as the pages'
  failure handling is, and by using the real UI in a browser against a scratch API, scratch data and scratch ports.
- Mutation testing of the new modules, as for every unit.
