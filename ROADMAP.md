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
      `pip install --dry-run`). Transitive versions are not locked -- a real lock file (`uv.lock`
      or `pip-compile` output, with hashes) would be the next step
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
  - [ ] Restrict `list_files` to a configured root: the next auth increment. The default root is a
        dedicated `Documents\Diya` folder, not the repo root
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
- [ ] Database migrations (the schema is `CREATE TABLE IF NOT EXISTS`)
- [ ] Add a screenshot or demo GIF to the README (a placeholder comment marks the spot, e.g. `docs/demo.gif`)
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
