# Diya — Product Vision

## What this is
Diya is dinesh's personal AI system, modeled on the architecture documented in the Truffle
Research Dossier, built for real daily use -- not a tutorial exercise. This is now an **open-ended
project with no fixed end date.** Ambition level, stated explicitly: full feature parity with what
Truffle actually does, built by a two-person team (dinesh + Claude), for one real person, for real.

Milestones 1-5 in `ROADMAP.md` are **Phase 1: Foundations** -- complete. Everything below is
**Phase 2: building Diya for real**, which starts now.

## What problem Truffle actually solves (Diya solves the same ones)
1. **Data sovereignty** -- an assistant whose inference never has to leave the device it runs on.
2. **Persistent personal memory** -- accumulates real understanding of one person's life over time,
   instead of forgetting everything at the end of each session.
3. **Proactivity** -- acts on your behalf on a schedule or when something changes, not only when
   directly asked.
4. **Extensibility** -- a growing set of real tools wired into your actual accounts and real life,
   not a fixed, closed feature set.

## Truffle's feature set vs. Diya's current status

| Feature | What Truffle does | Diya's status |
|---|---|---|
| Local inference | Qwen 3.6, on Jetson hardware, OpenAI-compatible API | **Done.** Ollama + qwen2.5:3b, identical API shape (Phase 1, M1) |
| Tool-calling / apps | MCP-based app store: Slack, Gmail, Notion, Obsidian, WHOOP, Home Assistant, etc. | **Growing.** `diya.py`: `list_files`, `search_notes`, `web_search` (`ddgs`, no key), `get_weather` (Open-Meteo, no key, population-disambiguated geocoding), `add_reminder`/`list_reminders`. Two real lessons, both fixed 2026-09-16: (1) routing weather through generic web search gave vague "old Siri"-style non-answers -- fixed with a purpose-built tool; (2) network tools had no timeout and could hang indefinitely offline -- fixed with a 5s timeout + graceful "no connection" message on both `get_weather` and `web_search`. Plain chat needs zero network, always, unaffected either way. |
| Memory | Local embeddings + vector store + a "User profile" category | **Mechanism done** (M3). Only 5 fictional example notes so far, no user-profile layer |
| Proactivity | Background apps push context on schedule/event; agent acts across apps | **Mechanism done** (M4, incl. a real Windows Task Scheduler job). Only watches one folder. **Hardened 2026-09-17**: found this was the one script still running unattended with zero error handling around its Ollama call -- would have crashed silently every 15 min if Ollama were ever briefly unreachable (e.g. right after a reboot). Fixed: failures now degrade gracefully and retry next cycle instead of losing the file or crashing. |
| Robustness (audited 2026-09-17, prompted by dinesh pushing for a real re-check, not a happy-path one) | -- | Three real gaps found and fixed, each proven with a real failure simulation, not just theorized: (1) `diya.py` crashed with a raw traceback on startup if Ollama wasn't reachable yet -- now fails with a clear message + exit code 1; (2) the tool-calling loop in `ask()` had no round limit at all -- could loop forever if the model got stuck; now capped at 8 rounds, matching Truffle's own documented `/max_rounds` default, proven with a mock that forced it to hit the cap; (3) a mid-conversation connection drop crashed the whole interactive chat -- now prints a clear message and the conversation continues on the next message. Same Ollama-availability constraint confirmed to apply identically on macOS (per-user login item, not a daemon) -- mitigated there with automatic login, a one-time setting, not a workaround to build. |
| **Dreaming** | Nightly consolidation/reflection cycle refining memory + user profile | **Not assembled yet** -- but M3 (embeddings/store) + M4 (scheduling) are exactly the two ingredients it needs |
| **Convo** | Persistent, multi-threaded, renamable, searchable conversation history | **Core done** (2026-09-16): `diya_db.py` (SQLite: threads + messages) + `diya_chat.py`, proven across separate process runs. Not yet: renaming, searching, multiple concurrent threads used in practice |
| Self-authoring tools (RunToolScript) | Agent writes and saves its own new tools on request | **Not built** |
| Client apps | Symphony (desktop), Radiance (iOS) | **Not built.** Terminal only, so far |
| Dedicated hardware | Custom Jetson-based always-on appliance | **Pending** -- Mac mini becomes Diya's always-on box once it arrives |

