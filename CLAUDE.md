# Diya

## Mission
**Diya** (named 2026-09-16) is dinesh's real, ongoing personal AI project -- not a tutorial. The
goal is full feature parity with what Truffle actually does (per `Truffle_Research_Dossier.pdf`),
built for real daily use, with no fixed end date. Explicitly stated scope: "this should be my
biggest project, I want no going down on this."

The project has two phases:
- **Phase 1: Foundations** (`ROADMAP.md`) -- complete. Five milestones, learned and proven by
  building small, honest versions of Truffle's core mechanisms on Windows, before any hardware
  arrived: local inference, tool-calling (raw + MCP), embeddings/memory, scheduled proactivity,
  and a capstone agent loop. Real, working code, real bugs found and fixed -- not just reading.
- **Phase 2: Building Diya for real** (`PRODUCT_VISION.md`) -- in progress, open-ended. Turning
  those proven mechanisms into something dinesh actually uses, with real persistence, real tools,
  a real "Dreaming" memory-consolidation job, and eventually a real always-on runtime and client.

This is a multi-session project. Nothing here is meant to be finished in one sitting.

## Team
- **User (dinesh)**: owns the hardware and the decisions, runs every command, reviews every piece
  of code before it counts as "done." Learning-by-doing, not being handed a finished product.
  Can read/understand code well; does not yet write code independently.
- **Claude**: writes the code, explains *why* before/while writing it (not just what), proposes
  the next step each session, never assumes a prior explanation "stuck" without checking.

## Working agreement
1. Every piece of code comes with a plain-language explanation of what it does and why, before
   moving on. If something isn't clear, say so -- that's the point of doing this together instead
   of just being handed the dossier's Mac mini section.
2. Nothing is rushed. Milestones in `ROADMAP.md` are worked in order, but at whatever pace fits.
3. At the **start** of a session: re-read `ROADMAP.md`'s "Status" section to recall where we left
   off. At the **end** of a session: update it before stopping.
4. Once the Mac mini is in hand, the real coding work should happen with Claude Code running
   *on the Mac itself* (not relayed from this Windows machine) -- so errors, installs, and tests
   are all real, live, and immediate. This folder lives on OneDrive specifically so it's reachable
   from the Mac once it's set up there too.

## Hardware decision (locked in 2026-09-16)
**Recommended buy: Mac mini, M6 chip, 16GB unified memory, 256GB SSD -- $899** (Apple's own
current pricing, confirmed at time of writing; some retailers pre-order it a little under $880).
- 16GB is enough to run the 7-8B-class quantized models this whole roadmap is scoped around --
  see `ROADMAP.md` Milestone 1 onward. Bigger models are a *later* problem, not a day-one one.
- If budget allows, 16GB/512GB storage (~$1,099) buys more room to keep several downloaded models
  around at once without deleting old ones -- a nice-to-have, not a requirement.
- Deliberately **not** recommending the 24GB/512GB ($1,299) or M5 Pro 64GB ($2,899) configs yet.
  Those solve a "the model I want doesn't fit in memory" problem we haven't hit yet. Upgrade only
  once a specific milestone actually demands it, and we'll know exactly why at that point.

## Reference
- `PRODUCT_VISION.md` -- Diya's real product scope, the Truffle-feature-parity tracker, Phase 2 plan
- `ROADMAP.md` -- Phase 1's completed milestone plan (kept as a record, not actively updated now)
- `Truffle_Research_Dossier.pdf` -- the original research this project is based on (Section 11 especially)
