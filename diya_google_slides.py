"""Google Slides on the decks Diya made: make a deck from an outline and add slides to it, each only when you approve the outline (DIYA-106 to -109; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Uses the narrow `drive.file` permission of the Drive (change) card, which only ever sees what Diya made: so these work on decks Diya made and cannot reach any other deck. (Reading ANY deck is the Drive read card: its text
comes back as numbered paragraphs.)

The outline is the preview (DIYA-109): the card carries every slide's title and bullets, whole, before anything is made, and the plan is checked after: the slide count must be what was asked for and each slide's title must read back
as proposed. Diya does not draw the slides to look at them, so how they LOOK is for the person to check in Slides; what it checks is the count and the words. Every slide uses one of Google's own layouts (title and body),
so the layout is always valid, and nothing is pasted in from elsewhere: no images, so there is no image licence to record (images are not built).

Written as one line: slides are separated by `||` and a slide's title and bullets by `|`, for example `Why revise | spaced practice | active recall || Plan | week 1: maths | week 2: physics`.

Importing this module has no side effects except naming what the Drive (change) card may ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import hashlib
import re

import diya_google_client as client
import diya_google_drive as gd
import diya_google_write as gw
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

CARD = gd.CHANGE
SLIDES = "https://slides.googleapis.com/v1/presentations"
MAX_SLIDES, MAX_BULLETS, TEXT_MAX = 12, 6, 150
_S = re.escape(SLIDES)

client.allow(CARD, "POST", _S)
client.allow(CARD, "GET", rf"{_S}/{gd.FID}")
client.allow(CARD, "POST", rf"{_S}/{gd.FID}:batchUpdate")


def parse_slides(text):
    """The outline as [(title, [bullets])]: slides separated by '||', a slide's title and bullets by '|'. InvalidArgs for none, too many, or text that is too long."""
    slides = []
    for chunk in str(text or "").split("||"):
        parts = [" ".join(p.split()) for p in chunk.split("|")]
        parts = [p for p in parts if p]
        if not parts:
            continue
        title, bullets = parts[0], parts[1:]
        if len(bullets) > MAX_BULLETS or any(len(p) > TEXT_MAX for p in parts):
            raise InvalidArgs(f"a slide has a title and at most {MAX_BULLETS} bullets of at most {TEXT_MAX} characters")
        slides.append((title, bullets))
    if not slides:
        raise InvalidArgs("there are no slides: write them as 'Title | bullet | bullet || Next title | bullet'")
    if len(slides) > MAX_SLIDES:
        raise InvalidArgs(f"at most {MAX_SLIDES} slides at a time")
    return slides


def _clean_outline(text):
    parse_slides(text)
    if diya_memory.printable(text) != text:
        raise InvalidArgs("the outline is one plain line")


def outline_words(slides, limit=140):
    return diya_memory.printable(" / ".join(title for title, _ in slides), limit)


def _ids(seed, n):
    stem = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:10]
    return f"diya_{stem}_{n}_s", f"diya_{stem}_{n}_t", f"diya_{stem}_{n}_b"


def _text_of(shape):
    return "".join(((e or {}).get("textRun") or {}).get("content", "") for e in (((shape or {}).get("text") or {}).get("textElements") or []))


def _titles(deck):
    """The title of each slide of a deck as Google returns it (the text of its title placeholder), in order."""
    out = []
    for slide in deck.get("slides") or []:
        title = ""
        for element in slide.get("pageElements") or []:
            shape = element.get("shape") or {}
            if (shape.get("placeholder") or {}).get("type") in ("TITLE", "CENTERED_TITLE"):
                title = _text_of(shape).strip()
                break
        out.append(title)
    return out


def _slide_requests(seed, start, slides):
    requests = []
    for n, (title, bullets) in enumerate(slides, start):
        slide_id, title_id, body_id = _ids(seed, n)
        requests.append({"createSlide": {"objectId": slide_id, "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                                         "placeholderIdMappings": [{"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id}, {"layoutPlaceholder": {"type": "BODY", "index": 0}, "objectId": body_id}]}})
        requests.append({"insertText": {"objectId": title_id, "text": title}})
        if bullets:
            requests.append({"insertText": {"objectId": body_id, "text": "\n".join(bullets)}})
    return requests


