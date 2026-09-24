# Roadmap

Current work is Stage 0 (safety and reproducibility); the later stages are at the end. The Phase 1
learning roadmap is archived in [`archive/phase1-learning-roadmap.md`](archive/phase1-learning-roadmap.md).
Market and technical context for these choices is in [RESEARCH.md](RESEARCH.md).

## Stage 0 checklist

Done:

- [x] Lazy initialisation, `DIYA_*` configuration, app factory
- [x] Tests and evals cannot touch the live database
- [x] Line endings and text encoding pinned (`.gitattributes`, UTF-8; a test enforces it)
- [x] Network boundary: loopback by default, Host and Origin allowlists, no wildcard CORS
- [x] Docs rewritten from the current code (`README.md`, `PRODUCT_VISION.md`)
- [x] Request body-size limits: `DIYA_MAX_BODY_BYTES` (default 1,000,000), `DIYA_MAX_TRANSCRIBE_BYTES`
      for `/api/transcribe` (default 25,000,000); an over-limit request gets a 413 before any
      route -- or the model -- sees it, checked against both a declared Content-Length and the
      bytes actually sent
- [x] `pyproject.toml` pins every direct Python dependency to an exact version, checked against
      what is actually installed and passing the test suite (`pip install .`, verified with
      `pip install --dry-run`).
- [x] `requirements.lock` pins the full transitive tree with hashes (96 packages), generated with
      `uv pip compile pyproject.toml --extra dev -o requirements.lock --generate-hashes` (the
      `--extra dev` was added to the command tried first, which produced a lock with no pytest in
      it -- and no way to run the suite from it). Proved for real: `pip install --require-hashes
      -r requirements.lock` into a brand new virtualenv (nothing else installed), then the full
      suite there -- 425 passed. The lock is resolved for this dev machine's platform (Windows,
      Python 3.13), not universal: confirmed by trying the same `pip install --require-hashes`
      inside a Linux container, which refused outright (`uvloop`, a Linux-only dependency of
      `uvicorn[standard]`, has no entry, since the Windows resolution never needed it). CI
      therefore keeps installing from `pyproject.toml` (`pip install ".[dev]"`), not the lock,
      which resolves correctly per-platform on its own; a genuinely cross-platform lock would need
      `uv pip compile --universal` and its own proof, and is not done
- [x] CI: `.github/workflows/ci.yml` runs on every push and pull request -- checkout, Python 3.13,
      `pip install ".[dev]"`, the full test suite, then `scripts/check_hardcoded_addresses.py` (a
      repo-wide version of the private-range-IP check `test_config.py` already did for
      `diya_config.py` alone; also covered by `tests/test_hardcoded_address_scan.py` so a
      regression is caught locally too, not only in CI). One job, no matrix, no caching.
      Encoding/CR enforcement needed no new step -- `tests/test_text_files.py` already does it, so
      it runs as part of the test-suite step. Verified for real, not just read: the exact three
      commands above were run inside a plain `python:3.13-slim` container (not just reasoned
      about) -- 410 passed, 15 skipped (Node and `pythonw.exe`, both absent from that minimal
      image; GitHub's real `ubuntu-latest` ships Node, so some of those will likely run there
      instead of skipping), 0 failed. That run caught two real bugs before they reached CI: the
      address-scan script's own docstring named a placeholder address literally, tripping its own
      check once it covered `scripts/` too; and a pyproject test assumed the `dossier` extra
      (`reportlab`, for `render_pdf.py`, not installed by `pip install ".[dev]"`) would always be
      present. Both fixed. Not yet verified: an actual GitHub-hosted run (only a real push does
      that) and Node-dependent behaviour on `ubuntu-latest` specifically.
