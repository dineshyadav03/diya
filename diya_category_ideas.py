"""New categories Diya suggests, and sorting the earlier chats (docs/ONE_CHAT_DESIGN.md, step 4).

Sorting never makes up a category (diya_categories). When a lot of what the person says is about something none of the categories describes well, such as school once exams and classes keep coming up,
Diya SUGGESTS one: a name and the messages it is about, shown to the person, who says yes (the category is made and those messages move into it) or no (the name is not suggested again).

Measured on a small model (2026-10-16), asking for the name AND the message numbers in one go gave a good name but a sloppy list, and it invented a topic when there was none ("Personal goals"). So the work
is split: the model is asked only for a NAME (or NONE); then, for each message, one narrow question, "is this mainly about <name>?", whose yes or no a small model answers far better than picking
numbers out of a list. Code counts the yeses: fewer than MIN_SUPPORT and nothing is suggested. The person decides.

`sort_earlier` puts the person's messages from before sorting existed in a category, the same way a new message is sorted (code first, then the model, then the one before it).
"""
from __future__ import annotations

import re

import diya_categories as cat

MIN_SUPPORT = 5  # fewer messages than this is not a topic
MIN_MESSAGES = 12  # with fewer than this to look at, nothing is suggested
MAX_LISTED = 120  # how many of the newest messages are looked at
MAX_MESSAGE_CHARS = 160


def name_prompt(listed, categories):
    """The question that asks for a name: the categories (name and meaning) and the numbered messages (`listed` is [text, ...])."""
    kinds = "\n".join(f"- {name}: {meaning}" if meaning else f"- {name}" for name, meaning in categories)
    numbered = "\n".join(f"{n}. {' '.join(str(text).split())[:MAX_MESSAGE_CHARS]}" for n, text in enumerate(listed, 1))
    return (
        "Below are messages that a person sent to their personal assistant. They are already sorted into these broad categories:\n" + kinds + "\n\n"
        f"What ONE more specific subject do at least {MIN_SUPPORT} of these messages share, that none of those categories describes well and that is narrower than they are "
        "(for example \"School\" for classes, exams and homework)? Greetings and tests of the assistant do not count.\n\n"
        "Answer with only the subject's name, one to three words, or with the word NONE.\n\n"
        f"{numbered}"
    )


def read_name(answer, taken):
    """The topic named, as a clean name, or None if the answer was NONE, was not a usable name, or is one of `taken` (lower case: the categories, names suggested before, the starter names)."""
    if not isinstance(answer, str) or not answer.strip():
        return None
    line = answer.strip().splitlines()[0].strip(" \"'`*.")
    line = re.sub(r"^(?:name|topic)\s*:\s*", "", line, flags=re.IGNORECASE).strip(" \"'`*.")
    if not line or line.lower() in ("none", "other", "no", "n/a"):
        return None
    try:
        name = cat.clean_name(line)
    except cat.CategoryError:
        return None
    return None if name.lower() in taken else name


def about_prompt(name, text):
    """The narrow question asked of each message."""
    shown = " ".join(str(text).split())[:cat.MAX_TEXT_CHARS]
    return (
        f"Message: \"{shown}\"\n\nDoes this message clearly talk about \"{name}\" itself (not just something that could loosely be related to it, and not a greeting, thanks or a request about the assistant)? "
        "Answer only yes or no."
    )


def says_yes(answer):
    return isinstance(answer, str) and answer.strip().lower().startswith("yes")


def _ask(client, model, prompt, max_tokens):
    reply = client.chat.completions.create(model=model, temperature=0, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
    return reply.choices[0].message.content


def suggest(book, client, model):
    """Look at the person's newest messages that no rule could place and, if one topic stands out that no category describes, keep a suggestion for the person to answer. Returns the suggestion's id,
    or None (nothing stood out, the model gave nothing usable, too few messages were about it, or a suggestion is already waiting). Messages the person put in a category themselves are not looked at."""
    if book.open_suggestions():
        return None
    candidates = book.recent_for_ideas(MAX_LISTED)
    if len(candidates) < MIN_MESSAGES:
        return None
    taken = {name.lower() for name, _ in book.categories()} | book.known_suggestion_names() | {name.lower() for name in book.starter_names()}
    name = read_name(_ask(client, model, name_prompt([text for _, text in candidates], book.categories()), 12), taken)
    if name is None:
        return None
    supporters = [message_id for message_id, text in candidates if says_yes(_ask(client, model, about_prompt(name, text), 3))]
    if len(supporters) < MIN_SUPPORT:
        return None
    return book.add_suggestion(name, supporters)


def sort_earlier(book, client, model, lock, progress=None, stop=lambda: False):
    """Sort every message of the person's that is in no category, oldest first. `lock` is held for one message at a time, so a chat in progress is never kept waiting for long. `progress(done, total)` is
    told after each. Returns how many were sorted."""
    todo = book.unsorted()
    done = 0
    for message_id, text in todo:
        if stop():
            break
        with lock:
            try:
                cat.sort(book, client, model, message_id, text, ())
            except cat.CategoryError:
                pass  # a message that vanished while this ran
        done += 1
        if progress:
            progress(done, len(todo))
    return done
