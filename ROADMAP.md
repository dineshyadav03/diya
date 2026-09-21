# Roadmap

Current work is Stage 0 (safety and reproducibility). Later stages are listed in the
[README](README.md#roadmap). The Phase 1 learning roadmap is archived in
[`archive/phase1-learning-roadmap.md`](archive/phase1-learning-roadmap.md).

## Stage 0 checklist

Done:

- [x] Lazy initialisation, `DIYA_*` configuration, app factory
- [x] Tests and evals cannot touch the live database
- [x] Line endings and text encoding pinned (`.gitattributes`, UTF-8; a test enforces it)
- [x] Network boundary: loopback by default, Host and Origin allowlists, no wildcard CORS

Remaining:

- [ ] Auth, remaining increments:
  - [ ] Per-install token, stored hashed
  - [ ] Next.js proxy, so the browser holds no secret
  - [ ] Request body-size limits
  - [ ] Restrict `list_files` to allowed folders
- [ ] `pyproject.toml` and locked dependencies
- [ ] Models pinned by digest (only tags today)
- [ ] Database migrations (the schema is `CREATE TABLE IF NOT EXISTS`)
- [ ] CI
