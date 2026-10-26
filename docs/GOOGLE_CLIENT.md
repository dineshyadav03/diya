# One careful client for Google (DIYA-067, DIYA-069, DIYA-054; 2026-10-26)

The first five Google cards each grew their own request code. Everything built after them goes through `diya_google_client.py`, so what is true of one is true of all.

| | What it does | Proof |
|---|---|---|
| **Typed outcomes** | A read returns what Google said as a dict, or raises `GoogleError` with a `kind` (`not_connected`, `signed_out`, `scope`, `api_disabled`, `not_found`, `conflict`, `rate_limited`, `server`, `network`, `limit`, `bad_request`) and words safe to show. Google's own reason for a refusal ("API not enabled", "insufficient scopes") is turned into what to do about it. A change returns the response, or raises `ActionFailed` (nothing was done) or `ActionUncertain` (it may have been), like every other action. | `tests/test_google_client.py` |
| **Bounded** | Every request has a timeout (15 s). A list asks for a page size and follows `nextPageToken` for at most a few pages, and says that it stopped. A **read** refused for being busy (429, or a 403 that says so) or failing on Google's side (500 to 504) is tried again at most twice, waits what Google asked but never more than 8 s. A network failure is the same. A **change** is never tried again: whether it reached Google is not known, and asking twice could do it twice. | same, and `tests/test_google_client_structure.py` (the one function that changes anything has no retry) |
| **Counted** | Every request is counted for the day (`app_state`). Past `DIYA_GOOGLE_DAILY_REQUESTS` (default 5000, 0 for no limit) nothing more is sent until tomorrow and the answer says so, so a runaway loop cannot spend the quota of the owner's Google project. | same |
| **Allowlisted** | A request is made only with a method and to an address the card was given (`allow`), over https, to one of Google's own hosts, with no query string, user or fragment in the address string (parameters travel separately). Anything else is refused before a token is fetched. | same |
| **One place that changes things** | `send` is the only function that makes a changing request in any newer Google module; it is called only from the functions a kind runs after the owner approved (`*_execute`). | `tests/test_google_client_structure.py`, `tests/test_catalog.py` (the module is named in `OUTBOUND_WRITERS`) |

**Not covered by it (the first five cards keep their own code):** Calendar reading, the first four additions, Gmail reading. Their behaviour is the same in kind and is tested in `tests/test_google_fault_matrix.py`. Moving them onto this client would change working code for no new behaviour.

**What it does not do:** it does not queue work while the network is down (DIYA-145): a change that could not be sent is `failed`, and a proposal waits for the owner to try again; nothing is retried behind their back.
