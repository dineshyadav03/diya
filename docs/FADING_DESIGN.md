# Facts that fade unless they are said again (2026-10-18)

Built from the second reading of supermemory (`docs/STUDY_SUPERMEMORY.md`, section 8): its open-source `company-brain` writes into memory with the rule *"decay unless reinforced"*, and Hindsight keeps a
*proof count and the exact quotes* behind each belief. Diya already retired a fact about a **day** once the day had passed (`diya_questions.retire_gone`). A fact about a passing **state** — "I'm reading Dune
these days", "for now I'm using the old laptop" — stayed in the profile for ever and was told to the model for ever. This closes that gap, narrowly.

## What the owner sees

* On the Memory page, a fact that sounds like a passing state says: *"This looks like a passing state, so it fades on 2026-12-02 unless you say it again or keep it."* with a **Keep** button.
* A fact that was said more than once says *"You said it again twice."*
* When the date comes, Dreaming retires the fact. It is **not deleted**: it shows as forgotten on the Memory page, and **Remember again** (Restore) brings it back, starting the clock afresh.
* "How do you know that?" says the same two things, from the record.

## The rule (code, not the model) — `diya_fade.py`

A fact fades only when its own words say it is a passing state:

| Words in the fact | Fades after (counted from the last time it was said) |
|---|---|
| "right now", "at the moment", "at present", "as of now" | 7 days |
| "for now", "for the time being", "for a while", "temporarily" | 45 days |
| "currently / these days / lately / nowadays" **next to an activity** (reading, working on, preparing for, …) | 45 days |
| "this semester / term / quarter" | 120 days |

Never fades: anything with "always, never, every, each, usually, used to, forever, since 2019, all my life"; and "currently lives in Pune", "currently works at the hospital", "currently has a dog" — a marker
word alone is not enough, the fact must also be about an *activity*. When two phrases match, the shortest decides. Anything the rule does not recognise does **not** fade: forgetting something that was meant
to last is worse than keeping something that has gone stale, so every doubt keeps the fact.

## Said again = counted, not dropped

When the person says something Diya already knows, the duplicate was always (correctly) rejected. Now the message is first recorded as a **mention** of the fact it repeats (`fact_mentions`, migration 23,
one row per fact and message). That renews a fact that would fade and is the evidence behind it. It happens on both paths a repeat can take: the check at staging (`duplicate:<id>` flag) and the accept-time
duplicate check. Nothing happens, and nothing fails, if the repeat's source message is not recorded or the earlier fact is not accepted.

## Keep, restore, and the record

* **Keep** (`POST /api/memory/{id}/keep`, event `kept`) ends the fading for good. A retire followed by a restore starts it again: the person is deciding anew to have the fact.
* Events `reinforced` and `kept` change no status; they are in the fact's trail like every other event. Dreaming's receipt (`dream_runs.faded`) counts the facts a pass retired; a pass that only faded
  facts is a *busy* pass, not an idle one.
* Only with automatic memory on: a Diya whose owner decides every fact by hand never has a fact retired for them, and the Memory page then promises no date (`Memory(fades=False)`, set by `open_memory`).

## Same change: the model is told when it is not told everything

`company-brain` ends a partial recall with *"Showing N of M+ matching memories — this is not the complete set"*. Diya's recall (docs/RECALL_DESIGN.md) already chose a subset when the store is bigger than the
room, but did not say so, so a fact left out could be read by the model as "never told". Now a partial view ends with a line saying how many facts are not shown and that "not listed" means "may not be in view".
Room for the line is reserved inside `MAX_PROFILE_CHARS` (`PARTIAL_NOTE_ROOM`), so the limit still holds.

## What was proved (tests/test_fade.py, tests/test_recall.py)

The rule on 9 passing and 12 lasting sentences, and on non-text; the clock running from the last mention; reinforcing once per message and only for an accepted fact; keep (twice, unknown, not accepted);
retire-not-delete and restore restarting the clock; a sentence said twice in a real chat becoming one fact with one mention; Dreaming retiring only what is due and counting it, doing nothing with automatic
memory off, and logging (not raising) a failure; the Memory route carrying `fades_on` and `said_again`; provenance wording; the proxy letting `keep` through; the partial-view note present only when facts are
omitted and always inside the limit.

## What was not proved

* That the rule suits the owner's real sentences. It was written from the supermemory policy and Diya's own examples, not from a measured sample of the owner's messages; it is narrow on purpose. After a
  month of real use, look at what faded (Activity → Dreaming receipts) and what should have.
* Nothing was run against the live database yet: the running Diya has the old code until it is restarted, and migration 23 (with the usual snapshot taken first) runs then.
