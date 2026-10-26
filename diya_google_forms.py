"""Google Forms: read a form's questions and its answers, and make a form or add questions to one Diya made, each change only when you approve it (DIYA-114 to -117; docs/GOOGLE_CHANGES.md), added 2026-10-27.

No new Google permission and no new card. Google's own table of which permission may call which Forms request lets `drive.readonly` (the Drive read card) read any form's questions and its answers, and `drive.file` (the Drive change
card) make a form and change a form that the app made. So:

* **Reading** is part of the Drive look-through (diya_google_drive): "read my Feedback form" lists its questions; "show the responses to my Feedback form" lists how many answers came and what each said. It is code, the answers are
  other people's words (so the Drive is read with a model that has no tools), and **the respondent's email address is never shown**: only when each answer came and what it said (DIYA-117). At most 20 answers, each cut short.
* **Making** a form, and **adding questions** to a form Diya made, are proposals the owner approves exactly as shown: the card carries every question and its kind (a short answer, a paragraph, one choice, several choices). A form
  is read back after: its title, the number of questions and each question's title must be as proposed. Diya never shares, publishes or links a form to anyone and never turns on collecting email addresses; whether the link works
  for other people follows Google's own default for a new form, and the result gives only the address of the form in the owner's account.

Written as one line: questions are separated by `||` and a question's words, its kind and its choices by `|`, for example `How did you hear of us? | choice | a friend | an ad || Any comments? | paragraph`.

Not built: editing or deleting a question, a quiz, sections, images, and anything on a form Diya did not make. Importing this module has no side effects except naming what the Drive cards may ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import re

import diya_google_client as client
import diya_google_drive as gd
import diya_google_write as gw
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

FORMS = "https://forms.googleapis.com/v1/forms"
FORM_TYPE = "application/vnd.google-apps.form"
MAX_QUESTIONS, MAX_CHOICES, TEXT_MAX = 12, 8, 150
SHOWN_RESPONSES, ANSWER_MAX = 20, 200
KINDS = {"text": "a short answer", "paragraph": "a paragraph", "choice": "one choice", "checkbox": "several choices"}
_F = re.escape(FORMS)

client.allow(gd.READ, "GET", rf"{_F}/{gd.FID}")
client.allow(gd.READ, "GET", rf"{_F}/{gd.FID}/responses")
client.allow(gd.CHANGE, "POST", _F)
client.allow(gd.CHANGE, "GET", rf"{_F}/{gd.FID}")
client.allow(gd.CHANGE, "POST", rf"{_F}/{gd.FID}:batchUpdate")


def parse_questions(text):
    """[(question, kind, [choices])] from the line a card carries: questions separated by '||', a question's words, kind and choices by '|'. InvalidArgs for none, too many, or text that is too long or the wrong shape."""
    questions = []
    for chunk in str(text or "").split("||"):
        parts = [" ".join(p.split()) for p in chunk.split("|")]
        parts = [p for p in parts if p]
        if not parts:
            continue
        words, kind, choices = parts[0], (parts[1].lower() if len(parts) > 1 else "text"), parts[2:]
        if kind not in KINDS:
            raise InvalidArgs(f"a question's kind is one of: {', '.join(KINDS)}")
        if kind in ("choice", "checkbox") and not 2 <= len(choices) <= MAX_CHOICES:
            raise InvalidArgs(f"a question with choices has 2 to {MAX_CHOICES} of them")
        if kind in ("text", "paragraph") and choices:
            raise InvalidArgs("a question that is answered in words has no choices")
        if len(words) > TEXT_MAX or any(len(c) > TEXT_MAX for c in choices):
            raise InvalidArgs(f"a question and a choice are at most {TEXT_MAX} characters")
        questions.append((words, kind, choices))
    if not questions:
        raise InvalidArgs("there are no questions: write them as 'Your name? | text || How did you hear of us? | choice | a friend | an ad'")
    if len(questions) > MAX_QUESTIONS:
        raise InvalidArgs(f"at most {MAX_QUESTIONS} questions at a time")
    return questions


