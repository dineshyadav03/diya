# Person-tagged memory -- design spec

> **Status (2026-09-27):** designed; **M1 (storage) and M2 (Dreaming tags a person at extraction) built.** M3
> (the review surface groups by person) is not. An extension of Stage 2 (`docs/STAGE2_DESIGN.md`), not a
> new stage: it adds one property to a fact that already exists, reviewed the same way. Prompted by
> `RESEARCH.md` entry 10's companion research (a person-level-memory post, 2026-09-27): person-scoped files
> instead of a flat pile of facts.

## 1. What is true today

Every accepted fact sits in one flat list, told to the model as one system message
(`docs/STAGE2_DESIGN.md`). "Likes green tea" and "sister Maya is visiting in May" are stored, shown and
injected exactly alike: nothing records that the second one is about Maya, not the user. There is no
`person` column, no per-person grouping on the Memory page, and no notion of identity beyond a fact's own
text.

## 2. What the research actually gives Diya

The post argues flat memory is a real limitation and that a person-level layer (Muse's `wife.md`,
`coworker.md` pattern) fixes it. That diagnosis holds for Diya's own flat `facts` table. Two things in the
post do not transfer, and saying so plainly is the point:

- **The "cold start" problem it opens with is not Diya's problem.** That is a multi-tenant cloud system's
  problem (a brand-new user, no history yet). Dreaming already extracts within 30 minutes of the first
  message; there is no days-or-weeks gap to bootstrap past.
- **The proposed bootstrap (point a local agent at iMessage, WhatsApp, email and calendar history, cluster
  by person) does not apply.** Diya has no connectors (Later stage 3, blocked on the owner's own accounts).
  Its only source of facts is its own chat. There is nothing to bootstrap from that is not already flowing
  through Dreaming.

What does transfer, and is buildable now with what Diya already has: **tag each fact with who it is about**,
group the review page by person, and treat identity the way Stage 2 already treats everything else that
matters -- reviewed by a person, never silently inferred, never truly deleted.

The sharpest point in the post's replies is the one to design around, not the post itself: "a wrong merge
about a person is the one memory bug you can't re-derive your way out of" (a reply to the original post,
2026-09-26). A merge that turns out wrong, done automatically, has no way back if the two facts have already
mixed. Every decision below follows from taking that seriously.

## 3. Decisions

### D1. What identifies a person

