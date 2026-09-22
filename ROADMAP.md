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

Remaining:

- [ ] Auth, remaining increments:
  - [ ] Per-install token, stored hashed
  - [ ] Next.js proxy, so the browser holds no secret
  - [ ] Restrict `list_files` to a configured root: the next auth increment. The default root is a
        dedicated `Documents\Diya` folder, not the repo root
- [ ] `pyproject.toml` and locked dependencies
- [ ] Models pinned by digest (only tags today)
- [ ] Database migrations (the schema is `CREATE TABLE IF NOT EXISTS`)
- [ ] CI
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
