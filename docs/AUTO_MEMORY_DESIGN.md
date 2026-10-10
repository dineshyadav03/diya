# Memory that remembers on its own, and asks when it is unsure -- design spec

> **Status (2026-10-10):** designed; nothing built yet, and nothing here changes what the model is told until the switch in section 7 is
> turned on. The owner's instruction: "for memory the facts do not need to be accepted: the model can understand automatically, and if
> it is wrong the user will say so and the memory will be modified. This has to be so proactive that no model out there is that
> active. Build a reason it can activate itself to confirm something it has doubts about, and build some guard rails too."

## 1. What this changes, said plainly

Until now the rule was: **nothing reaches the model until the owner has read it** (Stage 2: Dreaming stages, the owner accepts, only
accepted facts are told to the model). The owner has decided that rule costs more than it protects: in real use the review queue was
never used, so the model has known **nothing** about the owner on every real conversation so far (the live `facts` table is empty).

The new rule is: **code decides, the owner can undo, and when code is unsure, Diya asks.** A fact now reaches the model when a policy
says it is safe, and the owner reviews afterwards instead of before: a feed of what was learned, one-press Undo, correction by simply
saying so in the chat, and questions Diya raises herself about what she is not sure of.

What it gives up, honestly: a wrong fact (or one planted by someone who can put words in front of the model) can steer answers until it
is noticed. Every guard rail below exists to keep that window small, visible and reversible. `RESEARCH.md` entry 17 is the reason the
guard rails are not optional: persistent memory is the thing an attacker most wants to write to.

## 2. What exists and is reused

