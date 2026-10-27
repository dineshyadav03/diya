"""A Google Doc that cites its sources and cannot make one up (DIYA-096; docs/GOOGLE_CHANGES.md), added 2026-10-27.

"Research how spaced practice works and put it in a Google Doc with sources." The model writes the text; code decides what may be cited:

* **A source is a web address that was actually seen.** Only an address that a web search showed in this same turn, or that the person typed in their message, can be a source. Any other address the model offers is not accepted, and a
  Doc whose text names an address that is not on that list is refused: so a source cannot be invented, only chosen from what was found.
* **A claim points to its source.** The text must cite with [1], [2] ... and every number must be one of the sources; a Doc with sources and no citation in the text, or a citation with no source, is refused.
* **The list is made by code.** The sources are added at the end of the text, numbered, exactly as accepted; the model does not write them.
* **Nothing is checked about the claims themselves.** That a page says what the text says it does is NOT established: the person reads the card, which carries the whole text and every address, before approving it. The card says so.
* It is the existing "make a Google Doc" (same card, same read-back), so it is a proposal the owner approves, never done straight away, and the text is at most what a Doc may carry from Diya.

Importing this module has no side effects.
"""
from __future__ import annotations

import re

import diya_google_write as gw
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionKind, InvalidArgs

MAX_SOURCES = 8
URL = re.compile(r"https?://[^\s)>\]\"'<]+", re.IGNORECASE)
CITE = re.compile(r"\[(\d{1,2})\]")


def urls_in(text):
    """The web addresses in a piece of text, cleaned of the punctuation that follows them, each once, in order."""
    found = []
    for match in URL.findall(text or ""):
        url = match.rstrip(".,;:!?")
        if len(url) <= 300 and url not in found:
            found.append(url)
    return found


def _same(url):
    return url.rstrip("/").lower()


def prepare(args, text, seen_urls=()):
    """The text and the sources the card will carry: the sources the model gave are kept only if a search showed them this turn or the person typed them; the text may name no other address and must cite with [n]."""
    allowed = {_same(u): u for u in list(seen_urls) + urls_in(text)}
    given = args.get("sources")
    requested = urls_in(given) if isinstance(given, str) else []
    kept = []
    for url in requested:
        if _same(url) in allowed and allowed[_same(url)] not in kept:
            kept.append(allowed[_same(url)])
    dropped = len(requested) - len(kept)
    if not kept:
        raise InvalidArgs("no source can be cited: a source is a web address that a search showed in this conversation turn, or that the user typed, and none of the addresses given was one (search the web first, or ask the user for the links)")
    body = args.get("body")
    if not isinstance(body, str) or not body.strip():
        raise InvalidArgs("the Doc needs its text")
    stray = [u for u in urls_in(body) if _same(u) not in allowed]
    if stray:
        raise InvalidArgs(f"the text names an address that was never found or given ({diya_memory.printable(stray[0], 60)}); cite with [1], [2] and let the sources list carry the addresses")
    numbers = {int(n) for n in CITE.findall(body)}
    if not numbers:
        raise InvalidArgs("the text must cite its sources with [1], [2] ...: a claim with no [n] is not tied to anything")
    if max(numbers) > len(kept) or min(numbers) < 1:
        raise InvalidArgs(f"the text cites [{max(numbers)}] but there are {len(kept)} source(s): cite only [1] to [{len(kept)}]")
    kept = kept[:MAX_SOURCES]
    listed = " Sources: " + " ".join(f"[{n}] {url}" for n, url in enumerate(kept, 1))
    full = " ".join(body.split()) + listed
    if len(full) > gw.BODY_MAX:
        raise InvalidArgs(f"the text with its sources is over {gw.BODY_MAX} characters; write it shorter (the sources list is never cut)")
    notes = [f"{dropped} address(es) the model offered as sources were left out because no search showed them."] if dropped else []
    return {"title": args.get("title"), "body": full}, notes


def render(args):
    body = " ".join(str(args.get("body", "")).split())
    return f"Make a new Google Doc called {diya_memory.printable(args['title'], 70)} with cited sources, starting with: {diya_memory.printable(body, 110)} (the whole text and every address are in the fields below; that a page says what the text claims is not checked)"


def action_kinds():
    return (ActionKind(
        name="google_docs_create_cited", label="Make a Google Doc with sources", connector="google_drive_files", validate=gw.doc_validate, render=render, execute=gw.doc_execute, asked=asks.asks_for_cited_doc, prepare=prepare, uses_urls=True,
        tool={"type": "function", "function": {
            "name": "propose_cited_google_doc",
            "description": ("Propose making a new Google Doc whose text cites its sources. Only web addresses that a web search showed this turn, or that the user typed, can be sources. This only PROPOSES it: nothing is made until the user approves it on the Actions page. "
                            "Use it only when the user asks for a Google Doc with sources."),
            "parameters": {"type": "object", "properties": {
                "title": {"type": "string", "description": "The document's title."},
                "body": {"type": "string", "description": "The text, on one line, citing its sources as [1], [2] ... Do not write the web addresses in the text."},
                "sources": {"type": "string", "description": "The web addresses cited, separated by spaces, each one a search result of this turn or typed by the user. [1] is the first."},
            }, "required": ["title", "body", "sources"]},
        }},
    ),)
