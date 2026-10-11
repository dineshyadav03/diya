"""The cards at the top of the chat (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5), checked from the chat page's source, as the other pages' wiring is: when the page asks
what Diya wants to ask, what it tells the server was shown, how an answer and an edit are sent, what happens when one is refused, and that the words and the answers on a
card are the ones the server made. How it looks was checked in a real browser against a throwaway API; what the API sends is test_questions_api.py's.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")


def block(start, end):
    return PAGE[PAGE.index(start):PAGE.index(end, PAGE.index(start))]


def test_the_page_asks_for_questions_when_it_opens_and_again_after_each_reply():
    assert "    else setReady(true)\n    loadQuestions()" in PAGE
    assert "const QUESTIONS_AFTER_REPLY_MS = 20000" in PAGE and "setTimeout(loadQuestions, QUESTIONS_AFTER_REPLY_MS)" in PAGE


def test_a_failed_look_shows_nothing_and_a_list_that_is_not_a_list_is_ignored():
    part = block("async function loadQuestions", "async function answerQuestion")
    assert "if (!response.ok) return" in part and "if (!body || !Array.isArray(body.questions)) return" in part
    assert "} catch {\n      // nothing to show\n    }" in part


def test_what_was_put_in_front_of_the_person_is_reported_by_number_and_only_when_there_is_something():
    part = block("async function loadQuestions", "async function answerQuestion")
    assert "if (body.questions.length) {" in part and "fetch('/api/questions/seen', {" in part
    assert "JSON.stringify({ ids: body.questions.map((question) => question.id) })" in part and ".catch(() => undefined)" in part


def test_an_answer_is_sent_as_the_answer_alone_or_with_the_text_of_an_edit():
    part = block("async function answerQuestion", "async function watchLearned") if "async function watchLearned" in PAGE else PAGE[PAGE.index("async function answerQuestion"):]
    assert "`/api/questions/${question.id}/answer`" in part and "method: 'POST'" in part
    assert "JSON.stringify(text === undefined ? { answer } : { answer, text })" in part


def test_after_an_answer_the_cards_are_asked_for_again_and_the_edit_box_closes():
    part = PAGE[PAGE.index("async function answerQuestion"):]
    part = part[:part.index("  // Ask, a few seconds at a time")] if "  // Ask, a few seconds at a time" in part else part
    assert "setEditing(null)" in part and "await loadQuestions()" in part


def test_a_refused_answer_says_why_in_the_pages_own_words_and_the_card_stays():
    part = block("async function answerQuestion", "async function watchLearned")
    assert "setQuestionProblem(describeActionFailure(response.status, detail?.detail))" in part and "setQuestionProblem(describeActionFailure())" in part
    assert 'className="learned-problem" role="alert"' in PAGE and "{questionProblem && (" in PAGE
    first_return = part.index("return", part.index("if (!response.ok)"))
    assert "setAnswering(null)" in part[part.index("if (!response.ok)"):first_return]  # the buttons are usable again


def test_the_words_and_the_answers_on_a_card_are_the_ones_the_server_made():
    assert "<p className=\"question-text\">{question.text}</p>" in PAGE
    assert "{question.options.map((option) => (" in PAGE and "{option.label}" in PAGE and "onClick={() => (option.answer === 'edit' ?" in PAGE
    assert "I am not sure" not in PAGE and "looks private" not in PAGE  # nothing a question says is written in the page


def test_the_main_answer_is_the_main_button_and_a_card_is_unusable_while_its_answer_is_on_its_way():
    assert "className={option.answer === 'yes' ? 'cta small' : 'quiet-btn'}" in PAGE and "disabled={answering === question.id}" in PAGE
    assert "setAnswering(question.id)" in PAGE


def test_an_edit_needs_some_words_and_is_sent_only_from_its_own_form():
    assert "setEditing({ id: question.id, text: '' })" in PAGE
    assert "disabled={answering === question.id || !editing.text.trim()}" in PAGE
    assert "answerQuestion(question, 'edit', editing.text)" in PAGE and "event.preventDefault()" in PAGE
    assert 'htmlFor={`question-edit-${question.id}`}' in PAGE and "autoFocus" in PAGE


def test_the_cards_are_a_labelled_region_at_the_top_of_the_log_and_only_when_there_are_some():
    assert PAGE.index('<div id="log" ref={logRef}>') < PAGE.index('aria-label="Questions from Diya"') < PAGE.index("{ready && messages.length === 0")
    assert "{questions.length > 0 && (" in PAGE


def test_the_card_classes_exist_and_use_only_the_themes_variables():
    names = (".question-cards", ".question-card", ".question-text", ".question-actions", ".question-edit")
    lines = [line for line in CSS.splitlines() if line.startswith(names)]
    assert len(lines) == len(names) and not any(re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", line) for line in lines)
