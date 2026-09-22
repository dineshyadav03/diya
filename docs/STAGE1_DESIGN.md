# Stage 1: Trust -- design spec

This is a design document, not an implementation. Nothing in the codebase changes as a result of
writing it. It covers the three items `ROADMAP.md` already lists under "Auth, remaining
increments" (per-install token, Next.js proxy, `list_files` restricted to a configured root) plus
one this document adds: an outbound destination allowlist for the agent's own network-calling
tools. `ROADMAP.md`'s own later-stage numbering already uses "1" for a different milestone
(hardware and model benchmark); this document borrows "Stage 1" from the request that produced it
and does not renumber anything. All four items are currently deferred (`ROADMAP.md`, "Auth,
remaining increments") and this document does not change that -- it exists so the decision, when
it's made, is made once, on paper, with the tradeoffs visible.

Every claim about current behaviour below was checked against the code in this repo today, not
recalled from memory: file and line references point at what is actually there.

## 1. Threat model

Diya's API (`diya_web.py`) has no concept of a user account, a session, or a caller identity. Every
check it makes today is about *where a request claims to come from* (`Host`, `Origin`), never
*who is making it*. That distinction is the reason this document exists.

### Deployment A: same machine, loopback only (the default)

`diya_config.py`'s `Config.host` defaults to `"127.0.0.1"` (`diya_config.py:51`), and `main()`
refuses to start on any other interface unless `DIYA_LAN=1` is set (`check_exposure`,
`diya_config.py:203-215`). In this default deployment, **any process running under the same
Windows user account that can open a TCP connection to `127.0.0.1:8080`** can reach the full API.
Windows does not gate loopback connections by which program is asking; nothing in `diya_web.py`
does either. That includes: the user's own browser (the intended caller), any other application
the user has running, a browser extension, a script the user downloaded and ran, or malware -- all
indistinguishable from the frontend, from the server's point of view.

### Deployment B: same LAN (`DIYA_LAN=1` + `DIYA_ALLOWED_HOSTS`)

Now `config.host` is `"0.0.0.0"` (`diya_config.py:112`) and the server accepts connections from
any interface. `BoundaryMiddleware` (`diya_web.py:24-56`) still rejects a request whose `Host`
header isn't in the configured allowlist, and `CORSMiddleware` plus the same middleware's `Origin`
check still refuse a browser page from any other origin. Everything reachable in Deployment A is
now reachable from **any device on the LAN that knows the allowed host name or IP address and
sends it**. That is a lower bar than it looks:

- `docs/lan.md` step 1 has the user generate a certificate with `mkcert localhost 127.0.0.1 ::1
  <name-or-ip>` and step 3 start the API with `DIYA_ALLOWED_HOSTS=<name-or-ip>` -- **the same
  value goes into both.** A TLS certificate's Subject Alternative Names are sent to *any* client
  that completes a TLS handshake, before a single byte of the HTTP request (including the `Host`
  header `BoundaryMiddleware` checks) is even sent. Verified directly: running
  `mkcert localhost 127.0.0.1 phone.example.test` and reading the resulting certificate with
  `openssl x509 -noout -text` shows `X509v3 Subject Alternative Name: DNS:localhost,
  DNS:phone.example.test, IP Address:127.0.0.1` in the clear. **The "allowed host" value is not a
  secret to anyone who can complete a TLS handshake with the server** -- it is printed on the
  certificate the server hands out to connect at all.
- Even without that, a LAN-local IPv4 address space is small enough to scan, and the allowed name
  is often a predictable device name or the router-assigned IP itself.

So Deployment B's Host/Origin checks stop a *remote* attacker (someone not on the LAN) and stop a
same-LAN *browser* page on a different origin from riding the user's session (CSRF-style). They do
not stop a device on the LAN that decides to speak the API's language directly.

### Deployment C: LAN plus a malicious device

The device does not need to guess anything, per the finding above. It has everything Deployment B
gives an honest second device: certificate SANs disclose the allowed host name for free, and
`BoundaryMiddleware` was never designed to authenticate a caller, only to route-check one. From
here, a malicious device on the LAN is equivalent to Deployment A's malicious local process: full
reach, with only the network in between instead of the OS.

### What an unauthenticated caller can do today, across all three deployments

Every route below is reachable, right now, by anyone who satisfies the Host/Origin check --
verified by reading `diya_web.py:197-236` directly, not inferred:

- **`GET /api/threads`** (`diya_web.py:197-199`) returns every thread's ID and a preview of its
  first real message (`Store.list_threads_with_preview`, `diya_db.py`) -- the entire conversation
  index, with no pagination or filtering.
- **`GET /api/history/{thread_id}`** (`diya_web.py:201-203`) returns a thread's full message
  content by numeric ID, with **no ownership check of any kind** -- there is no "owner" concept in
  the schema at all (`diya_db.py`'s `threads`/`messages` tables have no user column). Thread IDs
  are `INTEGER PRIMARY KEY AUTOINCREMENT` (`diya_db.py`, migration 1), so they are sequential and
  trivially enumerable from 1 upward with no rate limit anywhere in `diya_web.py` or
  `diya_config.py`.
- **`POST /api/chat`** (`diya_web.py:223-236`) is the largest blast radius on the surface: it lets
  a caller impersonate the user in any thread, and it hands the message to `Agent.ask`
  (`diya.py:379-419`), which can invoke any of six tools (`diya.py:104-203`,
  `Agent._functions`, `diya.py:259-266`):
  - `list_files(directory=".")` (`diya.py:38-39`) is `os.listdir(directory)` with **no validation
    of any kind** -- an absolute path, `..` traversal, or any folder the OS process can read is
    listed on request. This is the single largest gap on the tool surface and the subject of
    section 5.
  - `add_reminder` writes directly to `diya.db` (`diya.py:313-315`) -- an unauthenticated caller
    can plant arbitrary reminders.
  - `get_weather` and `web_search` (`diya.py:56-101`) make outbound network requests on the
    server's behalf and return the result verbatim -- see section 4 for exactly where those
    requests can go.
  - `search_notes` and `list_reminders` are read-only but still gated by nothing.
- **`POST /api/transcribe`** (`diya_web.py:205-221`) accepts an audio upload up to
  `config.max_transcribe_bytes` (25,000,000 bytes by default) and runs it through Whisper
  (`diya_web.py:157-159`) -- a CPU-time sink with no auth and no rate limit; repeated large
  uploads are a real, if minor, local denial-of-service vector. Its error path
  (`diya_web.py:214-219`) also returns the raw exception string to the caller, which can include
  the server's own temp-file path (observed directly during Stage 0 testing) -- a small
  information leak, unrelated to auth but worth fixing alongside it.
- **`GET /docs`, `GET /redoc`, `GET /openapi.json`, `GET /docs/oauth2-redirect`** are enabled by
  FastAPI's own defaults the moment `FastAPI()` is constructed (`diya_web.py:173`; confirmed by
  constructing a bare `FastAPI()` and listing `app.routes`) -- verified live, not assumed. They are
  already covered by `BoundaryMiddleware` (`tests/test_boundary.py`'s
  `test_no_route_answers_to_a_foreign_host_including_the_docs` checks this explicitly) but not by
  anything else: anyone who can reach the server can read the full OpenAPI schema, including every
  request/response shape.

## 2. Endpoint inventory

None of the routes below require any authentication today. The "Auth required" column is this
document's proposal for after Stage 1 (section 3); "Justification" explains that proposed state,
not the current one.

| Route | Method | Server | Auth required | Justification |
|---|---|---|---|---|
| `/api/threads` | GET | FastAPI, `diya_web.py:197` | Yes | Lists every conversation; nothing about it is safe to leave open. |
| `/api/history/{thread_id}` | GET | FastAPI, `diya_web.py:201` | Yes | Full message content, enumerable by sequential ID. |
| `/api/chat` | POST | FastAPI, `diya_web.py:223` | Yes | Can write data (reminders, thread history) and trigger outbound network calls and filesystem listing via tools. |
| `/api/transcribe` | POST | FastAPI, `diya_web.py:205` | Yes | Consumes real CPU/model resources and writes/reads a temp file per call; no reason to leave it open to anyone who can reach the port. |
| `/docs`, `/redoc`, `/docs/oauth2-redirect` | GET | FastAPI (auto-generated) | Yes | Reveals the full request/response schema of every route above -- reconnaissance value with no offsetting benefit to a legitimate caller, who already has the source. |
| `/openapi.json` | GET | FastAPI (auto-generated) | Yes | Same schema, machine-readable; same reasoning. |
| `/files/{filename}` | GET | **Not present in this codebase today.** | Yes, if built | No such route exists; `list_files` (section 5) only returns names via `os.listdir`, never content. If a "download this file" endpoint is ever added as `list_files`'s natural companion, it must sit behind the same token *and* the same allowlisted-root-plus-secret-filter logic in section 5 -- serving file bytes is strictly more sensitive than listing file names, and must not be built without both controls already in place. |
| `/` (chat UI) | GET | Next.js, `frontend/app/page.js` | No | The page itself carries no data -- everything real loads via `/api/chat` and `/api/history/{id}`, which are gated above. An unauthenticated visitor sees an empty chat shell. |
| `/history` (chat history UI) | GET | Next.js, `frontend/app/history/page.js` | No | Same reasoning: the page fetches `/api/threads` client-side (`frontend/app/history/page.js:12`); the shell itself has nothing in it. |
| Static assets (`/diya-flame.svg`, `/icons/*.svg`) | GET | Next.js, serving `frontend/public/` | No | Five fixed, non-secret image files (verified: `frontend/public/` contains exactly `diya-flame.svg` and four icons under `icons/`). No user data ever passes through this path. |
| `/_next/static/*`, other Next.js framework routes | GET | Next.js (framework-internal) | No | Build output (JS/CSS bundles), not user data. Out of this document's scope; Next.js manages it. |

## 3. Auth design: bearer token

### The model

A single, long-lived, per-install bearer token, generated once by the server and required on
every request to every route marked "Yes" above, checked in a new ASGI middleware added the same
way `BoundaryMiddleware` and `BodyLimitMiddleware` already are (`diya_web.py:179-195`) -- as the
new outermost layer, so a request with no token is rejected before `BoundaryMiddleware` spends any
effort on it, exactly the same ordering principle already used for the body-limit check
(`diya_web.py:185-187`'s comment: "a request for the wrong Host or Origin is refused before any
effort goes into buffering its body"). A missing or wrong token returns `401`, with a
`WWW-Authenticate: Bearer` header, mirroring the existing pattern of a plain-text reason
(`diya_web.py:56`, `diya_web.py:123-125`) rather than a JSON error body -- these responses are for
a developer reading a `curl` failure, not for the UI to parse.

### Where the token lives

- **Generated** on first startup that finds no token file, inside `main()`
  (`diya_web.py:241-276`) alongside the existing `check_exposure`/`tls_files` checks -- a random,
  URL-safe value (Python's `secrets.token_urlsafe(32)`, the standard-library choice for exactly
  this).
- **Stored hashed**, matching the scope this repo already approved for auth v1 ("one per-install
  server-side token, stored hashed") and the same reasoning `diya_config.py` already applies
  elsewhere: don't keep a secret in a form that's useful if the storage is read by something else.
  A SHA-256 hash of the token goes in a new file (default `diya_token.hash`, a
  `DIYA_TOKEN_PATH`-configurable path next to `diya.db`, added to `.gitignore` alongside the
  existing personal-data entries). The *plaintext* token is printed once, to the console, at the
  moment it's generated -- the only time it exists outside the requester's own memory or password
  manager -- with a clear "save this now" message, the same tone as the existing
  "no TLS certificate found" startup message (`diya_web.py:255-257`).
- **Verified** by hashing an incoming `Authorization: Bearer <token>` header's value and comparing
  it to the stored hash with `hmac.compare_digest` (constant-time; a plain `==` on a secret
  comparison is a real, if narrow, timing side-channel and there's no reason to accept that risk
  for one extra standard-library call).

### How the UI obtains it

**The browser never holds the token.** This is the one non-negotiable constraint carried over from
the auth v1 scope this repo already agreed on ("no browser-held FastAPI secret"), and it's why the
Next.js proxy exists as its own line item, not a detail of this one. Today,
`frontend/lib/api.js`'s `apiBase()` (`frontend/lib/api.js:5-7`) points the *browser* directly at
`https://<hostname>:8080` -- every `fetch()` call in `frontend/app/page.js` (lines 76, 156) and
`frontend/components/VoiceBar.jsx` (line 126) originates in client-side JavaScript. Under this
design, those `fetch()` calls change to same-origin, relative paths (`/api/chat`, not
`https://<hostname>:8080/api/chat`), handled by new Next.js Route Handlers
(`frontend/app/api/chat/route.js` and one per proxied route -- none exist today; `frontend/app`
currently has only `page.js`, `history/page.js`, `layout.js` and `globals.css`). Each Route Handler
runs on the Next.js *server*, reads the token from its own environment (`DIYA_TOKEN`, set once when
the frontend is started, read from the same file the backend generated or configured by hand), and
attaches `Authorization: Bearer <token>` when it forwards the request to the real backend. The
browser's own request to the Next.js route carries no token and needs none -- it's same-origin,
already covered by the browser's own same-origin policy, and Next.js's dev server has no reason to
add its own Host/Origin boundary on top of that for a same-machine proxy hop.

### How `curl` and MCP clients use it

Neither goes through the Next.js proxy -- there's no browser involved, so the "browser never holds
the token" constraint doesn't apply, and going through a UI-only proxy would be a pointless extra
hop. Both attach the header directly: `curl -H "Authorization: Bearer $(cat diya_token.txt)"
https://localhost:8080/api/threads`, or the equivalent header set by any HTTP client library an
MCP server wraps. There is no MCP server wired to the live API today (`milestone2_mcp_server.py`
is a standalone Phase 1 learning exercise, unconnected to `diya_web.py`) -- this section describes
what a *future* one would need, which is exactly the same as `curl`'s case: read the token from
wherever the user put it, send it as a bearer header, nothing MCP-specific required.

### Expiry and rotation

**Recommendation: no expiry, manual rotation only.** The real option here is expiry-with-rotation
(short-lived tokens, a refresh flow) versus a single long-lived token the user can regenerate on
demand. Expiry buys real security against one specific scenario: a token that leaked once should
stop being useful. For a single-user local tool, that scenario is thin -- if a token leaks, the
thing that has it can read the token *file* just as easily as it could keep using an old token, so
short expiry doesn't remove the attacker's access, it just adds a refresh flow the Next.js proxy
and every `curl`/MCP caller would need to implement for a benefit that mostly doesn't apply here.
The cost side is concrete: a refresh flow means the browser (via the proxy) needs a way to detect
"my token just expired" and re-fetch, adding a failure mode to every request path this document
just simplified. Given that, the pragmatic choice is a token that doesn't expire on its own, plus
an explicit, cheap way to invalidate it: `python diya_web.py --rotate-token` (or
`DIYA_ROTATE_TOKEN=1` as an environment-variable equivalent, matching this repo's existing
env-var-first convention) deletes the stored hash and generates a new one on the next startup,
printed the same way as the first-run token. This is a deliberate simplification for the threat
model in section 1, not an oversight -- revisit it if Diya ever has more than one real caller
identity to distinguish between.

### Localhost exemption

**Recommendation: no exemption. The token is required even for requests from `127.0.0.1`.** The
real tradeoff: exempting loopback would let the user's own `curl` testing and the local UI work
with zero token handling at all, matching how some local dev tools behave, and it costs nothing
extra against a purely remote or LAN-based attacker, since Deployment A's local-machine boundary
would still be "whatever the OS lets connect to loopback." But Deployment A in section 1 names the
threat this would leave open explicitly: any other local process, run by the same user, already
has unrestricted reach to loopback -- that is precisely today's known gap
(`README.md`, "Known limits": "any local process can call the API"), and it's the one this whole
document exists to close. Exempting loopback would ship Stage 1 while leaving Stage 1's own
headline gap open for the deployment every real user actually runs by default. The cost of *not*
exempting it is small and one-time: the user's own `curl` needs the token too, and it's sitting in
one file for exactly that reason.

## 4. Network proxy design: outbound destination allowlist

This is about the two tools that make outbound network calls on the server's behalf --
`get_weather` and `web_search` (`diya.py:56-101`) -- not the inbound Next.js proxy in section 3.
The two tools are not equally easy to constrain, and pretending otherwise would be exactly the
kind of thing this document is supposed to avoid.

### `get_weather`: a destination allowlist is nearly free

`get_weather` calls `httpx.get` against two literal, hardcoded URLs
(`https://geocoding-api.open-meteo.com/v1/search` and `https://api.open-meteo.com/v1/forecast`,
`diya.py:59-80`). The model-controlled `location` argument is only ever passed as a query
*parameter* value (`params={"name": location, ...}`), never interpolated into the URL or the host
-- so there is no SSRF path through `get_weather` today; its destination is already fixed in
source. The design here is a thin wrapper: replace the two direct `httpx.get` calls with a small
`_fetch(url, params, timeout)` helper that checks `urllib.parse.urlsplit(url).hostname` against a
configured allowlist (default: exactly the two Open-Meteo hosts above) before delegating to
`httpx.get`. Behaviourally this changes nothing today -- the two calls already only ever hit those
two hosts -- but it means a future edit to `get_weather` that accidentally (or maliciously, via a
supply-chain compromise of this file) pointed it somewhere else would be caught at request time
instead of silently shipping.

### `web_search`: an application-layer allowlist is not feasible without replacing it

`web_search` delegates entirely to the third-party `ddgs` package's `DDGS(...).text(...)`
(`diya.py:94-101`). Verified directly (`pip show ddgs`): `ddgs` 9.16.0 depends on `click`, `lxml`,
and **`primp`** -- a Rust-based HTTP client -- not `httpx` or `requests`. Diya's own code never
constructs the request or chooses the host; `ddgs` (self-described as a "metasearch library that
aggregates results from diverse web search services") does that internally, through an HTTP
implementation this codebase does not import, cannot wrap, and cannot intercept by patching
`httpx`. A real destination allowlist for `web_search`'s traffic would need one of:

1. **Replace `ddgs` with a direct call to one fixed search API** (an HTTP call this codebase
   writes itself, going through the same `_fetch` helper as `get_weather`). This is the only
   option that gives a real, enforceable allowlist, at the cost of losing `ddgs`'s multi-backend
   fallback behaviour and likely needing an API key for a stable search provider (`ddgs`'s value is
   exactly that it doesn't need one).
2. **Constrain it at the OS or network layer** (a host firewall rule, or running the process under
   a sandboxed egress policy) -- outside this application's own code entirely, and a materially
   bigger infrastructure change than anything else in this document.
3. **Accept the gap and document it**, the same way `ROADMAP.md` already documents that Ollama
   model digests can't be pinned with the current tooling rather than faking a pin that doesn't
   hold.

**Recommendation: option 3 for now, revisit option 1 if `web_search` is ever implicated in a real
incident.** `web_search`'s job is fundamentally "reach the open web on request" -- unlike
`get_weather`, there is no fixed, small set of legitimate destinations to allowlist without
changing what the tool does. Replacing `ddgs` is a real, scoped follow-up worth doing on its own
merits (a fixed provider is also more testable than a live multi-backend metasearch call), not
something to bolt onto this document's scope. Recording the limitation honestly, the way this
repo already does elsewhere, is better than shipping an allowlist that only covers one of the two
tools it's named after and implying otherwise.

### Configuration

`DIYA_TOOL_ALLOWED_HOSTS`, a comma-separated list following the exact parsing and validation
`diya_config.py:114-127` already uses for `DIYA_ALLOWED_HOSTS` (plain host names, no scheme, port,
or wildcard) -- reusing an established, already-tested pattern rather than inventing a new one.
Default: the two Open-Meteo hosts above, so a fresh install is allowlisted correctly with no
configuration needed, matching the "every default is what used to be hard-coded" principle
`diya_config.py:1-9` already states for every other setting. **What the proxy must never reach:**
anything not on the list, including any address `diya_config.is_loopback` (`diya_config.py:177-185`)
or a private range (`10.`, `172.16-31.`, `192.168.`) would match -- the allowlist is a positive
list of external services, not a place to accidentally re-open access to the machine's own API or
another device on the LAN via a tool call.

## 5. Secret-safe `list_files` design

### Today

`list_files(directory=".")` (`diya.py:38-39`) is `os.listdir(directory)`, called with whatever
string the model puts in its tool-call arguments (`diya.py:409-413`), with no validation of any
kind -- an absolute path, a `..`-relative path, or any directory the OS process can read is listed.
This is the single item in this document with the most direct route to real harm: it needs no
special crafting, no race condition, just a model deciding (or being prompted) to call
`list_files({"directory": "C:\\Users\\<name>\\.ssh"})` and reading the response.

### Deny-by-default root

`list_files` gains a `roots` parameter, sourced from a new `DIYA_FILES_ROOTS` setting (comma-list,
same parsing pattern as `DIYA_ALLOWED_HOSTS` and the tool allowlist above), defaulting to one path:
`Documents/Diya` under the user's home directory -- the default this repo already decided on
(`ROADMAP.md`'s auth-remaining item: "The default root is a dedicated `Documents\Diya` folder, not
the repo root"). Given a requested `directory`, the function:

1. Resolves it relative to each configured root (a bare `"notes"` means `<root>/notes`; an
   absolute path is only accepted if it is already inside a root).
2. Calls `os.path.realpath` on the result (not just `os.path.normpath` -- `realpath` also resolves
   symlinks, closing the specific gap a `normpath`-only check would leave: a symlink placed inside
   an allowed root that points outside it).
3. Checks the resolved path is still equal to, or a descendant of, one configured root
   (`pathlib.Path.is_relative_to`, or the equivalent manual prefix check for the Python versions
   this repo supports).
4. Refuses (returns a string like `"Can't list '<path>': outside the allowed folders."` -- an error
   string returned to the model, matching how every other tool here reports failure
   (`diya.py:82-84`, `diya.py:97-98`, `diya.py:414-416`), never an exception that would surface a
   real filesystem path in a stack trace) if the check fails.

### What counts as a secret, even inside an allowed root

An allowed root does not mean everything in it is safe to enumerate. The listing filters out, by
default:

- **Dotfiles and dot-directories** (anything whose name starts with `.` -- `.ssh`, `.env`,
  `.git`), the same convention most shells and tools already treat as "hidden, don't show by
  default."
- **Explicit secret-shaped names**: `.env`, `.env.*`, `*.pem`, `*.key`, matching exactly the
  patterns `.gitignore` already uses for this repo's own secrets (`.gitignore`: `*.pem`, `*.key`,
  `.env`, `.env.*`) -- reusing a list this project has already had to think through once, rather
  than drafting a second one that could quietly diverge from it.

This is defense in depth, not the primary control: the root restriction is what stops
`list_files("C:\\Users\\<name>\\.ssh")` outright (it's outside every configured root); the secret
filter is what stops a stray `.env` file that ended up *inside* `Documents\Diya` itself from being
casually listed.

### Allowlist override

A user who deliberately wants Diya to see a different or additional folder sets
`DIYA_FILES_ROOTS` to a comma-separated list of paths, exactly as `DIYA_ALLOWED_HOSTS` already
takes a comma-separated list of host names (`diya_config.py:114-127`) -- one setting, explicit,
env-var-configured, never a folder path guessed or hard-coded into the code itself, matching every
other configurable boundary in this codebase.

## 6. Rollout plan

### Implementation order

Each unit lands as its own commit (or small commit sequence), matching how every Stage 0 increment
in this repo has shipped -- small, tested, reviewed individually, never bundled. Order matters here
specifically because of one dependency: the bearer token cannot default to *required* until the
Next.js proxy exists to hold it, or the live UI breaks the moment the default flips.

1. **`list_files` allowlist and secret filtering (section 5).** Fully self-contained: touches only
   `diya.py` and `diya_config.py` (a new `DIYA_FILES_ROOTS` setting, following
   `diya_config.py:114-127`'s exact pattern). No interaction with auth or the network allowlist.
   Ships first because it closes the single largest gap in section 1 with the least risk of
   breaking anything else.
2. **Outbound destination allowlist (section 4).** Also self-contained (`diya.py`,
   `diya_config.py`); the `_fetch` wrapper is behaviourally a no-op for `get_weather` on day one
   and `web_search` ships with the limitation documented, not silently unenforced.
3. **Bearer token middleware, generated but not required.** Add token generation
   (`diya_web.py`'s `main()`), storage, and the verification middleware, but gate enforcement
   behind a setting that defaults to *off* (`DIYA_REQUIRE_TOKEN`, unset by default) -- following
   the same "ship the mechanism before flipping the default" approach `diya_config.py` already used
   for `DIYA_LAN` (the setting existed and was tested before anything depended on it being on).
   This step alone changes nothing for the live UI; it exists so the token file, the hashing, and
   the 401 path can be tested against a real running server before anything depends on them.
4. **Next.js BFF proxy.** Add the Route Handlers (`frontend/app/api/*/route.js`) that hold the
   token server-side and forward to the real backend; change `frontend/lib/api.js` and every
   `fetch()` call in `frontend/app/page.js` and `frontend/components/VoiceBar.jsx` to call the new
   same-origin routes instead of `apiBase()`'s direct backend URL.
5. **Flip `DIYA_REQUIRE_TOKEN` to default on.** Only after step 4 is live and verified end to end
   -- this is the commit that actually closes Deployment A's gap from section 1. Document the
   opt-out (`DIYA_REQUIRE_TOKEN=0`) for anyone who deliberately wants the old behaviour, the same
   way `DIYA_DREAM_PROFILE_MODE=direct` documents an explicit opt into old behaviour elsewhere in
   this codebase.

### Migration impact

None of these four units touch `diya_db.py`'s schema, so the migrations system just shipped
(`diya_db.py`'s `MIGRATIONS`, `f54daad`) is unaffected -- there is nothing here for it to migrate.
The impact is entirely in configuration and one new small file (the token hash), not data:

- **A fresh install** generates a token on first run, same as it will discover a missing mkcert
  pair or a missing `DIYA_ALLOWED_HOSTS` today -- one new first-run message, not a new setup step
  that needs documentation beyond what `README.md`'s Quickstart already walks through.
- **An existing Windows user with a live `diya.db`** (this deployment, concretely: 33 threads, 143
  messages, 5 reminders as of the migrations work) is unaffected at the data layer entirely --
  threads, messages, and reminders are untouched by every unit above. The only thing that changes
  for them is: the next time their server process restarts (not automatically -- confirmed
  directly during the migrations rollout that a long-running `python diya_web.py` process does not
  pick up code changes on disk without a restart, unlike the scheduled `Diya_Dreaming` task, which
  runs as a fresh process each cycle and does), it generates a token and, once step 5 ships, starts
  requiring it. **The live UI would break at that restart if step 4 (the proxy) hasn't shipped
  first** -- this is exactly why step 5 is ordered last and gated on step 4, not a hypothetical.
  The user needs to know, once, that after upgrading past step 5 they should expect one first-run
  token message and (if they use `curl`/MCP directly) to start sending it.
- Nothing here requires deleting, backing up, or transforming `diya.db`, `user_profile.txt`, or any
  of the `dream_*`/`watcher_*` files.

### Test strategy per unit, and what each kills

Following this repo's established practice (every Stage 0 increment shipped with mutation-tested
coverage, not just passing tests): for each unit, a mutation that survives is a real gap, not a
formality.

1. **`list_files` allowlist:**
   - A request for a path outside every configured root is refused, for an absolute path *and* a
     `..`-relative one. *Kills*: the root-containment check being skipped, or checking
     `normpath` instead of `realpath` (so a `../` sequence a `normpath`-only check would resolve
     wrong still slips through).
   - A symlink inside an allowed root that points outside it is refused. *Kills*: using
     `normpath` instead of `realpath` specifically (the one mutation the previous test alone
     wouldn't catch, since a plain traversal string and a symlink escape are different code paths
     through the OS).
   - A dotfile and an `.env`-named entry inside an *allowed* directory are filtered from the
     result even though the directory itself is permitted. *Kills*: the secret filter being
     applied only to the root check and never to individual listed entries.
   - A legitimate subfolder of the configured root still lists normally. *Kills*: an
     overly-strict check that breaks the tool for its actual intended use.

2. **Outbound destination allowlist:**
   - `get_weather` against the real two hosts still succeeds (no behaviour change). *Kills*: a
     too-narrow allowlist that breaks the tool it's supposed to leave alone.
   - `_fetch` called (directly, at the unit level -- not through the model) with a URL whose host
     isn't on the list is refused before any request is sent, verified by asserting the
     underlying `httpx` call was never made (matching the precise assertion style
     `tests/test_body_limit.py` already uses to verify a rejected request never reaches the app
     underneath, not just that the response looks right). *Kills*: an allowlist that's checked but
     not enforced, or checked after the request already went out.
   - `web_search`'s limitation is asserted explicitly, not silently: a test documents that its
     traffic does not go through `_fetch` today (e.g., asserting `ddgs`/`primp` is what's actually
     imported, matching how this document verified it), so a future change that quietly makes the
     limitation worse -- or better, if `ddgs` is ever replaced -- shows up as an intentional test
     change, not a silent drift.

3. **Bearer token (generation, storage, verification):**
   - A request with no `Authorization` header, once `DIYA_REQUIRE_TOKEN` is on, gets 401.
     *Kills*: the middleware not being wired in, or wired in on the wrong side of
     `BoundaryMiddleware`.
   - A request with the *wrong* token gets 401, verified with a value that is a valid-looking
     token of the right length and character set, not just an empty or malformed one. *Kills*: a
     comparison that only checks token *shape*, not the actual hash match.
   - A request with the *right* token succeeds against every route in the inventory in section 2
     marked "Yes" -- run as one parametrized test over the whole endpoint list, the same style
     `tests/test_boundary.py`'s `test_no_route_answers_to_a_foreign_host_including_the_docs`
     already uses to check every route at once rather than one at a time. *Kills*: a route added
     later that the middleware doesn't actually cover (the middleware-ordering equivalent of a
     route someone forgets to add to a manually-maintained list).
   - The hash comparison is checked with `hmac.compare_digest`, not `==` -- verified by asserting
     the function used, not just the outcome (an outcome-only test can't distinguish the two).
     *Kills*: a correct-looking but non-constant-time comparison that a plain assertion on
     success/failure would never catch.
   - `DIYA_REQUIRE_TOKEN=0` (or unset, at the current default) means no route requires a token,
     with a test that would fail loudly the moment the default flips in step 5 -- an intentional
     tripwire, not a bug, for exactly the ordering step 5 depends on.

4. **Next.js BFF proxy:**
   - A same-origin browser request to the new Route Handler succeeds without the browser ever
     sending an `Authorization` header (checked at the network layer, e.g. via
     `frontend/tools/design-rig`'s existing stubbing approach, or a Playwright/fetch-level
     assertion that no such header left the browser context). *Kills*: a mistaken design that
     asks the browser to hold the token after all.
   - The Route Handler's own outbound call to the real backend does carry the correct
     `Authorization` header. *Kills*: a proxy that forwards the request but forgets to attach the
     token, which would only be caught by an end-to-end check, not a browser-side one.
   - `frontend/tools/next-tls.mjs`'s existing loopback-vs-LAN test coverage
     (`tests/test_frontend_launcher.py`) is extended to confirm the LAN launch mode still starts
     correctly with the proxy in place -- *kills* a proxy implementation that accidentally
     hard-codes `localhost` instead of following `apiBase()`'s existing hostname-derived pattern
     (`frontend/lib/api.js:5-7`), which would silently break exactly the iPhone/LAN workflow
     `docs/lan.md` documents.