- [x] Database migrations: `diya_db.py`'s `MIGRATIONS` (an ordered, numbered tuple) replaces the
      old bare `_SCHEMA`; `apply_migrations(conn)`, called from `Store.connect()` exactly where the
      old schema DDL used to run, tracks applied versions in a `migrations` table and only runs
      what a database doesn't already have recorded. Migration 1 is the original three-table
      schema, unchanged -- `CREATE TABLE IF NOT EXISTS`, so no schema or connection behaviour
      changed for existing callers. Proved, not just written (`tests/test_migrations.py`, 16
      tests, 6/6 meaningful mutations caught -- a 7th, an unconditional `commit()`, survived
      because it's genuinely harmless, not a gap): a fresh database gets every table and exactly
      the columns migration 1 specifies (checked via `PRAGMA table_info`, not a text diff); a
      database frozen at the pre-migrations shape (`LEGACY_SCHEMA`, a deliberate copy of the
      original schema that must never be updated) gains a `migrations` table and is marked current,
      with its existing rows unchanged byte-for-byte; a database already current gets nothing
      newly applied on a second call, its migration record is never rewritten, and -- checked by
      watching every statement the connection actually runs, not just the end state -- no `INSERT`
      or table-creating `CREATE TABLE` is even attempted again. Also run for real against a copy
      of the live `diya.db` (33 threads, 143 messages, 5 reminders): all rows identical before and
      after, `Store.list_threads()` still works, a second `apply_migrations()` call changed
      nothing. The live file itself was never touched, only a copy. 445 tests pass overall (was
      429).
- [x] `list_files` restricted to configured folders (Stage 1 design unit 1,
      [`docs/STAGE1_DESIGN.md`](docs/STAGE1_DESIGN.md)): it refuses any path outside
      `DIYA_FILES_ROOTS` (comma-separated; the default is `Documents/Diya` under the home folder,
      never the repo root). The check runs on the fully resolved path, so a `../` escape and a
      symlink that points outside are both refused, and dotfiles, `.env*`, `*.pem` and `*.key` are
      left out of every listing. Setting `DIYA_FILES_ROOTS` replaces the default rather than adding
      to it; list both to keep both. `tests/test_list_files_allowlist.py` (22 tests, 8 of 8
      mutations caught). The real-symlink test cannot run on the Windows dev machine (creating a
      symlink needs elevation); it ran and passed on the Linux CI runner, and a mocked-`realpath`
      test covers the same property locally. The `diya_evals.py` "file listing" case now reads a
      pinned fixture folder instead of the repo.
- [x] Outbound destination allowlist for `get_weather` (Stage 1 design unit 2,
      [`docs/STAGE1_DESIGN.md`](docs/STAGE1_DESIGN.md) section 4): both of its calls now go through
      `diya._fetch`, which refuses any host not in `DIYA_TOOL_ALLOWED_HOSTS` before a request is
      sent (default: the two Open-Meteo hosts, so nothing changes for a fresh install; setting it
      replaces the default). The host is read by both `urllib.parse` and `httpx` and only trusted
      if they agree (an addition to the design: they differ on a leading space, a tab or a
      missing `//`, and `httpx` is the parser that makes the connection); redirects are not
      followed (`httpx`'s default, pinned by a test); loopback and private addresses are refused
      like any host that is not on the list. `tests/test_tool_allowlist.py` (58 tests, 16 of 16
      mutations caught, including the design's three: checked but not enforced, checked after the
      request went out, and too narrow), plus a live run against the real hosts.
- [ ] **`web_search` is not covered by that allowlist, and cannot be without replacing `ddgs`.**
      `ddgs` 9.16.0 makes its own requests through `primp` (a Rust HTTP client; its runtime
      dependencies are `click`, `lxml` and `primp`, not `httpx` or `requests`), so this code has
      no point at which to check a destination, and "reach the open web on request" has no short
      list of hosts to allow. Recorded, not faked, the same way the model-digest limit is. The
      options (replace `ddgs` with one fixed search API called through `_fetch`; an OS-level
      egress rule; accept the gap) are in `docs/STAGE1_DESIGN.md` section 4, which recommends
      accepting it for now. A test asserts it, so replacing `ddgs` shows up as a deliberate change.
- [ ] **A broader personal-data scan (names, cities, device labels -- not just addresses) is not a
      clean CI gate, and is not being forced into one.** Every pre-push audit so far has grepped
      for a short list of terms tied to specific past incidents (a real LAN IP, a pet's name, a
      device model, a sync-folder name), reviewing each match by hand. That works as a one-off
      human check; it does not work as an unattended pass/fail gate, because some of those exact
      words are legitimately part of the code going forward (`diya.py`'s `CITY_ALIASES` table
      genuinely needs the string "bangalore"; a future eval or note could legitimately mention a
      real city). A gate that fails on legitimate code trains everyone to ignore or bypass it. The
      hardcoded-address scan above stays narrow (address-shaped strings only) precisely because
      that shape has no legitimate use in application code outside `tests/`; a name/place denylist
      has no equally clean boundary. This stays a manual step in the pre-push audit.

Remaining:

- [ ] Auth, remaining increments:
  - [ ] Per-install token, stored hashed
  - [ ] Next.js proxy, so the browser holds no secret
- [ ] **Models pinned by digest: not possible with the current tooling.** `ollama pull` (CLI 0.34.2)
      rejects a `name@sha256:digest` model reference outright ("invalid model name"), tried as
      `qwen2.5:3b@sha256:...`, `qwen2.5@sha256:...` and `library/qwen2.5@sha256:...`; only a tag
      can be pulled, and a tag can be silently repointed by the publisher at any time. The digests
      below are still worth recording: computed by fetching each model's registry manifest and
      hashing it independently (not just trusting Ollama's own display), and confirmed to match
      the short ID `ollama list` already shows (its first 12 hex characters) --
      so they can be checked against, even though nothing enforces them on pull.
      Verified 2026-09-22: `qwen2.5:3b` is
      `sha256:357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`;
      `nomic-embed-text:latest` is
      `sha256:0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f`.
      After pulling, run `ollama list`: if the ID column's first 12 characters don't match these,
      the tag has moved since this was checked.
- [ ] Add a screenshot or demo GIF to the README (a placeholder line marks the spot, e.g. `docs/demo.gif`)
- [ ] Generate `truffle-research.html` from `render_pdf.py` (until then it is a marked hand copy)

## Later stages

1. Hardware and model benchmark. Includes the 3B model calling `add_reminder` on plain arithmetic
   questions (roughly 40-50% of past runs), which prompt and temperature changes did not fix.
2. Trustworthy memory. Includes the review-and-promote step for staged facts: nothing reads
   `dream_pending.jsonl` yet, so staged facts never reach the model. Reference for the
   verification step: the solver/verifier separation (Apodex).
3. Connectors and permissions.
4. Durable workflows. The competitive battleground: every comparable leads with "describe an
   outcome, it follows through". Reference: Muse-style approval gates and action trails.
5. "Jev" decision benchmark. Open-source baseline: laya-mlx (MLX, so Apple silicon only).
6. Daily-driver experience.

## Future items

- Call management (market signal: Equal AI).
- Voice pipeline: Whisper -> a fast decision model -> execute, streaming partial transcripts into the
  decider early (the OpenJev pattern).