`diya_memory.py` (facts, an append-only `fact_events` trail, four statuses: candidate, accepted, rejected, retired; one transaction per
change), `diya_checks.py` (deterministic flags: `no_source`, `ungrounded`, `instruction_shaped`, `duplicate`, `similar`,
`previously_rejected`), `diya_verifier.py` (the optional second opinion from the model: `verifier:yes|no|unclear`), `dreaming.py`
(extracts facts from the owner's own messages every 30 minutes and stages them), `diya_review.py ingest`, the Memory page, and the
scheduled task that runs Dreaming. Everything stays; the new work sits on top and uses the same events.

## 3. Decisions

### D1. Three lanes, decided by code, for every extracted fact

`diya_autonomy.decide(...)` puts each candidate in exactly one lane, from its flags, its words and what is already known:

- **REMEMBER** (accepted at once, by `actor = auto`): a plain statement about the owner or someone they named, grounded in the owner's own
  message, passing every check, in no sensitive class, not conflicting with an accepted fact, within the caps below.
- **ASK** (stays a candidate, and a question is opened, D5): grounded but doubtful (the verifier said "unclear", or the wording is a
  loose paraphrase), a possible update of an accepted fact (`similar`), or a sensitive class (D3). A fact about another person the owner
  named ("sister Maya is visiting in May") is remembered like any other; it is asked about only when it is sensitive ("Maya takes
  medication for asthma").
- **NEVER** (rejected, recorded, and never asked about): a credential or secret, anything instruction-shaped, anything the owner already
  rejected, anything with no source message of the owner's own, and anything that would break a cap.

The decision and its reasons are written to the trail with the fact, so "why did it remember this?" always has an answer.

### D2. Only the owner's own words are ever a source

A fact can come only from a message with role `user`, as now. Text that arrived through a tool (a web page, a note, a file, a weather
answer), anything the assistant wrote, and anything a connector returned is never a source, however it is worded. Nothing in this design
can be triggered by such text: a question is built from a fact the owner said, never from what a page said.

### D3. Sensitive classes are asked about, secrets are never kept

Deterministic detectors (patterns and word lists, tested on labelled cases, deliberately over-cautious):

- **Never kept:** passwords and passphrases, API keys and tokens, one-time codes, card and bank account numbers, government ID numbers,
  recovery phrases. The fact is dropped, the trail says "a secret was not kept", and the text of the secret is not stored in the trail.
- **Always asked first:** health and medication, money amounts and debts, legal matters, an exact home or workplace address, contact
  details (an e-mail address or phone number, whose they are), and beliefs (religion, orientation, politics, caste, ethnicity). The same
  rule applies whoever the fact is about.

### D4. Corrections by saying so

When a message corrects something ("no, I live in Pune", "that's wrong", "I don't like tea any more", "forget that I said X"), code finds
the accepted fact it concerns (the same similarity the checks use; ambiguous means ask which), retires it and records the new one in one
transaction (`Memory.supersede`), and the reply says exactly what changed ("Updated: lives in Pune. Was: lives in Delhi. Undo."). A
correction is recognised only in the owner's own message and only changes facts, never settings, reminders or tasks. "Forget that" and
"forget everything about <person>" retire; they do not delete (the trail stays), and a hard delete remains a deliberate command.

### D5. Diya raises questions herself: the reason to activate

A `memory_questions` queue, filled by code (never by the model writing prose to the owner), with four triggers:

1. **Doubt**: a fact landed in the ASK lane.
2. **Conflict**: a new statement contradicts or updates an accepted fact ("lives in Delhi" and now "moved to Pune").
3. **Staleness**: an accepted fact with a time horizon that has passed ("travelling next week", "exam on the 14th") is asked about once:
   "Is this still true?" (the horizon is read in code from dates and words like "next week").
4. **Offer**: a fact that names a dated commitment ("dentist Friday at 3pm") opens one offer, "Want a reminder for this?", that does
   nothing unless the owner says yes (then it makes an ordinary reminder, the existing local, visible feature).

Where it shows: at the top of a chat when it opens (an assistant message with Yes / No / Edit buttons), a card on the Today page, and, if
the owner wants it, the desktop notifier ("Diya has a question"; the question itself is not in the toast). Yes accepts the fact; No
rejects it and it is never asked again; Edit rewords it and accepts.

**Guard rails on questions, so she is proactive and not a nag:** at most 3 open at once; at most 2 new a day; none between 22:00 and
07:00 (settable); a question that is ignored waits 3 days and is dropped after two ignores (the fact stays unused, never accepted by
silence); the same fact is never asked twice; a question's wording is built by code from the fact's own text through
`diya_memory.printable`; and no question is ever opened for a secret.

### D6. The guard rails, all together

1. Sources: the owner's own messages only (D2).
2. Never-kept and always-asked classes (D3).
3. Instruction-shaped text, links and markup are never facts (the existing check, now a hard stop).
4. Caps: the existing 2000-character profile budget and 200 per fact, plus **at most 20 automatic acceptances a day**; over that, new
   facts wait in the ASK lane.
5. **A circuit breaker:** if the owner undoes, rejects or corrects 3 automatic facts in one day, automatic acceptance pauses (everything
   goes to ASK) until 24 hours have passed with fewer than 3 taken back (a rolling window, so it heals by itself), and the Memory page
   says so at the top.
6. **Undo for every automatic change**, one press, from the feed and from the chat reply that announced it; the trail keeps both.
7. **Visible**: automatic facts are tagged "learned on its own" on the Memory page with their source message, and today's are listed.
8. **A kill switch**: `DIYA_AUTO_MEMORY=0` and a toggle on the Memory page; off means exactly the Stage 2 behaviour.
9. **Everything is local and deterministic around the model**: the model proposes facts and may give an opinion; only code puts a fact
   in a lane, builds a question, or applies a correction.

### D7. How proactive, concretely

- **Live capture:** right after a chat turn whose message looks like a statement about the owner (`diya_intent`'s fact-share test, plus
  first-person statements), a short background extraction runs on that message and the lanes are applied within seconds, instead of
  waiting up to half an hour for Dreaming. Dreaming remains as the second pass over everything, and applies the same lanes.
- **Say what was learned:** the reply carries one quiet line ("Noted: ...  Undo") when something was remembered or changed.
- **Use it without being asked:** the accepted facts are in the model's context on every turn, as now.
- **Ask when unsure, offer when it helps** (D5).

### D8. The model, and how its mistakes are bounded

The model extracts, and (optionally) gives a second opinion. Its known weaknesses (it paraphrases, it invents, it can be steered by a
message) are bounded by code: grounding against the source message, the instruction check, the lanes, the caps, and the questions.
Measured before the switch is turned on (section 5), with the real models, because a policy that is only plausible is the failure this
project keeps finding. A better extractor makes the lanes fire less; `qwen3:4b-instruct` is the likelier choice for this job.

## 4. Units

| Unit | What | Files |
|---|---|---|
| A1 | **The policy** (built). `diya_autonomy.py`: the secret and sensitive detectors, `decide`, and `apply`; the `auto` actor, `Memory.discard_secret`, `count_events` and `taken_back_count` (the daily cap and the breaker are counted from the existing event trail, so no migration was needed); the trail records the lane and the reasons. The `memory_questions` table moves to A5 and live capture's tables to A4. | `diya_autonomy.py` (new), `diya_memory.py` |
| A2 | **Applied to what Dreaming stages** (built): after Dreaming's own pass, `Dreamer.remember_on_its_own()` takes in what is staged and puts every candidate through `apply`. Behind `DIYA_AUTO_MEMORY`, off until A6. | `dreaming.py`, `diya_config.py` |
| A3 | **Corrections**: `Memory.supersede`, the correction detector, the reply line with Undo. | `diya_memory.py`, `diya_intent.py`, `diya.py` |
| A4 | **Live capture**: background extraction after a fact-shaped message, the same lanes. | `diya.py`, `diya_autonomy.py` |
| A5 | **Questions**: the queue, the triggers, the limits, the API, the chat message, the Today card, the notifier line. | `diya_questions.py` (new), `diya_memory_api.py`, frontend |
| A6 | **Measurement** on labelled messages with the real models (`python diya_autonomy_bench.py`): how often a wrong fact is remembered, how often a right one is asked, whether any secret or instruction was kept (must be zero), question volume. Then the switch. | `diya_autonomy_bench.py`, `tests/labelled_autonomy.py` |
| A7 | **The Memory page**: the feed, Undo, the questions, the toggle and the breaker's state. | frontend, `diya_memory_api.py` |

## 5. How it is verified, and what "done" means

Each unit gets tests, then the mutation harness, as before. The policy has a **zero-tolerance list**: across the whole labelled set, and
every model, the number of secrets kept, instruction-shaped facts accepted, tool-sourced facts accepted and sensitive-class facts
accepted without a question must be **0**; if it is not, the switch stays off. Everything else is measured and reported, not promised.

## 6. What this does not do

It does not write to anything but memory (no actions, no sends), does not read anything the owner did not say to Diya, does not let a
model decide a lane, does not delete (it retires), and does not ask about secrets. Questions about other people's data are asked, never
assumed. It does not make the model's answers more correct by itself: it makes them better informed, and the owner can see exactly how.

## 7. What needs the owner's yes

- **The switch.** Built off; turned on only after A6 shows the zero-tolerance list at 0, and then it is the owner's call to leave it on.
- **The sensitive list** (D3) and the question limits (D5): the numbers are proposals (3 open, 2 a day, 22:00-07:00, 20 a day, a breaker at
  3); say which to change.
- **The model.** The extractor is the model Diya runs on. The 4B model is the likelier fit; switching it is a separate decision
  (`docs/MODEL_BENCHMARK.md`).
