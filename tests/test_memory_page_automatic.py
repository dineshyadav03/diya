"""What the Memory page shows about memory that remembers on its own (docs/AUTO_MEMORY_DESIGN.md, D6 and unit A7), checked from its source, as the
other pages' wiring is: the state of the automatic memory in words (off, on with its numbers, paused by the circuit breaker), a mark on every fact
it took on its own, and Undo in place of Forget for exactly those. What the API sends is test_memory_api.py's; how it looks was checked in a real browser.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "app" / "memory" / "page.js").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "app" / "globals.css").read_text(encoding="utf-8")


def component():
    start = PAGE.index("function Automatic(")
    return PAGE[start:PAGE.index("function Why(")]


def test_the_page_tells_the_state_of_automatic_memory_from_the_summary_the_api_sends():
    assert "<Automatic automatic={summary.automatic} />" in PAGE
    assert "if (!automatic) return null" in component()  # an older API that sends nothing shows nothing, not a wrong thing


def test_when_it_is_off_the_page_says_so_in_the_plain_old_promise():
    assert "if (!automatic.on)" in component()
    assert "Automatic memory is off: nothing is remembered until you accept it." in component()


def test_when_it_is_on_the_page_says_what_it_took_what_was_taken_back_and_that_the_doubtful_waits():
    part = component()
    assert "{automatic.today} of {automatic.limit} allowed in the last day" in part and "{automatic.taken_back}" in part
    assert "waits below for you" in part


def test_a_paused_circuit_breaker_is_an_alert_with_its_reason():
    part = component()
    assert "automatic.breaker_open &&" in part and 'role="alert"' in part
    assert "you took back {automatic.taken_back} of its facts in the last day" in part and "asking about everything" in part


def test_a_fact_it_took_on_its_own_is_marked_and_offers_undo_not_forget():
    assert "{fact.by === 'auto' && <p className=\"memory-auto-tag\">Learned on its own</p>}" in PAGE
    assert re.search(r"fact\.by === 'auto'\s*\?\s*button\('Undo'", PAGE)
    assert "Undone: Diya will not use it from the next message." in PAGE
    assert "button('Forget'" in PAGE  # what a person accepted is still Forgotten, as before
    assert PAGE.count("'retire'") == 2  # Undo and Forget are both the same retirement: nothing new is deleted


def test_the_lede_no_longer_promises_that_nothing_but_your_accepting_is_ever_told_to_the_model():
    assert "Facts it finds in your conversations wait here until you accept them" not in PAGE
    assert "if automatic" in PAGE and "memory is on, the plain ones it took on its own, which are marked and can be undone here" in PAGE


def test_the_new_classes_exist_and_use_only_the_themes_variables():
    for name in (".memory-automatic", ".memory-auto-tag"):
        assert name in CSS, name
    block = CSS[CSS.index(".memory-automatic {"):CSS.index(".theme-label")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block)
