# Ten acceptance journeys (2026-10-20, task DIYA-010)

What a person does, what they must see, and what has to go wrong gracefully. Each is a whole workflow through the real HTTP routes of one Diya with a scripted model and stand-ins for anything outside (Google),
in `tests/test_journeys.py`; a test there fails if a journey listed here has no test. They do not say how good a real model's answers are: `diya_evals.py` and the benches measure that.

| # | You do | You must see | What goes wrong, and what must still be true | Test |
|---|---|---|---|---|
| 1 | Tell Diya you got a dog named Hog | The Memory page lists it, marked as taken on her own; the very next message reaches the model with it | The model cannot be asked: the message is still saved | `tests/test_journeys.py::test_journey_1_tell_her_something_and_she_knows_it_on_the_next_turn` |
| 2 | Say "no, I now work as a nurse" | The old fact is retired, the new one accepted, the old words kept; one press puts the old one back | The judge is unsure: nothing is replaced on a guess | `tests/test_journeys.py::test_journey_2_correct_a_fact_and_take_the_correction_back` |
| 3 | Say "forget that I like tea", then delete it for good | It is retired (and restorable); after "forget for good" the words are not in the database file | Two equally likely facts: nothing is forgotten | `tests/test_journeys.py::test_journey_3_forget_something_and_then_forget_it_for_good` |
| 4 | Ask for a reminder "tomorrow at 5pm", tick it off | A real time read from your words; when you ticked it is kept | A time you never said, invented by the model, is refused: no reminder is saved with it | `tests/test_journeys.py::test_journey_4_a_reminder_by_your_own_words_and_the_day_you_ticked_it_off` |
| 5 | Add a task, tick it | It is listed, then moves to done | The same open task twice is refused | `tests/test_journeys.py::test_journey_5_a_task_is_added_listed_and_ticked_and_not_added_twice` |
| 6 | Say "every morning at 8am tell me the weather in Pune" | It is listed with its rule and next time; run now, the answer lands in the chat | (a run can only read: `tests/test_adversarial_suite.py`) | `tests/test_journeys.py::test_journey_6_an_automation_made_in_words_runs_and_leaves_its_answer_in_the_chat` |
| 7 | Ask for a Google Task, press Approve | A card with the exact words and nothing sent; after Approve it is sent once and read back | Google drops the connection after the request: "unknown", never sent again | `tests/test_journeys.py::test_journey_7_a_google_task_waits_for_your_press_is_sent_once_and_read_back` |
| 8 | Press Pause, then Resume | While paused an approved action does not run; after Resume it runs once | Pausing twice and resuming when not paused change nothing | `tests/test_journeys.py::test_journey_8_pause_stops_what_she_does_on_her_own_and_resume_lets_it_go_on` |
| 9 | Make a backup, restore it | The restored file holds the same facts and passes the memory's own check | A file that is not a database is refused; restoring never overwrites | `tests/test_journeys.py::test_journey_9_a_backup_is_checked_and_restoring_it_gives_back_what_was_there` |
| 10 | Export your memory (Markdown and a repository of notes), restore into a fresh Diya | The same facts, people and retired ones | A file that is not an export is refused; nothing there is changed | `tests/test_journeys.py::test_journey_10_memory_leaves_as_a_file_and_comes_back_as_it_was` |

**Not in the ten, and why:** Google Calendar and Gmail reads and every real-account step (never run for real), voice (no microphone in a test), and the phone channels. They are labelled *Untried* in
`docs/CAPABILITIES.md`, and a journey for each is the first thing to write when the owner tries one.
