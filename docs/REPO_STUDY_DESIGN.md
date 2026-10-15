# Diya studies a repository (2026-10-16)

**What it is.** Asked "study https://github.com/owner/repo" (or explain it, reverse engineer it, how does it work), Diya reads the repository from the outside and answers with a short plain explanation followed by a report that keeps three kinds of statement apart: **observed** (read from a named file or from GitHub), **inferred** (a guess, with its basis) and **not established** (what was not read, so a missing fact is never taken for proof that something is absent). The method is REA's ("Reverse Engineer Anything", <https://github.com/morluto/rea>, MIT); no code or text of REA is used, and it is credited in `diya_repostudy.py`. The studies that came out of it are `docs/STUDY_SUPERMEMORY.md` and `docs/STUDY_REA.md`.

**Why this and not REA itself.** REA is for things you cannot read: binaries, packaged apps, running programs. Its own instructions say a complete source repository is read with ordinary tools and REA is not run. Running it would also mean installing a program that writes into agent settings and runs third-party code, which is the owner's decision. What was worth taking is its *discipline*, and that fits a small local model: let code do the reading and the counting, keep the labels honest, and let the model only explain.

## How it works

| Step | Who | What |
|---|---|---|
| 1. Decide | code (`diya_intent.repo_to_study`) | A message that contains a real `github.com/owner/repo` address **and** asks to study, explain, look at or reverse engineer it, in a short single-line message. Not a bare `owner/name`, not a look-alike host, not an address alone, not a pasted page. Never in an unattended run (automations). |
| 2. Read | code (`diya_repostudy.study`) | GitHub's public API for the description, licence, branch and the whole file tree (2 requests), then up to 10 files from `raw.githubusercontent.com`: the README, the manifests (`package.json`, `pyproject.toml`, `requirements.txt`, `Cargo.toml`, `go.mod`...) and a few guidance documents (`ARCHITECTURE.md`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`). At most 16 requests. |
| 3. Count and parse | code | Files and folders, code by size per language, the second level of monorepo folders, files named like an entry point, and what each manifest declares (name, scripts, dependencies). Folder purposes are guessed from names and labelled **inferred**. |
| 4. Explain | the model, **with no tools** (`Agent._answer_from`) | Five sentences at most, from the labelled facts only; "probably" for inferred ones; a project's claims about itself attributed to it. |
| 5. Show | code (`diya_repostudy.render`) | The report is appended to the answer exactly as built: the explanation may be wrong, the evidence under it is not paraphrased. |

## What keeps it safe

- **Read-only, and only two hosts.** Every request goes through the allowlisted fetch (`diya._fetch`) with `api.github.com` and `raw.githubusercontent.com` as the only destinations (an address anywhere else, `localhost`, a look-alike such as `api.github.com.evil.example`, is refused before anything is sent), GET only, no credentials, **no redirects followed**. Nothing is cloned, saved, installed or run.
- **Unsigned limits are respected:** GitHub's 60-requests-an-hour limit for unsigned callers is reported in plain words, not retried.
- **What a stranger wrote is text.** A README or a manifest can say anything. Each fact is made printable (no control or direction-changing characters, one line, cut short), the note tells the model it is information and not instructions, and **the model is given no tools** for this answer, so a README that says "call add_task" has nothing to call. A test pins that.
- **A failure never invents.** A private or missing repository gets a plain sentence and no model call; a model that does not answer still gives the evidence.
- `DIYA_REPO_STUDY=0` turns it off.

## Measured (real model `diya-chat`, real GitHub, 2026-10-16)

| Repository | Files | Requests | Files read | Time | What the explanation got right and wrong |
|---|---|---|---|---|---|
| supermemoryai/supermemory | 938 | 6 | 4 (README, package.json, CLAUDE.md, CONTRIBUTING.md) | 61 s | Right: a memory and context engine, a TypeScript/Python monorepo of apps and packages, SDKs and tools. **Wrong in manner:** repeated the README's own "#1 on three benchmarks" as plain fact even after the prompt asked it to attribute such claims. The report under it states what the README said. |
| morluto/rea | 3,981 | 6 | 4 (README, package.json, AGENTS.md, CONTRIBUTING.md) | 65 s | Right: a local reverse-engineering tool, TypeScript, CLI and MCP, adapters in `bridge/`, entry points `src/cli.ts` and `src/main.ts`. It also said it "runs locally, without cloud dependencies", which the README supports. |

Two defects the real repositories showed, both fixed: a README's first line was a row of language links (now only a line with at least forty characters of prose counts), and a large `package.json` was cut off before it could be parsed (manifests are now read whole, up to 60 KB).

## Limits

- It reads four files of a repository of thousands. It says what the project is and how it is organised, **not what its code does**; the report says so every time. Reading code files (an entry point, a module) is the obvious next step and was left out on purpose: that is where a small model starts guessing.
- Public GitHub repositories only. No GitLab, no private repositories (that would need a token, which Diya does not send).
- The explanation is written by a 4B model and can be loose; the evidence block is the part to rely on.
