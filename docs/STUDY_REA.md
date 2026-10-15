# REA, studied on itself (2026-10-16)

**Target:** <https://github.com/morluto/rea> (MIT licence, 3,981 files, 267,000 stars, last pushed 2026-10-15). **Method:** its own: every statement is **observed** (read from a named file), **inferred** (with its basis) or **not established**. The first pass was made by Diya's repo-study skill (`diya_repostudy.py`), which is written in REA's spirit; the rest was read from the files named. REA itself was **not run** (its own skill file says a complete source repository is read with ordinary tools, and running it means installing a program that writes into agent settings; see "What was not done").

## 1. What it is

**Observed** (`README.md`, `package.json`): "Reverse engineer anything with agents, from app behavior down to native binaries." One program (npm package `rea-agents`, commands `rea` and `rea-agents` both pointing at `scripts/rea.mjs`) that can run as an **MCP server** for a coding agent or as a **command line**, with the same workflows behind both. It inspects native binaries (through Hopper, Ghidra or IDA that the user already has), JavaScript and Electron apps (without any engine), .NET assemblies, Android packages, firmware, browser pages and recorded network captures, and returns **Evidence**: the answer plus where it came from and what it could not establish. Analysis runs locally. `npx rea-agents setup` registers it with Claude Code, Codex, Cursor, Gemini CLI and others and installs matching workflow instructions (a "skill").

**Observed** (file tree): TypeScript 83% of the code by size. `src/` 1,950 files (domain 601, application 331, browser 129, server 93, contracts 88, process 78, ghidra 70, artifacts 63), `tests/` 1,203, `scripts/` 393, `docs/` 111, `bridge/` 32 (programs that run inside Hopper, Ghidra, Cutter, mitmproxy and LLDB). Entry points `src/cli.ts` and `src/main.ts`. Dependencies include `@modelcontextprotocol/client` and `server`, `@babel/parser`, `@electron/asar`, `@lydell/node-pty`; the dev side has Vitest and Stryker (mutation testing).

## 2. How it is built

**Observed** (`docs/architecture.mermaid`, `AGENTS.md`): layers with dependencies pointing inward. A pure **domain** (evidence, comparisons, application graphs, no side effects) under **contracts** (the schemas a caller sees), under a shared **application** layer (the workflows both the CLI and the MCP server use), under **providers** (Hopper, Ghidra, IDA, browser, Android, firmware, SQLite...), over a **process foundation** (owned process groups, deadlines, cleanup). Engines are "bring your own": setup never installs Java, Node, Ghidra or IDA. Configuration changes must be additive and idempotent, with backups.

## 3. The ideas worth having (all **observed** in `AGENTS.md`, `docs/tool-design.md` and `.agents/skills/reverse-engineer-anything/`)

1. **Keep four kinds of statement apart:** observations, derivations, inferences and unknowns. Every answer carries its provenance, its coverage and its limitations.
2. **Missing coverage is unknown, not absence.** "A missing match in partial source Evidence does not establish absence." A page of results running out is not the same as the source being complete.
3. **Never claim a run, a reproduction or a measurement you did not make.** Issue reports use `NOT_ENOUGH_INFO` for what is missing.
4. **Fail closed on scope.** "Do not integrate capabilities while material scope, authority, side-effect or verification questions remain unresolved."
5. **Bounded, owned effects.** Processes REA starts are owned, have deadlines and are cleaned up; limits exist only for real format or measured resource reasons, and truncation is always reported.
6. **An unknowns registry:** open questions are recorded with the evidence for and against them and a revision number, and only qualifying observed evidence can close one.
7. **Measure what you optimise** (tokens, time, memory, cold versus warm), and say which costs were not measured.
8. **A plan without execution does not establish runtime behaviour.**

## 4. What was taken for Diya

- **The report shape** of the new repo-study skill (`diya_repostudy.py`, `docs/REPO_STUDY_DESIGN.md`): observed (with the file), inferred (with its basis), not established (what was not read, so a gap is never read as proof). No code or text of REA is used; it is credited in the module and the design note.
- **No claims without a run:** Diya's report says that nothing was run and how many of the files were read.
- **For later, if wanted:** an unknowns list for the owner's open questions (which Diya's question cards already approximate), and REA's habit of printing what it could not establish next to every answer.

## 5. What was not done

- **REA was not run.** `npx rea-agents setup` registers an MCP server and installs a skill into agent configuration; its static analysers run code from the npm registry on this computer. Both need the owner's say-so, and neither is needed to study a source repository.
- **Not read:** the code under `src/`, the bridges, the tests, the website, the changelog (366 KB), and all but about eight of the 3,981 files (the README, `AGENTS.md`, `CONTRIBUTING.md`, `package.json`, the skill file, its evidence reference, the architecture diagram and the tool-design note were read). Everything in section 3 is what REA says about itself; whether its code does it was not checked.
- **The 267,000 stars** are GitHub's number as of today; the popularity of a repository says nothing about whether this description is right.