**Recommendation: a plain name string, exactly as it was written, is the identity -- not a resolved
"person" entity with aliases.** `people.name` is the key (unique, case-folded for matching the way
`text_key` already folds fact text), not an opaque id with a separate name field. Diya has no email
addresses, phone numbers or multiple channels to reconcile (unlike the reply's "one person is N
identifiers" problem, which is about linking accounts across systems Diya does not have); the only
identifier that exists is what a person is called in the conversation. "Self" (the user) is a reserved name,
not a row -- most facts are about the user, and forcing every one of them through a person lookup for the
common case adds a join for no benefit.

### D2. Where the tag comes from

**Recommendation: Dreaming's extractor names the person when the fact says who it is about, in the same
list it already produces** ("- sister Maya is visiting in May" stays what it writes; the person comes from
a second field per fact in its JSON, not a change to the fact's own text). A fact with no named person
defaults to "self". This is one more field on an existing model call, not a second call: Dreaming already
reads the messages and produces a facts list; asking it to also say whose fact each one is is the same task
it is already doing, checked the same way (nothing here trusts the model's naming until a person accepts
the fact, exactly as nothing trusts its wording today).

**Rejected: resolving identity automatically** (matching "Maya" in one fact to "my sister" in another by
embedding similarity or a second model call). That is exactly the wrong-merge risk the reply names, and nothing
here needs it yet: two facts both tagged "Maya" are already grouped correctly without resolving whether
they mean the same Maya.

*As built (M1):* migration 4 adds `people` (`name`, a unique `name_key`) and a nullable `facts.person_id`.
`Memory` gains `people()` (name and current fact count, alphabetical by key), `set_person(fact_id, name,
actor)` and `merge_people(from_name, into_name, actor)`; `get()` and `facts()` now include each fact's
`"person"` (a name, or `None` for self). `None` means "self" everywhere a name is taken, the same way
`due_at=None` means "no time" for a reminder. A merge is refused from self (it would silently move every
untagged fact, not merge two named people) and never deletes the losing name's row -- a person left with
zero facts after a merge is the record that it happened, visible in `people()`, not gone. Neither operation
ever touches a fact's status: tagging or merging a candidate leaves it a candidate. 20 of 20 mutations
caught (two survivors on the first run were real gaps, now covered: the unique index on `name_key` had
never actually been hit at the SQL level, and every test had only ever retagged an already-accepted fact,
so a mutation that forced "retagged" to imply "accepted" was invisible until a candidate was tagged too).
The scheduled Dreaming task runs the working-tree files, so it applied migration 4 to the live `diya.db`
before this even landed (`people` table present, `person_id` on `facts`, integrity `ok`, the database's other
13 columns and rows byte-identical, checked on a copy). The running API needs a restart to use any of this.

*As built (M2):* Dreaming's extraction prompt asks for one more thing per fact, in the same bullet list it
already produces: if a fact names a specific person (not the user), end that line with their name in square
brackets ("- sister Maya is visiting in May [Maya]"); leave the brackets off a fact about the user or no one
in particular. Nothing about the extraction call changes beyond the prompt text -- one call, same as before.
`diya_memory.extract_person_tag` reads a trailing `[Name]` off a staged line at ingest time (not inside
Dreaming, which stays a producer of plain text lines, matching how it always has); `ingest_queue` strips it
before cleaning the fact's text, and passes the name to the now person-aware `add_candidate`. A name that
fails `check_person_name` (too long, a control character) is dropped -- the fact is kept as self, never lost
over an unusable tag, the same tolerance Dreaming's output has always been given.

Measured with the real model against 12 hand-written, fictional single- and multi-message batches (2 runs
each, `qwen2.5:3b`): of the messages naming a specific person, every one was tagged (Maya, Sam, Alex, James,
Priya, Kush, "mum" -- all 2 of 2). Of the messages about the user alone, most correctly got no tag, but on
two of them ("I have a dentist appointment on Tuesday", both runs; "I'm allergic to penicillin", one of two
runs) the model wrote the literal tag `[User]` -- reading its own instruction's word for "leave the brackets
off" as something to name instead, rather than actually leaving them off. Caught: `add_candidate` (and
`set_person`, `merge_people`) now treat "user" the same as "self" -- both mean no person, added specifically
because this was observed, not guessed at -- so a `[User]` tag ends up exactly where no tag would have:
`person` is `None`, and no bogus "User" row is ever created. Raw compliance with the instruction, before that
correction, was 19 of 24 fictional cases; after it, every case landed on the right outcome except one kind:
a fact naming a pet ("I adopted a cat named Pixel") was tagged as if the pet were a person (`[Pixel]`), both
runs. Left as it is: `people` has no notion of "human", and a person's own page for a named pet is not
obviously wrong for what this is for -- grouping facts by who or what they are about -- so this is recorded
as an observed, deliberate-for-now choice, not a bug, and the owner can say otherwise. 12 of 12 mutations
caught.

### D3. Merging two names

Two people almost always turn out to be the reviewer noticing "Maya" and "sister Maya" should be the same
person, not automatic clustering. **Recommendation: a person-level action, `merge(from_name, into_name,
actor)`, that re-tags every fact under `from_name` to `into_name` and records the merge as an event -- never
silently, never automatically, and never by deleting `from_name`.** A merge is reversible in the sense every
other change in Stage 2 is: nothing is destroyed, the event log says what moved and when, and re-tagging one
fact back undoes it. There is no automatic un-merge, the same way there is no automatic merge: a person
looks at both directions.

### D4. What the model is told

**No change.** The system message stays one list of accepted facts, exactly as `docs/STAGE2_DESIGN.md`'s
switch built it. Person tags are for review and, later, for finding facts by person; they are not (yet) a
change to what reaches the model, so this stays additive and low-risk on top of a part of Diya that already
works. Grouping the *prompt itself* by person (a `wife.md`-style separate block per person) is a real future
option once there are enough people tagged for it to matter, not part of this.

### D5. The review page

**Recommendation: the Memory page groups accepted facts by person** ("You", then each named person,
alphabetically), with a person's facts collapsed together the way retired/rejected facts already collapse
into `<details>`. A candidate still shows in one waiting list regardless of who it names; the person tag
only changes how *accepted* facts are organised, since that is where a flat pile is actually a problem
(nothing to browse until something is accepted).

## 4. What needs the owner's yes

- Whether Dreaming's extractor should be asked for a person field at all, given it is one more thing a
  small model can get wrong (a wrong person tag is not as costly as a wrong fact -- it can be corrected
  the same way a wrong fact can, by editing it before or after accepting -- but it is still the model
  guessing something new).
- Whether "self" should be a real, listable row (so it appears in the grouped view explicitly) or stay
  implicit as "no person tag" -- a detail, not a principle, but one that touches the schema.

## 5. Units

| Unit | What | Files |
|---|---|---|
| M1 | **Storage.** Migration 4: `people` table (`name` unique), `facts.person_id` (nullable, null means
self), the merge event kind. `Memory` gains `set_person`, `merge_people`, and `facts()`/`get()` return the
person's name. | `diya_db.py`, `diya_memory.py` |
| M2 | **Dreaming.** The extractor's prompt asks for an optional person name per fact; `ingest_queue` passes
it to `add_candidate`. Nothing changes for a queue record with no person field (existing staged records
still ingest). | `dreaming.py`, `diya_memory.py` |
| M3 | **Review surface.** The command line and the Memory page group by person; a `merge` command/route. |
`diya_review.py`, `diya_memory_api.py`, `frontend/app/memory` |

Each unit lands as its own commit, tested and mutation-checked on its own, in that order: M1 first because
M2 and M3 both need somewhere to put a person before they can show or extract one.
