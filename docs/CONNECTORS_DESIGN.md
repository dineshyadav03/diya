# Connectors and permissions -- design spec

> **Status (2026-09-28):** designed; **C1, C2 (Home Assistant, Notion, Todoist) and C3 (Google
> Calendar) all built and mutation-tested.** C3 is code-complete but **not verified against the real
> Google endpoints** -- it needs an OAuth client id/secret the owner registers themselves (Diya cannot
> create one). Stage 3 of `ROADMAP.md`'s later stages --
> the first stage that reaches outside this one machine's own files and the model. Landscape research
> is `RESEARCH.md` entry 11. Stage 4 (Muse/Instinct-style approval gates, action trails, a
> prompt-injection boundary) is a separate, later document by the owner's own decision (2026-09-28):
> it waited until a connector existed to prove itself against, rather than being designed in the
> abstract first. That document now exists: `docs/ACTIONS_DESIGN.md` (2026-10-04).

## 1. What is true today

Diya already calls out to the world in exactly two ways: `get_weather` (Open-Meteo, no account, no
write access, an outbound host allowlist) and `web_search` (DuckDuckGo via `ddgs`, same shape). Both
are read-only, need no credential Diya stores, and were built inside Stage 0's own security work
(`diya._fetch`'s allowlist). `list_files` and `search_notes` reach this machine's own filesystem, not
the outside world. Nothing today holds a token for an account that belongs to a real person, and
nothing today writes to a service outside Diya's own database.

## 2. What "a connector" means here

A connector is a tool, in exactly the same sense `get_weather` already is one -- a function `diya.py`
can put in `TOOLS` and the model can call -- except it authenticates as a real account the owner owns,
and (for some connectors) can change something outside Diya, not just read it. That second property is
new, and it is where every risk in this document comes from.

## 3. Decisions

### D1. Credentials never live in the database or in git

**Recommendation: each connector's token lives in its own local file, the same way `diya_token.hash`
does** -- a path from config (`DIYA_<NAME>_TOKEN_PATH`, a sensible default in the working directory),
gitignored, read at call time, never logged, never returned by any API route or printed by any CLI
command. An OAuth connector (Calendar, Gmail, Outlook) stores a refresh token this way; a static-token
connector (Home Assistant, Notion, Todoist) stores that token the same way. This is not new invention:
it is the same discipline `diya_web.py`'s `ensure_token`/`read_token_hash` already established for the
API's own access token, applied to a token that happens to belong to Google or Microsoft instead of
Diya itself.

### D2. Read before write, per connector, explicitly

**Recommendation: a connector's first version is read-only, whatever the underlying API can do.**
Write access (creating a calendar event, sending an email, changing a Home Assistant entity's state)
is a separate, later decision per connector, made once the read-only version has been used for real --
not assumed just because the API supports it. This is the concrete lesson from Instinct's launch
failure (RESEARCH.md entry 2: an unapproved email sent on the user's behalf) applied at the cheapest
possible point: never build the capability to take an action silently in the first place, rather than
build it and then gate it. It also keeps Stage 3 out of Stage 4's territory: an approval-gate system
is only needed once there is a *write* to gate.

### D3. Every connector call is logged, plainly, before Stage 4 exists

**Recommendation: a connector call writes one line to a plain log (what was called, when, which
account/instance, success or failure) the moment it runs** -- not the richer "action trail with
receipts" Stage 4 will design, just enough that the owner can always answer "what did Diya do with
this connector today" without trusting the model's own account of it. This is the same principle
`dream_log.txt` already applies to Dreaming's own extraction cycle, extended to the first kind of tool
call that reaches a real account. It is deliberately minimal: the full authority model, approval gates
and prompt-injection boundary are Stage 4's job, once a real connector exists to design them against.

### D4. A connector is opt-in by configuration, not by code branching

**Recommendation: a connector's tool is only added to `TOOLS` if its configuration is present** (a
token file exists and reads as valid), the same way `list_files` already refuses everything if no
`DIYA_FILES_ROOTS` is configured. An unconfigured connector is invisible to the model, not a tool that
exists and fails -- so adding four connectors to the codebase does not mean the model suddenly has four
new ways to fail for an owner who set up only one of them.

### D5. Every connector is a menu item, not a personal integration (revised 2026-09-28)

**Superseded same day.** The first draft of this section assumed Diya would be wired to the owner's own
accounts specifically, and asked which one to pick. The owner corrected this: Diya's connectors are
options *any* owner of a Diya install sees and chooses from -- "we will have the same options given to
the user and he will select" -- not something wired to one specific person's accounts at build time.
**Recommendation: build all of D1-D4's supported connector types as equally-available options behind
one settings surface (D6), each starting disconnected, so whoever is running this installation decides
for themselves which ones to turn on.** This does not change D1-D4 at all -- they were already
connector-agnostic -- it only changes what "done" means: not "Diya is connected to the owner's Google
account" but "Diya can offer a Google Calendar connection to whoever owns this install, the same way it
can offer Home Assistant or Notion." Still one owner per running Diya (one database, one set of stored
tokens): this is not multi-tenancy, it is not hardcoding one owner's specific service in the code.

### D6. A Connections page, the same shape as Memory and Reminders

**Recommendation: a new page (`frontend/app/connections`, `/api/connections`) lists every connector
type D1-D4 support, each as a card: name, one line of what it does, and its current state (not
connected, or connected since &lt;date&gt;) with a Connect/Disconnect action.** A static-token connector's
"Connect" is a form (paste the token, Diya checks it works before saving). Disconnecting deletes
the local token file (D1) and nothing else -- no data the connector ever fetched is retroactively
undone, matching how retiring a fact never deletes its history. This is the same page-per-feature
pattern the UI already has (Memory review, Reminders); a connector with no owner-provided credentials
shows as "not connected" and offers nothing to the model (D4), exactly like today.

**Revised for unit C3.** The original wording above described an OAuth connector's Connect as "a real
browser redirect through that provider's own login, ending back on this page" -- language borrowed
from how a *web app*'s OAuth flow works, where the server and the browser are different machines and
the provider has to hand control back to a page. Diya is not that: the browser and the server are the
same machine, so there is no separate page to return to. What C3 actually builds instead (RFC 8252,
"OAuth 2.0 for Native Apps" -- the pattern every major identity provider, including Google, recommends
for exactly this shape of app): clicking Connect makes one request that opens the owner's own browser
to the provider's consent screen and blocks -- the button just waits, the way it already does for a
token-kind Connect, only longer -- while a temporary local server on an OS-assigned loopback port
catches the redirect back. Nothing here needed the page itself to change shape.

*As built (C1):* `diya_connectors.Connector` (name, label, description, `auth_kind`, `implemented`,
an optional `validate` callable) is a frozen dataclass that refuses a malformed name or a token-kind
connector marked `implemented` with no validator, at construction time. `CONNECTORS` -- the real
registry -- is an empty tuple, deliberately: nothing here is a working connector yet, only the shape
one takes. `Memory.connect()`/`disconnect()`/`status()` and the per-connector token file
(`<connector_tokens_dir>/<name>.token`, gitignored, atomic write-then-rename like `diya_token.hash`)
and the plain call log (`connectors_log.txt`) are all keyed off two new `Config` fields
(`connector_tokens_dir`, `connectors_log_path`) rather than D1's original one-env-var-per-connector
idea -- simpler, and it does not grow the config schema every time a connector is added.
`diya_web.create_app()` gained a `connectors=` parameter (defaulting to the real registry) the same
way it already takes a fake model client or a temp database, so the routes can be proven against
fakes without a real connector existing -- `tests/test_connectors.py` and `tests/test_connections_api.py`
never touch the real (empty) registry except to pin down that it is, in fact, still empty.

Connect and disconnect are two separate routes (`POST /api/connections/{name}/connect`,
`.../disconnect`), not one shared `{action}` route like Memory's: a connect body carries a token and a
disconnect needs none, so the split avoids an artificial third "no body" case on a single handler.
Disconnecting is idempotent by design (removing something already gone is not an error) -- a real,
disclosed difference from the stricter accept/reject state machine elsewhere in this project, chosen
because a connector's own live state (connected or not) is simpler than a fact's multi-step review
history.

17/17 mutations caught (`diya_connectors.py`, `diya_connections_api.py`, `diya_web.py`, scratch
`mutate_c1.py`); two real gaps on the first run, both fixed with a new test rather than a shrug: a
mutation that left stray whitespace in a stored token file survived because `read_token()` also
strips on read (masking a write-side bug), and a mutation that mislabelled a real disconnect as "was
not connected" in the log survived because the original test only checked for a substring that the
mutated, longer line still happened to contain. Live-checked in a real browser (a scratch server
registering three fake connectors -- two token-kind, one unimplemented oauth-kind, mirroring the real
candidates from RESEARCH.md entry 11): a wrong token shows the connector's own rejection reason, the
right token connects and the card updates immediately, and disconnecting returns it to "not
connected" -- all without a page reload.

*As built (C2):* `diya_connector_tools.py` -- one validator and one read-only tool per connector, all
through `httpx` with a 5-second timeout, `get_weather`'s own pattern. Home Assistant needed a config
field of its own (`DIYA_HOME_ASSISTANT_URL`): unlike Notion and Todoist, which have one fixed API
address, a self-hosted instance's address isn't a secret, so it is a plain setting the owner sets once
(the same way `DIYA_OLLAMA_URL` already works), not something typed into the Connect form alongside
the token. Each tool reads its connector's *current* token from storage on every call rather than once
at Agent construction, so a disconnect (or reconnect) takes effect on the very next message, never a
restart. `Agent.tools` became a property, computed fresh each call, that adds a connector's tool spec
only while it is actually connected (D4); the three tool functions are always registered in
`Agent._functions` (each checks its own connection and answers "not connected" if asked to run
anyway), so nothing needs rebuilding when a connection changes, only the list the model is shown.

Measured against the real model (`qwen2.5:3b`, tokens faked so no real account was needed): asked
about Todoist, Notion and Home Assistant with all three "connected", it called the right tool every
time (`list_todoist_tasks`, `search_notion`, `search_home_assistant`) and correctly called none of
them for an unrelated weather question. Each underlying call was refused for real by the real service
(a fake token got a genuine 401 from Notion and Todoist's live API; Home Assistant's address pointed
nowhere) -- every failure was reported back in one plain sentence, never a crash. One quirk, not a
safety problem: on Todoist's 401 the model told the person "Todoist's API is no longer supported",
which is its own guess at *why*, not something the tool said -- recorded, not fixed, the same
disclosure standard as M2's `[User]` tag finding.

15/15 mutations caught (`diya_connector_tools.py`, `diya.py`, scratch `mutate_c2.py`); one real gap on
the first run (a match-count cap with no test case ever producing more matches than the cap allowed)
fixed with a new test.

**Found later, and fixed (2026-10-04, `docs/ACTIONS_DESIGN.md` D11):** the Todoist half of C2 was built on
Todoist's REST v2 (`/rest/v2/...`). When measured on 2026-09-28 the real service still answered it (a real 401
for a fake token); by 2026-10-04 it answered **410 Gone** ("This endpoint is deprecated... rely on the new API
endpoints, available under /api/v1/ prefixes"), so the connector could not connect to a real account at all --
its validator saw a 410 for every token, which is not a 401 and was reported as "Todoist answered with HTTP
410". Nothing caught it because every test fakes the network and the 2026-09-28 measurement was a real call
that had not yet started failing: **a connector measured once is not a connector that keeps working**. It now
uses API v1 (`/api/v1/projects` to validate, `/api/v1/tasks` and `/api/v1/tasks/filter?query=` to list, both
paginated as `{"results": [...], "next_cursor"}`), checked against the real service the same way: a fake token
is refused as a rejected token, and every path it uses answers 401 where a made-up one answers 404.

*As built (C3):* `diya_google_calendar.py`. `connect(config)` is the whole RFC 8252 flow in one call:
start a loopback `http.server` on an OS-assigned port, open the owner's browser to Google's consent
screen (`access_type=offline`, `prompt=consent` -- without it a *returning* owner is not reliably
issued a refresh token at all, only an access token), block until the redirect lands, check its
`state` against the one this call generated (refusing a mismatched or missing one, not just a missing
code), exchange the code at Google's token endpoint, and store the refresh token through
`diya_connectors.store_token` -- a new, small addition to `diya_connectors.py` (D1's storage, without
D6's "validate a pasted token" step, since a successful exchange already proves it). `Connector` gained
an `oauth_connect` field alongside `validate`, checked the same way at construction time (an
implemented oauth-kind connector needs one, exactly as a token-kind one needs a validator).
`diya_connections_api.py`'s single `connect` route now dispatches on `auth_kind` rather than assuming
a pasted token; sending a token body to an oauth-kind connector is simply unused, not refused --
harmless, since the real UI never does it, and enforcing that shape strictly bought nothing.

`list_calendar_events` re-exchanges the stored refresh token for a fresh access token on every call
(access tokens last one hour; nothing here ever caches one) and treats a refresh failure the same as
"not connected", since there is nothing a mid-conversation tool answer can do about a revoked
connection beyond saying so.

Tested without a browser or a real Google account anywhere: `_wait_for_redirect`'s loopback server is
real (a genuine socket on 127.0.0.1), driven by a test-side HTTP client standing in for "the owner
clicking through consent" the moment `connect()` hands it the URL it built; every Google network call
(`httpx.post`/`.get`) is faked. 16/16 mutations caught. **Not verified against the real Google
endpoints**, because that needs a real OAuth client -- see "what needs the owner's yes" below; this is
the one part of Stage 3 still resting on RFC 8252's documented behavior and Google's own docs rather
than a live measurement, disclosed rather than quietly assumed solid.

## 4. The candidates, ranked by cost (detail and sources: RESEARCH.md entry 11)

| Connector | Auth | Ongoing cost | Write access | Fit |
|---|---|---|---|---|
| Home Assistant | one local long-lived token | none | yes, if wanted | best match for "local, inspectable" -- only if the owner runs an instance |
| Notion | one internal-integration token | none | yes, if wanted | simplest real OAuth-free option, if notes live there |
| Todoist | one personal API token | none | yes, if wanted | same shape as Notion, for tasks |
| Google Calendar | OAuth, Testing mode | free; weekly re-auth click unless later published | yes, if wanted | free, real, the most-requested category |
| Microsoft Graph (Outlook) | OAuth, Azure app registration | free; same publishing trade-off | yes, if wanted | alternative to Google, or both |
| Gmail | OAuth, Testing mode | free; weekly re-auth; annual paid review only if ever published | yes, if wanted | same trade-off as Calendar, higher stakes if it can write |
| Spotify | OAuth, Development Mode | free (owner needs Premium) | playback control | fine for exactly one user |
| WhatsApp | none clean | -- | -- | official API does not fit a personal number; unofficial libraries carry ban risk -- needs the owner's explicit yes, not a default |
| iMessage | -- | -- | -- | not reachable from Windows at all |

## 5. Units

| Unit | What | Files |
|---|---|---|
| C1 | **Plumbing.** A `Connector` registry (name, description, config check, connect/disconnect,
whether it is currently usable); the per-connector token-file helper (D1); the plain call log (D3);
`GET/POST /api/connections`; the Connections page (D6) listing every registered type. No real
connector yet -- everything shows "not connected", the same way a fresh Memory page shows nothing
waiting. Built. | `diya_connectors.py` (new), `diya_connections_api.py` (new), `frontend/app/connections` |
| C2 | **The three no-OAuth connectors.** Home Assistant, Notion, Todoist: each a paste-a-token Connect
form (C1's static-token path), one read-only tool each (`diya.py`'s `TOOLS`), tested against fakes the
way `get_weather` is (`tests/fakes.py`-style, never a real account in a test). Buildable and fully
testable without any OAuth registration. Built. | `diya_connector_tools.py` (new), `diya.py`,
`diya_web.py` |
| C3 | **An OAuth connector.** Google Calendar (RFC 8252's loopback-redirect flow, D6 revised), a
refresh-token store, one read-only tool. Needs an OAuth client id/secret registered once against a
real Google Cloud project -- the owner's own account, since Diya cannot create one -- committed
nowhere (D1), read from config like everything else. Code built and mutation-tested; **not verified
against the real Google endpoints**, since that needs the owner's own client id/secret. Gmail and
Microsoft Graph follow the same shape once this one is proven for real.
| `diya_google_calendar.py` (new), `diya_connectors.py`, `diya_connections_api.py`, `diya_connector_tools.py` |
| C4+ | Further connectors (Spotify; WhatsApp only with the owner's explicit yes, D2/RESEARCH.md entry
11's ban-risk caveat) as wanted, each a small addition to C1's registry, not a new design. |

Order matters: C1 before anything, the same reason M1 came before M2/M3 in person-tagged memory --
there is nowhere to plug a connector in without it. C2 before C3 because it proves the whole page and
registry end to end (connect, use a tool, disconnect) without the added cost of an OAuth round trip or
a real developer-console registration, so any bug in the shared plumbing is found on the cheap path
first.

## 6. What needs the owner's yes

- Whether any connector gets write access at all yet, or every connector stays read-only until Stage 4's
  approval-gate design exists (D2 defaults to read-only either way; this is about the ceiling, not the
  starting point).
- For WhatsApp specifically: whether an unofficial, session-based library is acceptable at all, given
  the real account-ban risk against Meta's terms (RESEARCH.md entry 11) -- this is not a default yes.
- C3's OAuth client registration needs a real Google Cloud project under an account the owner
  controls (Diya cannot create one): a Google Cloud project, the Calendar API enabled, an OAuth
  consent screen (External, the owner added as a test user -- keeps it in free "Testing" mode), and
  an OAuth client of type "Desktop app" (the only type Google gives RFC 8252's arbitrary-loopback-port
  exception to). `DIYA_GOOGLE_CLIENT_ID` and `DIYA_GOOGLE_CLIENT_SECRET` are the two values that come
  out of that -- until they're set, Connect just says so.