## Phase 2 — building Diya for real
No fixed milestone list yet on purpose -- to be scoped as we go, driven by what Diya should
actually do for dinesh's real life, not a copy of Truffle's example app list (Slack/Gmail/WHOOP
were built for *Truffle's* users, not necessarily relevant here). Known, concrete building blocks,
in a sensible dependency order:

1. ~~**Persistence**~~ -- **done 2026-09-16.** `diya_db.py` (SQLite: `threads` + `messages` tables)
   and `diya_chat.py`. Proven with a real test: told it something in one process run, asked about
   it in a completely separate run, got the right answer straight from the database -- no
   embeddings or Dreaming involved. This directly resolved an open design question: short-term
   recall (same thread) needs only this, not Dreaming.
2. **Real tools** -- integrations for things that actually matter in dinesh's real day-to-day life.
   To be defined together, not assumed by copying Truffle's list. **Next up.**
3. ~~**Dreaming**~~ -- **built and proven 2026-09-17.** `dreaming.py`: reads every user message
   across ALL threads since the last dream cycle, asks the model to merge new real facts into a
   standing `user_profile.txt`, tracks progress the same way `milestone4_watcher.py` does (a state
   file, never loops itself, doesn't crash or lose progress if Ollama is unreachable -- that lesson
   applied from the start this time). `diya.py` now injects the current profile as a system message
   on every run, in every thread. **Proof, not assumption**: told it "my dog's name is Rocky" in
   thread 20, ran a dream cycle, asked "what's my dog's name?" in thread 21 -- a brand-new thread
   that never mentioned Rocky at all -- and it answered correctly. This is the direct fix for the
   exact gap dinesh identified days ago (something said in one conversation, recalled from a
   completely different one).
4. **Always-on runtime** -- move from "a script someone runs manually" to a real background
   service. Realistically waits for the Mac mini to be the dedicated, always-on machine.
5. **A real client** -- eventually, something better than a terminal. A simple local web page is
   the realistic first step; a native desktop/mobile app is a much later, much bigger undertaking.

## Research addendum (found 2026-09-16, after the original dossier)
Checked `github.com/deepshard` again for anything new. Two real findings not in the original PDF:
- **`LookMomNoCloud`** is actually "Truffle Desktop" (likely Symphony's internal/early name). Its
  README reveals real stack details: a Python backend (`server.py`) with **Prisma** (a real,
  migrated database -- `prisma-client-py` is vendored as a fork) and a TypeScript/Bun frontend.
  Confirms Convo's persistence is a proper migrated database, not something improvised.
- **Their inference engine is MLC-LLM** (`mlc-ai-nightly`, `mlc-llm-nightly`), not a homegrown
  engine. This explains a detail the original build-vs-buy research flagged as a side note: MLC's
  TVM-based stack benchmarks roughly 2x faster than Ollama/llama.cpp on the same Jetson hardware --
  very likely why they chose it. Diya uses Ollama instead, deliberately, for simplicity at our
  scale; MLC-LLM would be the real upgrade path if raw on-device speed ever became the bottleneck.

## Evals (added 2026-09-17)
`diya_evals.py` -- a real, repeatable eval suite, prompted by dinesh asking "don't we need evals
for this?" Six test cases checking both tool-routing and answer content. Already caught two real
regressions the first time it ran:
- The Bangalore geocoding fix had silently regressed -- root cause was actually that the geocoding
  API sometimes returns *only* the wrong-country match with nothing to disambiguate against, not a
  logic bug in the disambiguation itself. Fixed with a small city-alias table, now permanently
  covered by an eval case so it can't regress silently again.
- Simple factual questions sometimes returned genuinely empty answers (~40-60% of runs) -- fixed
  with a bounded one-shot retry in `ask()`, verified at 8/8 correct across repeated runs.

**Known, tracked, NOT fixed -- and now confirmed closed as an investigation, 2026-09-17:** the
model still calls tools unnecessarily on plain factual statements (`add_reminder` on math answers,
`web_search` on being told a fact about a dog). Three real fix attempts tried and measured, all
failed: tightening the tool description (twice), and lowering `temperature` to 0.1 -- which
actually made it worse (8/8 unnecessary calls, up from ~50%), suggesting the model's single most-
likely completion already leans toward calling a tool, so more determinism just locks in the wrong
default harder. This is a genuine small-model training-level bias, not a wording or sampling
problem on our side -- confirmed the "Type 2" reasoning-gap category from the model-vs-memory
discussion. Real consequence already observed: junk reminders written into the live database
during testing (found and cleaned up). Conclusion: needs a different/bigger model to actually fix,
not more prompt or parameter tuning -- stop chasing it here, revisit once a bigger model is an
option (post-Mac-mini).

## Watcher UX fix (2026-09-17)
The scheduled task was popping up a visible terminal window every 15 minutes (`python.exe` always
opens a console). Fixed by switching the task to `pythonw.exe` (the windowless interpreter) --
but that alone would have been risky, since `print()` crashes under `pythonw.exe` with no console
to write to. Fixed properly by redirecting stdout/stderr to a real file (`watcher_log.txt`) at the
top of the script before anything else runs, tested directly with `pythonw.exe` first, then
verified the live scheduled task still succeeds (`LastTaskResult: 0`) after the change.

## Web client (added 2026-09-17)
`diya_web.py` -- a real FastAPI + browser chat UI, reachable from any device on the LAN (e.g.
`http://192.168.0.174:8080`, machine-dependent), not just this PC's terminal. Prompted by dinesh
mentioning a spare iPhone XS -- can't run any AI itself, but works as a dedicated screen for Diya
via Safari, no native app needed.

Two real bugs found and fixed while building this, neither of them "the feature I meant to build":
- A `fastapi`/`starlette` version mismatch (starlette had been upgraded to 1.6.0 by another
  package's dependency resolution, breaking the older installed fastapi) -- fixed by upgrading
  fastapi, verified the MCP server code still imports fine afterward (same starlette dependency).
- **The Dreaming profile silently didn't apply on the web UI** -- it had only been wired into
  `diya.py`'s `main()`, not into any shared function, so the new web entry point never got it.
  Refactored into `with_profile()`, a real shared helper now used by every entry point (terminal,
  web, and available to evals), so this specific class of "only wired into one code path" bug
  can't recur the same way again. Verified fixed: the "what's my dog's name" test now answers
  correctly through the web UI too, not just the terminal.

Firewall note: opening the port to LAN traffic needs an admin-level rule, which this session
correctly could not do on its own (access denied) -- that's dinesh's call to make, not something
to route around. Command to run in an elevated PowerShell if Windows doesn't just prompt for it
automatically: `New-NetFirewallRule -DisplayName "Diya Web UI (port 8080)" -Direction Inbound
-Protocol TCP -LocalPort 8080 -Action Allow -Profile Any`.

**Verified working, 2026-09-17 -- the first real cross-device test in this whole project.**
Opened `http://192.168.0.174:8080` from the iPhone XS over Wi-Fi and added it to the Home Screen.
Everything before this was tested via curl from the same machine; this is the first confirmation
from an actual separate device. Diya now has a real client, not just a terminal.

Still open, not yet done: Guided Access on the iPhone (Settings -> Accessibility -> Guided Access)
to lock it into just this one app, for the full "dedicated appliance" feel discussed alongside the
iPhone-as-Truffle-device conversation. Software side of the client is done; that step is a physical
phone setting only dinesh can do.

**Voice output added 2026-09-17.** Not Piper (that's for a future non-browser, always-on voice
pipeline) -- for "make the web UI speak back," Safari's own built-in, fully local
`speechSynthesis` API is the right smaller first step: zero new dependencies, runs entirely
on-device, reachable directly from the page's own JavaScript. Added a "Speak replies" toggle
(checked by default) that speaks each answer aloud. First version was silently broken -- called
`speechSynthesis.cancel()` immediately before `speak()`, a known iOS Safari bug where that pattern
silently drops the new utterance. Fixed: only cancel if actually mid-speech, small delay after.
Added a "Test Voice" button (speaks a fixed phrase on direct tap) and on-page error surfacing
since there's no way to see the phone's console remotely.

**Voice input added 2026-09-17, in response to dinesh actually wanting real voice exchange, not
just spoken replies.** Real platform constraint worth recording: Safari has no Web Speech
Recognition API at all (unlike Chrome) -- there is no local, in-browser way to do speech-to-text
on iOS Safari. Built the real alternative instead: record audio via `MediaRecorder` (Safari does
support this), upload to a new `/api/transcribe` endpoint, transcribe locally with **faster-whisper**
(`base` model, CPU, int8) -- fully offline, no cloud speech API. Model loads once at server startup
(~60s the first time, downloading; cached after) rather than per-request, which would otherwise
make every voice message painfully slow. This is tap-to-talk, not always-listening -- the honest,
buildable version of "real-time," not the full wake-word pipeline (still future work).

Verified for real: loaded the model, transcribed a generated test clip directly (1.4s once loaded),
then verified the *actual* HTTP endpoint end-to-end with a real multipart file upload -- matches
exactly what the browser's fetch/FormData call does. One real accuracy finding already surfaced:
Whisper's base model transcribed "Diya" as "dear" in one test -- a plausible, likely-recurring
mishearing of the assistant's own name, worth knowing about rather than being surprised by later.

**What's unverified from here, real mic recording through Safari on the actual iPhone** -- no
microphone access in this environment. That's the one part only dinesh can confirm.

## UI redesign + a real found-and-fixed breaking bug (2026-09-17)
Dinesh called the first UI genuinely bad ("looks shit"), fairly -- it was never given an actual
design pass. Redesigned: dark theme (fits an always-on device sitting somewhere, not glaring),
a proper header instead of floating overlapping buttons, real chat-bubble styling, diagnostic/
error text now rendered as small centered system messages instead of fake assistant chat bubbles,
icon-only round mic/send buttons with the mic actually pulsing red while recording. Logo went
through one iteration: first a 🪔 emoji nodding to what "Diya" means, then dinesh asked for that
removed in favor of something more professional -- replaced with a small inline SVG badge (rounded
square, amber background, bold "D" lettermark), no emoji.

**A real, serious bug found immediately after this redesign, worth understanding precisely:**
dinesh reported "not sending the message" -- turned out to be much worse than one broken button.
`PAGE` is a Python string containing a large block of literal JavaScript. Because it was a
*regular* (non-raw) Python string, Python's own escape processing ran on the JS content before it
ever reached the browser -- consuming a `\'` that JavaScript needed to escape an apostrophe inside
a string (`'that\'s suspiciously small...'`), leaving a bare unescaped apostrophe in the actual
served JS. That broke the *entire* `<script>` block with a syntax error, meaning none of the
functions -- `send()`, `addMsg()`, the mic handlers, all of it -- were ever defined. Confirmed by
extracting the actually-served JS and finding the broken line directly in it, not by guessing.
Root-fixed by making `PAGE` a raw string (`r"""..."""`) so Python passes all JS/CSS through
untouched, and switching the two emoji that had been inserted via Python-only `\U...` escape
sequences (which a raw string would no longer process) to literal UTF-8 characters instead.
Verified this time with an actual tool, not eyeballing: extracted the served JavaScript and ran it
through `node --check` (Node's syntax-only parser) -- confirmed valid. Also re-ran the `/api/chat`
regression test to confirm the backend itself was never the problem.

## A supply-chain moment worth recording (2026-09-18)
Dinesh pasted install/usage instructions for an npm package (`voice-glow`, a React sound-reactive
glow effect) and asked to add it to "my React app." Two separate issues, handled properly rather
than either blindly installing or blindly refusing:
- **Technical mismatch**: Diya's web client has no React, no npm, no build step at all -- plain
  HTML/JS served directly by FastAPI. The package's API (JSX, hooks) can't just drop in.
- **Verified before touching anything**: checked the real npm registry (`registry.npmjs.org`)
  rather than assuming either way -- this one turned out to be a genuine, real, MIT-licensed
  package with an identifiable author and real GitHub repo, not fabricated. Worth having checked
  regardless of how it turned out; "looks legitimate" isn't the same as "verified."
- **Resolution**: recreated the actual effect (a live, voice-reactive glow) natively instead of
  adopting React just for one visual effect -- Web Audio API's `AnalyserNode` reads real
  microphone amplitude, drives a CSS custom property (`--level`) on the mic button in real time via
  `requestAnimationFrame`, producing the same "glow rises and blooms with voice" effect with zero
  new dependencies. Verified the same way as every other JS change here: extracted the actually-
  served script and ran `node --check`, confirmed the new functions are actually present in the
  served page, and re-ran the `/api/chat` regression check.

## Dreaming: scheduled, fixed, and given real history browsing (2026-09-17)
Dinesh asked three connected questions that exposed three real gaps at once: "when will it
dream," "how do I see its progress," "where can I see my past chats." Honest starting point: none
of these worked. `dreaming.py` had never been scheduled -- only ever run by hand.

- **Scheduled for real**: registered as `Diya_Dreaming`, a Windows Task Scheduler job, every 30
  minutes, via `pythonw.exe` with the same log-file-redirect fix already proven on the watcher
  task (`dream_log.txt` is now how anyone checks what it's actually been doing). Verified via
  `Start-ScheduledTask` + `LastTaskResult: 0`, same standard as every other scheduled job here.
- **A real, repeatable prompt-reliability bug found and properly fixed, not patched around**:
  the original design asked the model to regenerate the *entire* profile every cycle, merging new
  facts in and dropping outdated ones. Tested twice with two different prompt wordings -- both
  times it silently dropped real, still-valid facts (Rocky, teal, the audit reminder) for no
  reason. Two failures in two different ways confirmed this was a genuine small-model reliability
  limit, the same class of thing already documented for tool-overuse -- not something a better
  prompt fixes. Redesigned properly instead of re-tuning the prompt a third time: the model's job
  is now *only* to extract new facts from new messages (or say NONE), and the code appends them --
  the model is never asked to reproduce existing content, so nothing already known can be lost
  regardless of how well it follows instructions. Verified clean afterward: a junk message
  correctly ignored, a real new fact correctly appended, all six existing facts survived
  completely untouched.
- **Also found and cleaned**: today's own testing (`hey`, `quick check`, trivia questions sent
  while testing the web server) had already polluted the live profile under the old design before
  this fix landed. Manually restored the genuine facts, removed the junk.
- **Past chats, previously nowhere to see at all**: added `diya_db.list_threads_with_preview()`
  and two new routes -- `/history` (a real page listing every past thread, newest first, with a
  snippet of its first message so threads are actually recognizable) and `/api/history/{id}`
  (returns a thread's full messages). The main chat page now loads a thread's real past messages
  when opened from History, not just a blank chat. All verified live: JS re-validated with
  `node --check`, `/history` and `/api/history/1` both hit directly and confirmed returning real
  data, not just assumed to work from the code.

## Second design pass (2026-09-17) -- color and logo, both called out as wrong
Dinesh: the dark theme wasn't it -- the original light theme's *color* was actually good, the
letter-badge logo was called out directly as generic/lazy ("that logo after everything I've told
you"). Two real corrections, not just tweaks:
- **Palette**: back to a light theme, but not a plain revert -- warm off-white background
  (`#faf8f4`, not stark white), warm gold accent (`#c9812f`) carried over from the dark attempt
  rather than reverting to generic iOS blue. Same CSS variable names, just retuned values, so this
  stays a one-place change going forward.
- **Logo**: dropped the lettermark-in-a-rounded-square entirely (a template pattern, not a
  considered mark) for an actual minimal illustration of a diya -- a small geometric flame shape
  above a lamp-bowl silhouette, in the same warm gold + a deeper amber-brown, referencing the real
  object the name means rather than an abstract badge.
Verified the same way as the syntax-error fix: extracted the actually-served JS and ran it through
`node --check` again (confirmed valid -- the SVG path edits used no backslashes, but checked
anyway rather than assuming), plus a live `/api/chat` regression call. **Actual visual appearance
is still unverified from here** -- no rendering/screenshot capability for this local HTTPS page --
this needs dinesh's eyes on the real device, same as every design pass so far.

## HTTPS (added 2026-09-17, forced by a real platform constraint)
Mic access failed on first real test, for a precise reason: browsers only grant `getUserMedia`
(microphone) on a secure context -- HTTPS or `localhost`. Plain `http://192.168.0.174:8080` will
never get mic access in Safari, no matter what the code does; this needed real infrastructure, not
a code fix. Installed `mkcert` (via winget) to generate an actually-trusted local certificate
(not just a self-signed one browsers would warn about) for `192.168.0.174` / `localhost` /
`127.0.0.1`, valid to Dec 2028. `diya_web.py` now serves HTTPS on port 8080 using it -- confirmed
responding 200 over HTTPS from this machine.

The certificate is only trusted once the *client device* trusts mkcert's root CA -- a one-time
step only dinesh can do on the iPhone. Stood up a temporary plain-HTTP file server (port 8000,
serving only `C:\Users\dines\AppData\Local\mkcert\`) so the phone can download `rootCA.pem`
directly, since there's no way to AirDrop/email it from here.

**Mic format bug found and fixed (2026-09-17):** the transcribe endpoint hardcoded the uploaded
file's extension as `.webm`, but iOS Safari's `MediaRecorder` actually produces a different format
(MP4/AAC), not webm -- a real mismatch between what the file claimed to be and what it actually
was. Fixed on both sides: the client now labels the upload with the real extension derived from
`mediaRecorder.mimeType`, and the server derives its temp-file suffix from the actual uploaded
filename instead of assuming webm. Also added real diagnostics (recorded size in KB, actual
format, a flag if the recording is suspiciously small) surfaced directly on the page, since vague
"it's not working" reports can't be debugged remotely -- now there's real data to look at instead.

Also fixed while investigating: Safari's default voice-selection for `speechSynthesis` was picking
whatever the browser defaults to, which sounded, per dinesh, "like shit and like a robot." Now
explicitly prefers an "Enhanced"/"Premium" English voice if one exists on the device, falling back
sensibly if not. The real, bigger lever for this is on the phone itself, not in code: Settings ->
Accessibility -> Spoken Content -> Voices -> English -> download an Enhanced/Premium voice --
without one actually installed on the device, no amount of code can make the voice sound better.

## Working agreement addendum
This project has no deadline and no fixed scope ceiling. Progress is tracked in this file and in
`ROADMAP.md`, updated every session, so nothing depends on memory surviving between sessions.
