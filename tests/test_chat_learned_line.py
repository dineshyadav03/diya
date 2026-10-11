"""The quiet line under a reply (docs/AUTO_MEMORY_DESIGN.md, D7), checked from the chat page's source, as the other pages' wiring is: when it asks, how often and for how
long, what it says for each thing memory did, what it never says, what Undo is for each, and that a look which finishes after the chat was changed adds nothing.
How it looks was checked in a real browser against a throwaway API and database; what the API sends is test_corrections.py's.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")


def block(start, end):
    return PAGE[PAGE.index(start):PAGE.index(end, PAGE.index(start))]


def test_the_page_only_asks_when_the_api_says_memory_is_reading_the_message_and_gave_its_number():
    assert "if (data.reading && Number.isInteger(data.message_id)) watchLearned(data.message_id)" in PAGE


def test_it_asks_every_three_seconds_for_about_two_minutes_and_then_gives_up_quietly():
    assert "const LEARNED_EVERY_MS = 3000" in PAGE and "const LEARNED_GIVE_UP_AFTER = 40" in PAGE
    part = block("async function watchLearned", "async function undoLearned")
    assert "attempt < LEARNED_GIVE_UP_AFTER" in part and "setTimeout(resolve, LEARNED_EVERY_MS)" in part
    assert "if (!response.ok) return" in part and "} catch {\n        return" in part  # a failed look is dropped without a word


def test_it_keeps_asking_while_the_message_is_being_read_and_adds_a_line_only_if_something_was_made():
    part = block("async function watchLearned", "async function undoLearned")
    assert "if (body.reading) continue" in part and "if (body.items.length && epoch === chatEpochRef.current)" in part
    assert "role: 'learned'" in part and "if (!body || !Array.isArray(body.items)) return" in part


def test_a_look_that_finishes_after_the_chat_was_changed_adds_nothing_to_the_new_chat():
    part = block("async function watchLearned", "async function undoLearned")
    assert part.count("epoch !== chatEpochRef.current") == 1 and "const epoch = chatEpochRef.current" in part
    assert PAGE.count("chatEpochRef.current += 1") == 2  # a new chat, and the opening of a saved one


def test_each_thing_memory_did_is_said_in_its_own_words():
    part = block("function describeLearned", "let cachedVoices")
    assert "`Noted: ${item.text}.`" in part and "`Updated: ${item.text}. Was: ${item.old_text}.`" in part and "`Forgot: ${item.text}.`" in part
    assert "I wasn’t sure about something you said, so it is waiting for you on the Memory page." in part
    assert "I did not keep something that looked like a secret." in part


def test_what_is_left_waiting_or_not_kept_is_never_said_in_words_that_may_be_private():
    part = block("function describeLearned", "let cachedVoices")
    for kind in ("asked", "not_kept"):
        case = part[part.index(f"case '{kind}':"):]
        case = case[:case.index("case ", 5) if "case " in case[5:] else len(case)]
        assert "item.text" not in case and "item.old_text" not in case, kind


def test_undo_is_the_right_undo_for_each_kind_and_only_for_the_kinds_that_have_one():
    part = block("async function undoLearned", "async function sendMessage") if "async function sendMessage" in PAGE else PAGE[PAGE.index("async function undoLearned"):]
    assert "item.kind === 'replaced'" in part and "/api/memory/${item.id}/undo-replace" in part
    assert "/api/memory/${item.id}/${item.kind === 'forgot' ? 'restore' : 'retire'}" in part
    assert part.count("method: 'POST'") == 2
    assert "(item.kind === 'remembered' || item.kind === 'replaced' || item.kind === 'forgot')" in PAGE
    assert "item.kind === 'asked' &&" in PAGE and '<Link href="/memory"' in PAGE


def test_a_taken_back_line_says_so_and_cannot_be_taken_back_twice():
    assert "{item.undone ? 'Undone.' : describeLearned(item)}" in PAGE
    assert "if (!item || item.undone) return" in PAGE and "!item.undone && (item.kind ===" in PAGE
    assert "disabled={item.busy}" in PAGE


def test_a_refused_undo_says_why_in_the_pages_own_words_and_the_line_stays():
    part = PAGE[PAGE.index("async function undoLearned"):]
    assert "describeActionFailure(response.status, detail?.detail)" in part and "mark({ busy: false, problem:" in part
    assert 'className="learned-problem" role="alert"' in PAGE


def test_the_classes_exist_and_use_only_the_themes_variables():
    for name in (".learned-note", ".learned-line", ".learned-undo", ".learned-problem"):
        assert name in CSS, name
    lines = [line for line in CSS.splitlines() if line.startswith(".learned-")]
    assert lines and not any(re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", line) for line in lines)
