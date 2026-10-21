# Adopting DeepSeek's harness and keeping Diya's ideas (plan, 2026-10-21; tasks DIYA-188 and DIYA-257)

**What the owner asked on 2026-10-21:** "copy everything from that harness, exactly the same harness" **and** "our ideas too", both together.

## What the DeepSeek harness is (read on 2026-10-21; nothing of it was run)

* Source: https://github.com/deepseek-ai/deepseek-harness, **MIT**, about 256,000 stars, last push 2026-10-17. A read-only copy is at `C:\Users\dines\dsh-copy\deepseek-harness`: commit `687f282e8625c6b8d11ff58211a90524be2e4317`, 16,297 files, about 206 MB on disk. It is **outside** this repository and outside OneDrive, on purpose.
* **344 packages**, 96% TypeScript, on the Cordis plugin framework ("everything is a plugin"; a running setup is a tree of plugins composed from YAML profiles and bundles).
* Its own safety page: experimental developer preview, **no security audit**, it can run model-written code and commands, load third-party plugins and reach files and credentials; use a disposable VM.
* Windows is a first-class target in what was read (`sandbox-windows-acl`, `pwsh-local`, `pwsh-sandbox`). Local models: the model layer (`llm-pi-ai`) mentions Ollama in its catalogue; **how well a 4B model drives its tool loop was not tried.**

## What is in it, against Diya's five pillars

| Pillar | In DeepSeek's harness (packages) | In Diya today | Gap |
|---|---|---|---|
| Context | `context` (instructions, file and session references, time), `compaction` (basic, tool-result pruning, image offload), `spill` | memory profile, recall, episodic recall, playbooks, dated facts; history cut by size | **real compaction** |
| Action | `shell`, `fs`, `web` (search, fetch), `browser-use`, `computer-use`, `lsp`, `mcp`, `skill`, `subagent`, `workflow`, `todo`, `schedule` | a fixed list of read tools and approved proposals; no shell, no browser | many tools, most of them **unsafe by Diya's rules** |
| Orchestration | `core/agent-loop`, `plan`, `goal`, `jobs`, `subagent`, `workflow`, `session` (checkpoints, format migrations) | one loop with code-first routing | durable jobs, plan mode, checkpoints |
| Control | `interaction` (user approval, permission presets), `sandbox`, `guard` (repeat-tool reminder, timeout policy), `credentials` | approvals by exact hash, pause switch, tool tiers, local-only model, Rule-of-Two accounting | their **sandbox** and **timeout policy** |
| Feedback | `feedback` (message and command feedback), `telemetry` (OpenTelemetry), `session-query`, `test-support` (replay, mock model server) | Status page, scorecard, journal | **a feedback loop and replayable sessions** |

## What Diya has that it does not (the ideas to keep)

Reviewed memory (a fact waits for the person before the model is told it), fading and Keep, "how do you know that?" and "what did you know on 12 Oct?" answered from the record, facts and dates written by code instead of the small model, approval by exact hash with a pause switch, the model address refused unless it is this computer, a threat model checked by tests, and 8,230 tests.

## The way to have both without throwing Diya away

**A bridge, not a rewrite.** The DeepSeek harness becomes the runtime; Diya's Python keeps running as a local service ("brain services": memory, provenance, calendar, connections, approvals) that a **small plugin** in the harness calls over Diya's own API on this computer, so the harness gets Diya's memory, reviewed facts, record-based answers and approval gate as tools and context. Nothing is rewritten in TypeScript except that bridge. If it proves out, ports of single pieces can follow, each with its MIT notice.

## Phases (each a slice of about 5% of a weekly limit; none is done yet)

| Phase | What | Gate before the next |
|---|---|---|
| 0 | **Done 2026-10-21:** the pinned read-only copy, this map | the owner's yes for phase 1 |
| 1 | Run the harness **in isolation** (a container or a throwaway Windows user, an empty workspace, no credentials, shell and computer-use tools off) against the local Ollama model; time ten of the owner's everyday questions | does a 4B model drive its loop at all? If not, stop and say so |
| 2 | The bridge plugin: Diya's memory read, record-based "how do you know", and approval, called from the harness | the owner uses it for a day beside Diya |
| 3 | Port what fixes Diya's failures: compaction, feedback (helpful / not helpful), the timeout policy, replayable sessions | each piece tested, notice kept in `THIRD_PARTY_NOTICES.md` |
| 4 | Decide whether anything more moves over, or whether Diya's own front end stays | the owner's decision, after real use |

## Rules while this is done

* **The owner's rule of 2026-10-21: build from that repository, but keep it nowhere inside Diya.** The copy stays at `C:\Users\dines\dsh-copy\deepseek-harness`. It is never added to this repository as a folder, a git submodule or subtree, a vendored directory or a pinned dependency. Only what we write ourselves, with its MIT notice, may sit in Diya. `tests/test_licences.py` fails if a `.gitmodules` file or a tracked path inside a `deepseek-harness` folder appears.

* The copy is **read, never run, on the owner's own account**; running comes only in phase 1's isolation and only on the owner's yes in chat. Its install step runs thousands of other people's packages, so it is not run on the host.
* No shell, browser or computer-use tool is given to a model on this computer without the owner's explicit yes for that tool, each time (the owner's decision of 2026-10-18: ask every time for external actions).
* Code taken from it keeps its MIT notice and is named in `THIRD_PARTY_NOTICES.md` (the licence rule, `docs/LICENCES.md`). Nothing from it is in this repository yet.

## What is honestly not known

Whether a 4-billion-parameter model on this CPU can use a harness built for frontier models (its prompts and tool schemas are large against a 16,384-token window); how much of the 344 packages Windows and a local model actually exercise; and whether the harness's quality justifies the move. Phase 1 exists to find out before anything else is spent.