def _line(questions):
    return "||".join("|".join([words, kind] + choices) for words, kind, choices in questions)


def _clean_line(text):
    parse_questions(text)
    if diya_memory.printable(text) != text:
        raise InvalidArgs("the questions are one plain line")


def _request(words, kind, choices, index):
    question = {"required": False}
    if kind == "text":
        question["textQuestion"] = {"paragraph": False}
    elif kind == "paragraph":
        question["textQuestion"] = {"paragraph": True}
    else:
        question["choiceQuestion"] = {"type": "RADIO" if kind == "choice" else "CHECKBOX", "options": [{"value": c} for c in choices]}
    return {"createItem": {"item": {"title": words, "questionItem": {"question": question}}, "location": {"index": index}}}


def _kind_of(item):
    question = ((item.get("questionItem") or {}).get("question") or {})
    if "choiceQuestion" in question:
        return "choice" if question["choiceQuestion"].get("type") == "RADIO" else "checkbox"
    if "textQuestion" in question:
        return "paragraph" if question["textQuestion"].get("paragraph") else "text"
    return "other"


def _titles(form):
    return [str(item.get("title") or "") for item in form.get("items") or [] if isinstance(item, dict) and item.get("questionItem")]


# ---- reading a form and its answers (the Drive read card) -----------------------------------------------------------------------------------------------

def render_form(config, form_id, name):
    """The questions of a form as numbered lines, by code; a GoogleError for a problem."""
    form = client.read(config, gd.READ, gd.LABELS[gd.READ], f"{FORMS}/{form_id}")
    lines = []
    for number, item in enumerate([i for i in form.get("items") or [] if isinstance(i, dict) and i.get("questionItem")][:40], 1):
        kind = _kind_of(item)
        options = [str(o.get("value", "")) for o in (((item.get("questionItem") or {}).get("question") or {}).get("choiceQuestion") or {}).get("options") or [] if isinstance(o, dict)]
        lines.append(f"[Q{number}] {diya_memory.printable(item.get('title') or '(no title)', 150)} ({KINDS.get(kind, 'another kind of question')}" + (f": {', '.join(diya_memory.printable(o, 40) for o in options[:8])}" if options else "") + ")")
    title = diya_memory.printable((form.get("info") or {}).get("title") or name, 100)
    return f"{title} (Google Form, {len(lines)} question(s))\n" + ("\n".join(lines) if lines else "It has no questions.")


def render_responses(config, form_id, name):
    """How many answers a form has and what each said, by code, without the respondent's email address; at most 20, each cut short. A GoogleError for a problem."""
    form = client.read(config, gd.READ, gd.LABELS[gd.READ], f"{FORMS}/{form_id}")
    questions = {}
    for number, item in enumerate([i for i in form.get("items") or [] if isinstance(i, dict) and i.get("questionItem")], 1):
        question_id = ((item.get("questionItem") or {}).get("question") or {}).get("questionId")
        if isinstance(question_id, str):
            questions[question_id] = (number, diya_memory.printable(item.get("title") or "", 60))
    answered = client.read(config, gd.READ, gd.LABELS[gd.READ], f"{FORMS}/{form_id}/responses", {"pageSize": SHOWN_RESPONSES})
    responses = [r for r in answered.get("responses") or [] if isinstance(r, dict)]
    title = diya_memory.printable((form.get("info") or {}).get("title") or name, 100)
    if not responses:
        return f"{title}: no one has answered yet."
    lines = [f"{title}: {len(responses)} answer(s)" + (" shown (there may be more)" if len(responses) >= SHOWN_RESPONSES or answered.get("nextPageToken") else "") + "; the respondent's email address is never shown."]
    for number, response in enumerate(responses[:SHOWN_RESPONSES], 1):
        said = []
        for question_id, answer in sorted((response.get("answers") or {}).items(), key=lambda kv: questions.get(kv[0], (999, ""))[0]):
            values = [str(a.get("value", "")) for a in ((answer or {}).get("textAnswers") or {}).get("answers") or [] if isinstance(a, dict)]
            label = questions.get(question_id, (0, "?"))
            said.append(f"Q{label[0]} {', '.join(diya_memory.printable(v, ANSWER_MAX) for v in values) or '(blank)'}")
        lines.append(f"- {diya_memory.printable(response.get('createTime') or '', 20)[:16].replace('T', ' ')}  " + "; ".join(said))
    return "\n".join(lines)


