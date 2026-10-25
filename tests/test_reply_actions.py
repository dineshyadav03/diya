"""Copy and Ask again under each of Diya's replies (frontend/app/page.js renderRating / copyReply; DIYA-161 in part), added 2026-10-25.

What this proves, from the page's source (the real-browser check is the design rig's chat-feedback scenario, passed on desktop and phone width on 2026-10-25): both buttons are in the row under Diya's reply, before
the rating buttons; Copy puts exactly that reply's text on the clipboard and says whether it worked, because a browser may refuse; Ask again sends the same words the person wrote through the one send function
(so every guard of sending applies) and is off while Diya is working or the chat is not the one to write in; neither makes a request of its own, sends anything to the model or changes what is kept. It does not
cover editing a message, files, code blocks with their own copy button or citations, which the same sheet row names and are not built.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend" / "app" / "page.js").read_text(encoding="utf-8")
ROW = PAGE.split("function renderRating(serverId, reply) {", 1)[1].split("  // The person says a message belongs elsewhere", 1)[0]


def test_both_buttons_are_in_the_row_under_the_reply_before_the_rating():
    assert ROW.index("Copy") < ROW.index("Ask again") < ROW.index("Helpful") < ROW.index("Not helpful")
    assert ROW.count('<div className="msg-rate-row">') == 1 and "{replyTo !== null && renderRating(replyTo, { text: m.text, asked })}" in PAGE


def test_copy_puts_that_replys_own_text_on_the_clipboard_and_says_whether_it_worked():
    assert "navigator.clipboard.writeText(text)" in PAGE and "copyReply(serverId, reply.text)" in ROW
    body = PAGE.split("async function copyReply(key, text) {", 1)[1].split("  function renderRating", 1)[0]
    assert "catch {" in body and "ok = false" in body and "setCopied({ key, ok })" in body and "2000" in body  # a refusal is shown, and the word goes back after two seconds
    assert "Couldn’t copy" in ROW and "Copied" in ROW


def test_ask_again_sends_the_same_words_through_the_one_send_function_and_is_off_when_sending_is():
    assert "handleSend(reply.asked)" in ROW and "disabled={!canAsk}" in ROW and "{reply.asked && (" in ROW
    assert "const canAsk = !(thinking || stillAnswering || loadingChat || loadProblem || earlierChat)" in ROW
    assert "asked = typeof shownMessages[k].text === 'string' ? shownMessages[k].text : ''" in PAGE  # the person's own words, from the message the reply answers


def test_neither_button_makes_a_request_of_its_own():
    assert "fetch(" not in ROW and "fetch(" not in PAGE.split("async function copyReply(key, text) {", 1)[1].split("  function renderRating", 1)[0]


def test_the_design_rig_checks_the_buttons_in_a_real_browser():
    rig = (ROOT / "frontend" / "tools" / "design-rig" / "shots.mjs").read_text(encoding="utf-8")
    assert "every reply also has Copy and Ask again, as real buttons, before the rating" in rig
