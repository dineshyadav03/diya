# Study: a computer-use agent for Diya (2026-10-27), before anything is applied

The owner's goal is Hark's "Handoff": the assistant does things on websites for you. This page says what a computer-use agent is, what the DeepSeek harness copy really holds, what a 4B model on this laptop
can and cannot do with one, the danger, and what to measure before any code. Nothing here has been applied. Where a line is general knowledge and not something checked today, it says so.

## 1. What it is

Three layers: a **model** that decides the next step; a **driver** that turns "click that button" into a real click and hands back what the page looks like; and a **browser or desktop**. The loop is look, decide,
act, look again, until done. The two ways to "look" decide everything else:

| Way of looking | What the model gets | Needs from the model |
|---|---|---|
| Page structure (accessibility tree, as Playwright MCP gives it) | text: one line per button, link, field, with a name | a text model; page size must fit its window |
| Screenshot (Cua Driver, vision agents) | an image of the screen | a vision model, which on this laptop competes with the chat model for 16 GB |
| Nothing: a recorded script | nothing; the model is not in the loop | none: code does the clicks, the model only supplies the details |

## 2. What the harness copy holds (read from `harness/docs/subsystems/`, not run)

- `browser-use` and `computer-use` are **registration slots**, not agents: they accept ONE provider and have "no common browser-operation methods". The agent loop is the harness's own, and the doing is borrowed.
- Browser providers, all experimental: **Playwright MCP**, **Chrome DevTools MCP**, **Stagehand** (a library that asks a model to act on a page). Chromium only. "Cancellation cannot undo a browser action already delivered."
- Computer use: **Cua Driver**, an outside program, written about first for macOS; screenshots go to image-capable models only, and a text-only model gets "the existing MCP image diagnostic" instead.
- So the harness adds a place to plug a driver in. It does not add the ability. Everything it could do for Diya comes from Playwright, which Diya could use without it.

## 3. What a page costs a text-only agent (measured today)

Public pages opened in the installed Edge, structure only, one line per useful element (`handoff/tools/ax_size.mjs`; nothing typed or clicked):

| Page | Interactive elements | About tokens |
|---|---|---|
| example.com | 1 | 230 |
| GitHub login | 15 | 300 |
| Amazon.in front page | 42 | 1,000 |
| Wikipedia main page | 249 | 6,800 |
| IRCTC front page | 0 | 95 (almost nothing came back: bot blocking or slow scripts; not diagnosed) |

Diya's window is 16,384 tokens and the persona, tools and chat already take about 2,500. A form or a bill page fits easily; a busy page does not. And one step is one page, so a ten-step chore is ten pages.

## 4. What a 4B model can and cannot do here (general knowledge, NOT measured here)

- It can pick one element out of a short list when told exactly what to look for. It is poor at planning ten steps, noticing that a step failed, and stopping. Small models in public reports loop, click the wrong
  thing and say "done" when nothing happened. Hark uses frontier models for this; we cannot.
- It cannot do vision work and chat in 16 GB at once.
- Sites fight automation: sign-in checks, one-time codes, bot detection. **Diya never solves a CAPTCHA** (a rule of this project), so some sites are out whatever the agent can do.

## 5. The danger, which is the same as the Rule of Two in `docs/AUTHORITY_MODEL.md`

A browser agent **reads words strangers wrote** (any page), **can reach private data** (a signed-in session) and **can change things** (click Pay). All three together is the combination that a hidden sentence on a page can
turn against you ("ignore your instructions and transfer..."). So: a separate browser profile that is signed in to nothing else; a short list of sites it may open; the password never in the model's context;
a money cap; and **every step that changes something is approved by you, with the exact words and a screenshot of what will be submitted**, as every other action in Diya already is.

## 6. Verdict and the shape that fits Diya

Do not integrate the harness's computer-use or browser-use now. It brings frontier-model assumptions, a macOS-first driver and nothing a recorded script does not already give.

The shape that fits is the project's own rule, **code finds and acts, the model words**: a **flow** per chore, recorded once as a Playwright script (open this site, this field, this button), run by code; the model
only supplies the details ("the amount", "the date") from your words; the last step shows you the filled page and waits for your yes (typed or pressed); a failure stops and says where. One flow at a time, a read-only one first
(read the amount on a bill), then one that changes something.

## 7. What to measure before any code (nothing needs your accounts)

1. **Can `diya-chat` pick the right element?** Give it the GitHub login structure (300 tokens) and ten plain tasks ("which line is the field for the user name?"); count right answers and time. Under 9 of 10: stop.
2. **Does a flow survive?** Record a read-only flow on the one site you choose, run it five times on five days; count the runs that finish. (Needs your choice of site, and your sign-in done by you in a separate profile.)
3. **Harness Phase 1** (`docs/DSH_PHASE1.md`, run by you in Docker): only to see whether the harness's own loop can drive `diya-chat` at all. It is not needed for the flow design above.

Decision rule: if 1 passes and 2 finishes at least 4 of 5, build the first flow. If not, Handoff stays out of reach for this machine and Diya stays an assistant that tells you what to do and drafts it, not one that clicks.

## 8. Measured on diya-chat, 2026-10-27 (`handoff/tools/capability_probe.py`; small samples: indicative, not proof)

| Building block | Result | What went wrong |
|---|---|---|
| A. Details from a booking request (restaurant, party size, 24-hour time) | 3 of 5 fully right, 13 of 15 fields | "7:30 pm" came out as 20:30; "an italian place" got an invented restaurant, "Bella Italia" |
| B. A short message to a restaurant | 3 of 3 had the facts, short, no invented phone number | one left a "[Your Name]" placeholder |
| C. Pick the right element on a 12-element login page | 8 of 8 | none (a clean page; real pages are bigger and messier) |
| D. Did the step work, from what the page says | 7 of 8 | "the restaurant will confirm by SMS" was called finished: the premature "done" |

So the model is good enough for the pieces if code checks them: the time is read by code (diya_time), a restaurant is accepted only if the person's own words contain it, and "finished" is decided by code
looking for the site's own confirmation text, never by the model's say-so. Without those checks, a flow would book the wrong time or report success that did not happen.