# ---- make a form -------------------------------------------------------------------------------------------------------------------------------------

def create_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("title", "questions")}
    if not gw._own_words(kept.get("title"), text):
        raise InvalidArgs("the form's name must be one the user said; ask them what to call it")
    kept["questions"] = _line(parse_questions(kept.get("questions")))
    return kept, []


def create_validate(args):
    gw._only(args, {"title", "questions"}, "a Google Form")
    gw._clean_title(args.get("title"), "a form")
    _clean_line(args.get("questions"))


def _outline(questions):
    return "; ".join(f"{words} ({KINDS[kind]})" for words, kind, _ in questions)


def create_render(args):
    questions = parse_questions(args["questions"])
    return f"Make a new Google Form called {diya_memory.printable(args['title'], 60)} with {len(questions)} question(s): {diya_memory.printable(_outline(questions), 150)} (it is not shared with anyone)"


def create_execute(config, args):
    questions = parse_questions(args["questions"])
    made = client.as_json(client.send(config, gd.CHANGE, gd.LABELS[gd.CHANGE], "POST", FORMS, body={"info": {"title": args["title"], "documentTitle": args["title"]}}, doing="making the form"))
    form_id = made.get("formId")
    if not isinstance(form_id, str) or not re.fullmatch(gd.FID, form_id) or (made.get("info") or {}).get("title") != args["title"]:
        raise ActionUncertain("Google answered, but not with the form that was asked for, so it may or may not be in your Drive. Look in Google Drive, then record what you found.")
    link = f" https://docs.google.com/forms/d/{form_id}/edit"
    try:
        client.send(config, gd.CHANGE, gd.LABELS[gd.CHANGE], "POST", f"{FORMS}/{form_id}:batchUpdate", body={"requests": [_request(w, k, c, n) for n, (w, k, c) in enumerate(questions)]}, doing="putting the questions in")
    except (ActionFailed, ActionUncertain) as exc:
        raise ActionUncertain(f"The form was made but its questions could not be put in it ({exc}). It is here:{link}")
    try:
        found = client.read(config, gd.CHANGE, gd.LABELS[gd.CHANGE], f"{FORMS}/{form_id}")
    except client.GoogleError:
        raise ActionUncertain(f"Google said the form was made, but reading it back to check did not work, so it is not confirmed. It is here:{link}")
    if _titles(found) != [w for w, _, _ in questions]:
        raise ActionUncertain(f"Google said the form was made, but reading it back showed other questions than the {len(questions)} that were asked for, so it is not confirmed. It is here:{link}")
    return f"Made the Google Form {args['title']} with {len(questions)} question(s) and read it back to check (the number and every question). It is not shared with anyone.{link}"


# ---- add questions to a form Diya made -----------------------------------------------------------------------------------------------------------------

def add_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "questions")}
    kept["questions"] = _line(parse_questions(kept.get("questions")))
    return kept, []


def add_resolve(config, args, said):
    file = gd.find_file(config, args.get("name"), said, mime=FORM_TYPE)
    try:
        form = client.read(config, gd.CHANGE, gd.LABELS[gd.CHANGE], f"{FORMS}/{file['id']}")
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    count = len(_titles(form))
    if count + len(parse_questions(args["questions"])) > 50:
        raise InvalidArgs("a form made by Diya has at most 50 questions")
    return dict(gd._ref(file), questions=args["questions"], question_count=count)


