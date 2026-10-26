# Short, plain replies, like Hark's (2026-10-26)

The owner put Diya's replies beside Hark's, side by side, and asked for Diya's to be short. Diya's had emoji, "Why? To help test my own system", "Want me to ...?", "Just say the word", a P.S. about the dog, a paragraph where a line would do, and an
opening "You're absolutely right and thank you for calling that out". This page says what was measured, what was changed, and what is still wrong.

## How it was measured

`python diya_style_bench.py` (`diya_style_bench.py`, cases in `tests/labelled_style.py`): 24 ordinary messages (a fact, a tip, an explanation, a little chat, the weather), put to the real model (`diya-chat`) the way the chat puts them: the persona in
front and a **made-up profile** of the person ("has a golden retriever named Rocky", "plays the guitar", "is studying AI", "lives in Nellore", "is allergic to peanuts"), temperature 0 and one seed. None of the messages is about the profile,
so a reply that brings it up is volunteering something nobody asked for. Twelve messages are *dev* (looked at and tuned on) and twelve are *held-out* (written before any change and looked at once, at the end). A reply is **clean** if it is not too long
for what was asked, has no emoji, does not end by offering more help, has no P.S., does not open with praise, has no heading, and does not bring up the profile (unless the message made that relevant: dinner and the allergy).

## What the first look found (before any change)

2 of 24 clean. Median reply **75 words**. 22 of 24 had an emoji, 17 were too long, **20 of 24 brought up the dog, the guitar or the studies for no reason** ("Rocky's been barking at the mailman again", "Perfect for a guitar session or a walk with Rocky! 🎸🐶",
"Why did the guitar go to therapy? ... Rocky would be the best therapist"). The cause is in what the model is told: a list of what it knows about the person, and "use what you know about the user".

## What was changed

1. **The persona says how to answer** (`diya.STYLE_RULES`): the answer first and then stop, under 60 words unless they ask for detail, a plain fact is one sentence, no emoji, no headings, no lists unless asked, no P.S., no praise for the question,
   no offer at the end, and never bring up their pets, hobbies, studies or home unless the question is about them. "Use what you know about the user" became "use it only when it changes the answer".
2. **A reminder straight after the list of facts** (`diya.PROFILE_REMINDER`): that list is background; an allergy matters when they ask what to eat, a pet or a hobby does not matter for a joke, a tip or a fact. Told only in the persona, the model still
   volunteered a fact in 9 of 24; with the reminder where a small model reads it last, 3 of 24.
3. **A tidy that only takes out** (`diya_intent.tidy_reply`): pictures (unless the person used one), a closing offer ("Want me to ...?", "Let me know if ...", "Just say the word", "I'm here to help"), a P.S., and a one-word praise or "you're right" at the
   start. It never rewrites, never touches a reply with a code block, never removes an offer that is the whole reply, and leaves every other word as the model wrote it. `diya.TIDY_REPLIES` switches it off.
   (A tidy that removed any sentence that mentioned a profile fact was **not** built: it would also remove "you are allergic to peanuts" from an answer about dinner, which is the one time it matters.)

## What it came to (the same 24 messages)

| | clean | median words | emoji | too long | closing offer | volunteered a fact |
|---|---|---|---|---|---|---|
| before | **2 of 24** | 75 | 22 | 17 | 2 | 20 |
| the style rules alone (first try) | 8 of 24 | 40 | 1 | 8 | 1 | 9 |
| the final persona (rules, 60 words, reminder), no tidy | 17 of 24 | 30 | 1 | 2 | 0 | 3 |
| **the final persona and the tidy (what the person reads)** | **19 of 24** | **30** | **0** | 2 | 0 | 3 |

Dev only (tuned on): 2 → 11 of 12 clean, median 66 → 22 words. **Held-out (never tuned on): 0 → 8 of 12 clean, median 112 → 38 words**, no emoji, 10 → 2 replies that volunteered a fact.

## Still wrong

- Four of the twelve held-out replies are not clean: two plain facts are two sentences where one would do ("Alexander Graham Bell invented the telephone in 1876. He was a Scottish-born inventor..."; the speed of light), a group-name suggestion that
  worked in "Rocky's golden retriever energy", and a calm-before-a-test tip that said "You're studying AI, so think of it like a system". (In the dev set, "give me a tip to focus" still said "Play your guitar between sessions".)
  The model is small and told twice; code cannot tell a relevant mention from an irrelevant one.
- The explanations are still the longest replies (about 75 to 85 words for "why is the sky blue"): shorter than before (244), longer than Hark's two lines.
- This is one model, one profile, one run of each message at temperature 0. A real day has a longer chat and a longer profile; the volunteering may be worse or better there. If a reply still brings something up, "Forget this" on that message and the
  Not helpful button are the tools; and the number to watch is in this page's table.
- The replies that code writes (calendar, mail report, proposals, "Done: ...") were already plain and are not touched.
- The persona goes on every turn, so tool routing was checked with it on (next section), which found a bigger problem than the style.

## What checking the routing found (and fixed)

Until now the held-out routing benchmark asked its messages with **no persona and no profile in front of the model**, which is not how the chat asks them: the chat always puts the persona and the list of what is known about the person first. Asked the chat's way,
the same 45 messages scored **41 of 45** with the old persona (and the real profile), and with the new style rules **39 of 45**: three questions about the person's own notes ("what did i write about the garden?", "what was my note about the laptop battery", "remind me
what i wrote about the vet") were answered "I don't have access to your notes" without calling the notes tool. The same model called it every time without the persona and the profile, and with the persona but **no** profile facts the old persona passed 4 of 4, the new
2 of 4: so both the facts and the stricter style make it answer from what it has instead of looking. Telling it in the persona to use its tools did not help (4 of 5 failed).

The fix is the project's own pattern, **code decides, the model words it** (`Agent._notes_search_note`, `diya_intent.notes_topic`): a question about the person's own notes ("what did i write about X", "did i note anything about X", "remind me what i wrote
about X") has its topic read by code, the notes are searched by code, and the model is asked once, with no tools, to word what was found (so what a note says cannot reach a tool). `tests/test_notes_by_code.py`.

The held-out routing benchmark now asks the chat's way too (`diya_heldout_bench.PROFILE_LINES`, a made-up profile, and `agent.with_profile`; a search made by code is counted as a call, with what was searched for). Under those conditions, with the final code:
**43 of 45, routing 43 of 45, answers 45 of 45**; notes 5 of 5. The two it misses are "the meeting is at 4pm tomorrow so ill be late for dinner" and "i need to finish chapter 5 before friday": the model *called* `add_reminder` / `add_task`, and the tool refused (nothing is saved:
the guard that code enforces), so the must-be-zero line holds, but it is a miss on routing. Without a persona it did not reach for them; with one it does, which is the same weakness as the notes one, in the other direction. These numbers are not comparable with the 42 of 45 in
docs/HELDOUT_BENCH.md, which was measured without the persona and the profile.

Also found on the way, and fixed in the tidy: with the new persona a plain fact ended "I'm smaller than cloud models like Claude or GPT, no fancy tricks, just facts" (the persona's honesty line, said unasked): that sentence is now taken out unless the person asked about the model.