# ---- make a deck -----------------------------------------------------------------------------------------------------------------------------------------

def create_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("title", "slides")}
    if not gw._own_words(kept.get("title"), text):
        raise InvalidArgs("the deck's name must be one the user said; ask them what to call it")
    kept["slides"] = "||".join("|".join([t] + b) for t, b in parse_slides(kept.get("slides")))
    return kept, []


def create_validate(args):
    gw._only(args, {"title", "slides"}, "a Google Slides deck")
    gw._clean_title(args.get("title"), "a deck")
    _clean_outline(args.get("slides"))


def create_render(args):
    slides = parse_slides(args["slides"])
    return f"Make a new Google Slides deck called {diya_memory.printable(args['title'], 60)} with a title slide and {len(slides)} slide(s): {outline_words(slides)} (the whole outline is in the fields below)"


def create_execute(config, args):
    slides = parse_slides(args["slides"])
    made = client.as_json(client.send(config, CARD, gd.LABELS[CARD], "POST", SLIDES, body={"title": args["title"]}, doing="making the deck"))
    deck_id = made.get("presentationId")
    if not isinstance(deck_id, str) or not re.fullmatch(gd.FID, deck_id) or made.get("title") != args["title"]:
        raise ActionUncertain("Google answered, but not with the deck that was asked for, so it may or may not be in your Drive. Look in Google Drive, then record what you found.")
    link = f" https://docs.google.com/presentation/d/{deck_id}/edit"
    try:
        first = [e for s in (made.get("slides") or [])[:1] for e in (s.get("pageElements") or [])]
        requests = []
        for element in first:
            if ((element.get("shape") or {}).get("placeholder") or {}).get("type") in ("TITLE", "CENTERED_TITLE") and isinstance(element.get("objectId"), str):
                requests.append({"insertText": {"objectId": element["objectId"], "text": args["title"]}})
                break
        requests += _slide_requests(deck_id, 1, slides)
        client.send(config, CARD, gd.LABELS[CARD], "POST", f"{SLIDES}/{deck_id}:batchUpdate", body={"requests": requests}, doing="putting the slides in")
    except (ActionFailed, ActionUncertain) as exc:
        raise ActionUncertain(f"The deck was made but its slides could not be put in it ({exc}). It is here:{link}")
    try:
        found = client.read(config, CARD, gd.LABELS[CARD], f"{SLIDES}/{deck_id}")
    except client.GoogleError:
        raise ActionUncertain(f"Google said the deck was made, but reading it back to check did not work, so it is not confirmed. It is here:{link}")
    titles = _titles(found)
    if len(titles) != 1 + len(slides) or titles[1:] != [t for t, _ in slides]:
        raise ActionUncertain(f"Google said the deck was made, but reading it back showed {len(titles)} slide(s) or other titles instead of the {1 + len(slides)} that were asked for, so it is not confirmed. It is here:{link}")
    return f"Made the Google Slides deck {args['title']}: a title slide and {len(slides)} slide(s), the count and every title read back to check. How the slides look is for you to check in Slides.{link}"


# ---- add slides to a deck -------------------------------------------------------------------------------------------------------------------------

def add_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "slides")}
    kept["slides"] = "||".join("|".join([t] + b) for t, b in parse_slides(kept.get("slides")))
    return kept, []


def add_resolve(config, args, said):
    file = gd.find_file(config, args.get("name"), said, mime=gd.SLIDES)
    try:
        deck = client.read(config, CARD, gd.LABELS[CARD], f"{SLIDES}/{file['id']}")
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    count = len(deck.get("slides") or [])
    if count + len(parse_slides(args["slides"])) > 60:
        raise InvalidArgs("a deck made by Diya has at most 60 slides")
    return dict(gd._ref(file), slides=args["slides"], slide_count=count)