def add_validate(args):
    gw._only(args, {"name", "file_id", "version", "questions", "question_count"}, "adding questions")
    if not isinstance(args.get("file_id"), str) or not re.fullmatch(gd.FID, args["file_id"]):
        raise InvalidArgs("a change needs the form found by its name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("name"), "a form")
    _clean_line(args.get("questions"))
    if not isinstance(args.get("question_count"), int) or isinstance(args.get("question_count"), bool) or not 0 <= args["question_count"] <= 50:
        raise InvalidArgs("how many questions the form has is found by looking at it")


def add_render(args):
    questions = parse_questions(args["questions"])
    return f"Add {len(questions)} question(s) to the end of the Google Form {diya_memory.printable(args['name'], 60)} (now {args['question_count']}): {diya_memory.printable(_outline(questions), 150)}"


def add_execute(config, args):
    gd._still_the_same(config, args)
    questions = parse_questions(args["questions"])
    try:
        before = _titles(client.read(config, gd.CHANGE, gd.LABELS[gd.CHANGE], f"{FORMS}/{args['file_id']}"))
    except client.GoogleError as exc:
        raise ActionFailed(f"{exc} Nothing was done.")
    if len(before) != args["question_count"]:
        raise ActionFailed("The form has a different number of questions than when this was proposed, so nothing was added. Look at it and ask again if you still want this.")
    client.send(config, gd.CHANGE, gd.LABELS[gd.CHANGE], "POST", f"{FORMS}/{args['file_id']}:batchUpdate", body={"requests": [_request(w, k, c, len(before) + n) for n, (w, k, c) in enumerate(questions)]}, doing=f"adding questions to '{args['name']}'")
    try:
        after = _titles(client.read(config, gd.CHANGE, gd.LABELS[gd.CHANGE], f"{FORMS}/{args['file_id']}"))
    except client.GoogleError:
        raise ActionUncertain("Google said the questions were added, but reading the form back to check did not work, so it is not confirmed. Look in Google Forms, then record what you found.")
    if after != before + [w for w, _, _ in questions]:
        raise ActionUncertain("Google said the questions were added, but reading the form back showed a different list, so it is not confirmed. Look in Google Forms, then record what you found.")
    return f"Added {len(questions)} question(s) to the Google Form '{args['name']}' (now {len(after)}), the list read back to check."


# ---- the kinds ----------------------------------------------------------------------------------------------------------------------------------------

def _kind(name, label, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=gd.CHANGE, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is done until the user approves it on the Actions page. It works only on forms Diya made, and shares nothing.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


QUESTIONS = {"type": "string", "description": "The questions on one line: questions separated by '||', a question's words, its kind (text, paragraph, choice or checkbox) and its choices by '|', for example 'How did you hear of us? | choice | a friend | an ad || Any comments? | paragraph'."}


def action_kinds():
    return (
        _kind("google_forms_create", "Make a Google Form", "propose_google_form", "Propose making a new Google Form with questions. Use it only when the user asks for a form or a survey.",
              {"title": {"type": "string", "description": "The form's name, exactly as the user said it."}, "questions": QUESTIONS}, ["title", "questions"], validate=create_validate, render=create_render, execute=create_execute,
              asked=asks.asks_for_form, prepare=create_prepare),
        _kind("google_forms_add", "Add questions to a Google Form", "propose_form_questions", "Propose adding questions to the end of a form Diya made. Use it only when the user asks to add questions to a form, naming it.",
              {"name": {"type": "string", "description": "The form's name, exactly as the user said it."}, "questions": QUESTIONS}, ["name", "questions"], validate=add_validate, render=add_render, execute=add_execute,
              asked=asks.adds_form_questions, prepare=add_prepare, resolve=add_resolve),
    )
