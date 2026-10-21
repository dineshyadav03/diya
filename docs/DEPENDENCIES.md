# Dependencies: how they are pinned, scanned and licensed (2026-10-21; task DIYA-213)

## How versions are kept the same

| Part | Where | What is exact |
|---|---|---|
| Python, the packages Diya imports | `pyproject.toml` | every one pinned with `==` (the `dev`, `push` and `dossier` extras too) |
| Python, everything those pull in | `requirements.lock` | made by `uv pip compile pyproject.toml --extra dev -o requirements.lock --generate-hashes`: every package pinned and every file hashed, so an install from it gets exactly those files or fails |
| The web UI | `frontend/package.json` + `frontend/package-lock.json` | CI installs with `npm ci`, which refuses to run if the two disagree |

`tests/test_dependencies.py` fails if a pin is loose, if a pin in `pyproject.toml` and `requirements.lock` disagree, if a lock entry has no hash, or if the web UI's lock does not satisfy `package.json`.

## What is scanned, and when

CI (`.github/workflows/ci.yml`) runs two scans on every push:

* **`pip-audit`** (Python Packaging Authority) on what was just installed. It fails the build on any known advisory that is not in the table below.
* **`npm audit --audit-level=high`** on the web UI's lock. It fails the build on any high or critical advisory.

Neither can look at code Diya wrote; they look up the versions of other people's packages in public advisory lists, so a package that is vulnerable but not yet reported is not found. The scans need the network, so a CI run can fail because an advisory service was unreachable: run it again.

## What the first scan found (2026-10-21) and what was done

| Where | Found | Done |
|---|---|---|
| `python-multipart` 0.0.20 (a direct dependency: file uploads such as the microphone) | 12 advisories, among them denial of service when parsing crafted multipart requests; fixed by 0.0.31 | pinned to 0.0.31 in `pyproject.toml` and the lock; the web, upload, token and proxy tests pass with it |
| `cryptography` 45.0.5 (the optional `push` extra: Web Push's key agreement, signing and encryption; found by the first CI run, not by the local scan, because the lock does not hold the extras) | 7 advisories (13 reports); the newest fix is in 50.0.0 | pinned to 50.0.2 in `pyproject.toml`; the push tests (191) pass with it |
| `aiohttp` 3.14.3 (transitive) | 8 advisories (cookies, request smuggling in the pure-Python parser, memory use); fixed by 3.14.4 | the lock now says 3.14.5 |
| `certifi` 2026.7.22 (transitive) | a root certificate that should no longer be trusted; fixed by 2026.10.19 | the lock now says 2026.10.19 |
| `next` 15.5.25 and `postcss` 8.4.31 inside it, `sharp`, `source-map-js` (web UI build tools) | 4 advisories (cache poisoning of pre-rendered pages in self-hosted apps, a style-sheet XSS and source-map file read in `postcss`, a denial of service in `source-map-js`, `sharp`'s image library) | `package-lock.json` moved to `next` 15.5.28, `sharp` 0.35.5, `source-map-js` 1.2.2, and an `overrides` entry in `package.json` raises `postcss` to 8.5.31 (Next pins an older one; the fix without the override is a major upgrade of Next). The UI builds with it; `npm audit` reports 0 |

**What the owner still has to do on this computer:** the running Diya keeps the old versions until the packages are installed again: `python -m pip install "python-multipart==0.0.31"` (and `"cryptography==50.0.2"` if phone notifications are ever switched on) and, in `frontend`, `npm ci`. Until then one test, `tests/test_pyproject.py`, is red on this computer, and it is right to be: it says the installed package is not the one that is pinned. Nothing was installed or changed on this computer by this work.

## The advisories that are ignored on purpose

`pip-audit` also reports six advisories for which no fix exists or the fix is a major upgrade, and which do not apply to how Diya uses the package. They are listed in CI so that a **new** advisory still fails the build.

| Advisory | Package | Why it does not apply |
|---|---|---|
| PYSEC-2026-311, PYSEC-2026-3813, PYSEC-2026-3814, PYSEC-2026-3815 | `chromadb` 1.5.9 | All four are about the Chroma **server** (its `/api/v2/tenants/...` endpoints and its authorisation providers). Diya uses an in-process client (`chromadb.Client(Settings(anonymized_telemetry=False))` in `diya.py`): it starts no server and has no tenants. No fixed version is listed. |
| PYSEC-2026-4114 | `oauthlib` 3.3.1 | A timing difference in the **authorisation server** side of the PKCE grant (`grant_types/authorization_code.py`). Diya does not import `oauthlib`; it is a transitive package. The fix is the major version 4.0.0. |
| PYSEC-2026-1845 | `pytest` 8.4.0 | Local users of a shared UNIX machine can interfere through the `/tmp/pytest-of-{user}` directory. The tests run on one person's Windows computer and on a fresh CI machine. The fix is the major version 9.0.3, a change to the test tool that was not made as part of this. |

Re-read this table when any of those packages is upgraded: the ignore should go when the reason does.

## Licences

The licence of every dependency, and why one LGPL group in the web UI's optional image tools is acceptable, is in `docs/LICENCES.md`.