def add_validate(args):
    gw._only(args, {"name", "file_id", "version", "slides", "slide_count"}, "adding slides")
    if not isinstance(args.get("file_id"), str) or not re.fullmatch(gd.FID, args["file_id"]):
        raise InvalidArgs("a change needs the deck found by its name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("name"), "a deck")
    _clean_outline(args.get("slides"))
    if not isinstance(args.get("slide_count"), int) or isinstance(args.get("slide_count"), bool) or not 0 <= args["slide_count"] <= 60:
        raise InvalidArgs("how many slides the deck has is found by looking at it")


def add_render(args):
    slides = parse_slides(args["slides"])
    return f"Add {len(slides)} slide(s) to the end of the Google Slides deck {diya_memory.printable(args['name'], 60)} (now {args['slide_count']} slide(s)): {outline_words(slides)}"


def add_execute(config, args):
    gd._still_the_same(config, args)
    slides = parse_slides(args["slides"])
    try:
        deck = client.read(config, CARD, gd.LABELS[CARD], f"{SLIDES}/{args['file_id']}")
    except client.GoogleError as exc:
        raise ActionFailed(f"{exc} Nothing was done.")
    before = _titles(deck)
    if len(before) != args["slide_count"]:
        raise ActionFailed("The deck has a different number of slides than when this was proposed, so nothing was added. Look at it and ask again if you still want this.")
    client.send(config, CARD, gd.LABELS[CARD], "POST", f"{SLIDES}/{args['file_id']}:batchUpdate", body={"requests": _slide_requests(args["file_id"] + str(len(before)), len(before), slides)}, doing=f"adding slides to '{args['name']}'")
    try:
        after = _titles(client.read(config, CARD, gd.LABELS[CARD], f"{SLIDES}/{args['file_id']}"))
    except client.GoogleError:
        raise ActionUncertain("Google said the slides were added, but reading the deck back to check did not work, so it is not confirmed. Look in Google Slides, then record what you found.")
    if after != before + [t for t, _ in slides]:
        raise ActionUncertain("Google said the slides were added, but reading the deck back showed a different count or titles, so it is not confirmed. Look in Google Slides, then record what you found.")
    return f"Added {len(slides)} slide(s) to the Google Slides deck '{args['name']}' (now {len(after)}), the count and titles read back to check."


# ---- a deck from a Doc (DIYA-142) ----------------------------------------------------------------------------------------------------------------
#
# "make a deck from my Study plan doc": the Doc is named by the person (an explicit source), read by code through the Drive read card, and cut into an outline by code: the blocks of the Doc that are separated by a blank line
# become slides (a block's first line the title and the rest bullets; a one-line block followed by another is the title of the next one), a last slide names the Doc and its version, and nothing is added that the Doc does not say. The outline is
# then PROPOSED as a deck, so the card shows every slide before anything is made (the preview), and the proposal is marked as made after reading a file. Nothing is published or shared.

_FROM_DOC = (
    re.compile(r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*(?:make|create|build|turn|convert)\s+(?:me\s+)?(?:an?\s+)?(?:(?:(?:google\s+)?(?:slides?|deck|presentation)\s+){1,2})?(?:from|out\s+of|of)\s+(?:my\s+|the\s+)?(?P<name>[A-Za-z0-9][A-Za-z0-9 '&._-]{0,78}?)(?:\s+(?:google\s+)?(?:doc|document|file))?\s*\.?$", re.IGNORECASE),
    re.compile(r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*(?:turn|convert|make)\s+(?:my\s+|the\s+)?(?P<name>[A-Za-z0-9][A-Za-z0-9 '&._-]{0,78}?)\s+(?:google\s+)?(?:doc|document|file)\s+into\s+(?:an?\s+)?(?:(?:google\s+)?(?:slides?|deck|presentation))\s*\.?$", re.IGNORECASE),
)


def from_doc_request(text):
    """The name of the Doc a message wants made into a deck ("make a deck from my Study plan doc", "turn my Study plan doc into slides"), or None."""
    if not isinstance(text, str) or not text.strip() or len(text) > 200 or "\n" in text.strip():
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    for pattern in _FROM_DOC:
        found = pattern.search(flat)
        if found:
            name = " ".join(found.group("name").split()).strip(" .'-")
            if name and not re.fullmatch(r"(?:it|that|this|them)", name, re.IGNORECASE):
                return name
    return None


def outline_from_text(text, source_note):
    """The outline (see parse_slides) cut from a Doc's text by its blank lines, with a last slide that names the source. ValueError, in words, when there is nothing to make slides of."""
    blocks, current = [], []
    for line in str(text or "").splitlines():
        line = " ".join(line.split())
        if line:
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    slides, pending = [], None
    for block in blocks:
        if len(block) == 1 and len(block[0]) <= 60 and not block[0].endswith((".", ",", ";")) and pending is None:
            pending = block[0]  # a short line on its own: the title of the next block
            continue
        title, bullets = (pending, block) if pending is not None else (block[0], block[1:])
        pending = None
        slides.append((title[:TEXT_MAX], [b[:TEXT_MAX] for b in bullets[:MAX_BULLETS]]))
    if pending is not None:
        slides.append((pending[:TEXT_MAX], []))
    if not slides:
        raise ValueError("the document has no text to make slides from")
    slides = slides[:MAX_SLIDES - 1] + [("Source", [source_note[:TEXT_MAX]])]
    return "||".join("|".join([t] + b) for t, b in slides)


def deck_from_doc(config, name):
    """(the deck's name, its outline) for the Doc the person named, read through the Drive read card; ValueError, in words, when the Doc cannot be found, read or cut into slides."""
    file, why = gd._which_file(config, name)
    if why is not None:
        raise ValueError(str(why))
    if file.get("mimeType") != gd.DOC:
        raise ValueError(f"{diya_memory.printable(file['name'], 60)} is not a Google Doc, so it is not made into slides")
    try:
        text = client.read_text(config, gd.READ, gd.LABELS[gd.READ], f"{gd.FILES}/{file['id']}/export", {"mimeType": "text/plain"}, 6000)
    except client.GoogleError as exc:
        raise ValueError(str(exc))
    note = f"From the Google Doc {diya_memory.printable(file['name'], 60)} (version {diya_memory.printable(file.get('version', '?'), 12)}, changed {gd._day(file.get('modifiedTime'))})"
    return diya_memory.printable(file["name"], 100), outline_from_text(text, note)


# ---- the kinds ----------------------------------------------------------------------------------------------------------------------------------------

def _kind(name, label, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=CARD, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is done until the user approves it on the Actions page. It works only on decks Diya made.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


SLIDES_ARG = {"type": "string", "description": "The slides on one line: slides separated by '||', a slide's title and bullets by '|', for example 'Why revise | spaced practice | active recall || Plan | week 1: maths'. Plain words only."}


def action_kinds():
    return (
        _kind("google_slides_create", "Make a Google Slides deck", "propose_google_slides", "Propose making a new Google Slides deck from an outline. Use it only when the user asks for a deck or presentation.",
              {"title": {"type": "string", "description": "The deck's name, exactly as the user said it."}, "slides": SLIDES_ARG}, ["title", "slides"], validate=create_validate, render=create_render, execute=create_execute,
              asked=asks.asks_for_slides, prepare=create_prepare),
        _kind("google_slides_add", "Add slides to a Google Slides deck", "propose_add_slides", "Propose adding slides to the end of a deck Diya made. Use it only when the user asks to add slides to a deck, naming it.",
              {"name": {"type": "string", "description": "The deck's name, exactly as the user said it."}, "slides": SLIDES_ARG}, ["name", "slides"], validate=add_validate, render=add_render, execute=add_execute,
              asked=asks.adds_slides, prepare=add_prepare, resolve=add_resolve),
    )
