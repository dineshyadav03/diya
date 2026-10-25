# Things that must always be true (written 2026-10-25)

Most of Diya's tests check cases somebody thought of. This page lists the sentences that must hold for **every** case, and each one is checked against thousands of made-up cases by
`tests/test_invariants.py` (a fixed seed, so a failure can be run again exactly; `DIYA_FUZZ_SEEDS=50` tries many more). If a sentence here stops being true, a test fails and says which.

Written in plain words on purpose: if one of these is not what you want Diya to promise, say so and it changes.

## 1. What you say stays on this computer

- Whatever model address is set, Diya either uses an address whose host is this computer, **as two different programs reading the address would both see it**, or refuses to start with a plain message. Nothing else can happen.
  `tests/test_invariants.py::test_a_model_address_is_this_computer_as_every_reader_sees_it_or_it_is_refused_and_nothing_else_happens`
- An address with a space, a control character, a backslash, an `@` part or a bad port is refused too (unless you set `DIYA_ALLOW_REMOTE_MODEL=1`), because two programs can read such an address two ways.
  Same test. (Before 2026-10-25 an address like `http://evil.com\@localhost/` was let through; both readers happened to agree on its host, so it was not a live hole, but it was one wrong parser away from one.)

## 2. Only you get in

- A request is let in only if it has exactly one `Authorization` header, the `Bearer` scheme, and your token exactly. A longer token, a shorter one, one letter changed, a trailing space, another scheme, a
  second header (even with the right token in it), or the right words in a different header all get turned away.
  `tests/test_invariants.py::test_only_the_exact_token_in_exactly_one_bearer_header_gets_in`
- With no token stored, nothing is let in, not even the right words. `tests/test_invariants.py::test_with_no_stored_token_nothing_gets_in_even_the_right_words`

## 3. What is shown cannot hide anything

- Whatever text is given (a memory, a note, a model reply), what Diya shows is one line with no control, invisible or direction-changing character; a second pass over it changes nothing; clean text is shown as it is.
  `tests/test_invariants.py::test_whatever_text_is_given_what_is_shown_is_one_clean_line_that_a_second_pass_leaves_alone`
- This is checked against the **whole** Unicode table, not a sample: every invisible format character is shown as a visible escape. The test found that the "tag" block (U+E0020 and on, which can carry a hidden
  message), the soft hyphen, the invisible math operators and a few more were not on the list; they are now. Joiners that emoji and Indic scripts need, and script-specific marks, are deliberately left.
  `tests/test_invariants.py::test_every_invisible_format_character_there_is_is_shown_as_an_escape`
- The same characters cannot be stored in a memory. `tests/test_invariants.py::test_a_fact_cannot_carry_an_invisible_character_into_the_store`

## 4. The small model is not flooded or left looping

- A tool result is cut only when it is over the limit, always keeps its beginning and its end, never comes out longer than the cap, and is not cut twice; what is not text is not touched.
  `tests/test_invariants.py::test_a_long_result_is_cut_only_when_over_the_limit_keeps_both_ends_and_is_not_cut_twice`
- The "you are repeating yourself" reminder comes at exactly the third and fifth identical call in a row, however the arguments are ordered or written, and at no other time.
  `tests/test_invariants.py::test_the_repeating_reminder_comes_at_the_third_and_fifth_identical_call_in_a_row_and_only_then`

## 5. Nothing is done without your yes, and nothing is done twice

- Whatever order things happen in (approving the wrong thing, running what was never approved, running twice, a day passing, rejecting, saying what happened), an action's effect runs only if you approved it
  before its time was up, at most once; proposing never does anything; a finished action never changes; the store's own integrity check is clean after every move.
  `tests/test_invariants.py::test_an_effect_runs_only_for_an_action_approved_before_it_expired_and_at_most_once_whatever_the_order_of_moves`
  (Separate operating-system processes colliding on one database are checked in `tests/test_actions_multi_process.py`.)

## 6. "What did you know on that day?" is the truth

- For any moment, whatever sequence of adding, retiring and restoring led there, the answer is exactly the accepted facts as they stood at that moment, and asking writes nothing.
  `tests/test_invariants.py::test_what_it_knew_on_any_moment_is_exactly_the_accepted_facts_as_they_stood_then`

## What this does not prove

These are rules about Diya's own code. They do not prove the model server (Ollama) sends nothing out, that a connected service behaves, or that the 4B model answers well; those are measured elsewhere
(`docs/SCORECARD.md`). A random test can show a rule broken; it cannot show it can never break, only that thousands of tries found nothing. Invisible look-alike letters that are not "format" characters
(Hangul filler letters, the blank braille cell) are not on the invisible list, because they are real letters of real scripts; they are the next thing to look at if that matters to you.
