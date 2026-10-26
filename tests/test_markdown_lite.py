"""Bold, italic and code in the model's replies (frontend/lib/markdown-lite.mjs, frontend/app/page.js), added 2026-10-21.

Found when the real calendar answer showed **Winter Vacation for Students** with its stars: the chat drew replies as plain text. What this proves, under Node: **bold**, *italic* and `code` become parts the page
draws as <strong>, <em> and <code>; the reply from the screenshot reads as the bold titles it meant; anything not recognised stays exactly as written (an unmatched star, a "* item" bullet, an underscore as in
Lead Forward_A, a half-written **bold while it streams, an empty pair); what comes back is parts of text, never HTML, so a reply that contains "<b>" or "<script>" is only ever text (the page draws each part inside
its own element); the parts put back together are the original words minus only the marks; and the page draws assistant replies and the streaming reply through it and the person's own messages as they are.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "frontend" / "lib" / "markdown-lite.mjs"
PAGE = ROOT / "frontend" / "app" / "page.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

CODE = (
    "import { pathToFileURL } from 'node:url'\n"
    "const m = await import(pathToFileURL(process.argv[1]).href)\n"
    "process.stdout.write(JSON.stringify(m.inlineParts(JSON.parse(process.argv[2]))))\n"
)


def parts(text):
    result = subprocess.run(["node", "--input-type=module", "-e", CODE, str(MODULE), json.dumps(text)], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    return [(p["kind"], p["text"]) for p in json.loads(result.stdout)]


@needs_node
def test_bold_italic_and_code_become_parts():
    assert parts("a **b** c *d* e `f` g") == [("text", "a "), ("bold", "b"), ("text", " c "), ("italic", "d"), ("text", " e "), ("code", "f"), ("text", " g")]


@needs_node
def test_the_reply_from_the_screenshot_reads_as_the_bold_titles_it_meant():
    found = parts("- **Winter Vacation for Students** (15 days)\n  Starts 2020\n- **Orchestrate October'26**")
    assert [text for kind, text in found if kind == "bold"] == ["Winter Vacation for Students", "Orchestrate October'26"]
    assert "".join(text for _kind, text in found) == "- Winter Vacation for Students (15 days)\n  Starts 2020\n- Orchestrate October'26"


@needs_node
@pytest.mark.parametrize("text", [
    "* a bullet with no closing star", "* one\n* two\n* three", "a half-written **bold while it streams", "Lead Forward_A and snake_case_name", "2 * 3 * 4", "an empty pair **** and ``", "a lone * star",
    "<b>bold</b> and <script>alert(1)</script>", "line one\nline two",
])
def test_what_is_not_a_mark_stays_exactly_as_written(text):
    found = parts(text)
    assert "".join(t for _k, t in found) == text and {k for k, _t in found} <= {"text"}


@needs_node
def test_what_comes_back_is_text_never_markup():
    found = parts("**<b>x</b>** and `<script>alert(1)</script>`")
    assert found == [("bold", "<b>x</b>"), ("text", " and "), ("code", "<script>alert(1)</script>")]  # the angle brackets are still just characters, drawn as text by the page


@needs_node
@pytest.mark.parametrize("value", [None, 5, "", [], {}])
def test_anything_that_is_not_text_gives_no_parts(value):
    assert parts(value) == []


def test_the_page_draws_the_models_replies_and_the_streaming_one_through_it_and_the_persons_own_as_they_are():
    page = PAGE.read_text(encoding="utf-8")
    assert "from '../lib/markdown-lite.mjs'" in page and "function Inline" in page
    assert "{m.role === 'assistant' ? <Inline text={m.text} /> : m.text}" in page
    assert "<Inline text={streamText} />" in page
    assert "dangerouslySetInnerHTML" not in page


# ---- an address of Google's own in a reply is a link (2026-10-26: what Diya added to the owner's account is told with its address) ----------------------------------------------------------------

@needs_node
def test_a_google_address_in_a_reply_becomes_a_link_and_the_full_stop_after_it_is_not_part_of_it():
    assert parts("Made the folder. https://drive.google.com/drive/folders/abc123") == [("text", "Made the folder. "), ("link", "https://drive.google.com/drive/folders/abc123")]
    assert parts("See https://docs.google.com/document/d/x1y2z3/edit. Then stop") == [("text", "See "), ("link", "https://docs.google.com/document/d/x1y2z3/edit"), ("text", "."), ("text", " Then stop")]
    assert parts("https://google.com") == [("link", "https://google.com")]


@needs_node
@pytest.mark.parametrize("text", [
    "https://evil.example/x", "https://google.com@evil.example/x", "https://google.com.evil.example/x", "https://notgoogle.com/x", "https://evilgoogle.com", "http://drive.google.com/x", "https://google.com:evil@x.example",
    "ftp://drive.google.com/x", "javascript:alert(1) https://x.example",
])
def test_an_address_that_is_not_googles_stays_the_words_it_was(text):
    found = parts(text)
    assert "".join(t for _k, t in found) == text and "link" not in {k for k, _t in found}


@needs_node
def test_putting_the_parts_back_gives_the_original_words_even_with_a_link_between_marks():
    text = "**Done**: made `x` at https://drive.google.com/drive/folders/abc123, *check it*."
    found = parts(text)
    assert [k for k, _t in found if k != "text"] == ["bold", "code", "link", "italic"] and "".join(t for _k, t in found) == text.replace("**", "").replace("`", "").replace("*", "")


def test_the_page_draws_a_link_part_as_an_anchor_that_opens_elsewhere_without_the_opener():
    page = PAGE.read_text(encoding="utf-8")
    assert "part.kind === 'link'" in page and 'target="_blank" rel="noopener noreferrer"' in page
