"""Google Tasks: reading the lists properly, and completing, changing, moving and deleting a task when you approve each one (DIYA-097, DIYA-098; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Adding a task was already here (diya_google_write). This is the rest, on the same card (Google Tasks, the `tasks` scope), through the one careful client (diya_google_client):

* **Reading.** `list_google_tasks` follows the next pages (a few, then says it stopped), shows each task's state (open or done), its due day and its id, and can read a list by name or the tasks that are done. The lists
  other than the default are READ by name only; everything that changes something is done to the default list.
* **Changing.** Completing, renaming or re-dating, moving to the top or under another task, and deleting a task. Each is a proposal the owner approves exactly as shown; none is ever done straight away (diya_autoapprove
  names the four kinds that can be, and these are not among them). The task is found NOW, by the words the person used, among the open tasks (ActionKind.resolve): none found, or several with the same name, refuses
  the proposal and says so, so that nothing is ever changed that was only guessed at. The approval carries the task's id and version (its etag); when it is run the task is read again, and if it has changed since
  (renamed, completed, edited in Google) nothing is done and the person is told. After the change the task is read back and must be what was asked for.
* **Deleting** is the one change here that Diya cannot undo, so its approval card says so (risk level 3).

Importing this module has no side effects.
"""
from __future__ import annotations

import re

import diya_connectors
import diya_google_client as client
import diya_google_write as gw
import diya_intent
import diya_intent_google as asks
import diya_memory
import diya_time
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

CARD = "google_tasks"
LABEL = "Google Tasks"
BASE = "https://tasks.googleapis.com/tasks/v1"
ID = r"[A-Za-z0-9_-]{5,128}"
PAGE = 100
MAX_PAGES = 3
SHOWN = 40  # how many tasks one read shows

client.allow(CARD, "GET", re.escape(f"{BASE}/users/@me/lists"))
client.allow(CARD, "GET", rf"{re.escape(BASE)}/lists/(?:@default|{ID})/tasks")
client.allow(CARD, "GET", rf"{re.escape(BASE)}/lists/(?:@default|{ID})/tasks/{ID}")
client.allow(CARD, "PATCH", rf"{re.escape(BASE)}/lists/@default/tasks/{ID}")
client.allow(CARD, "DELETE", rf"{re.escape(BASE)}/lists/@default/tasks/{ID}")
client.allow(CARD, "POST", rf"{re.escape(BASE)}/lists/@default/tasks/{ID}/move")
DEFAULT = f"{BASE}/lists/@default/tasks"


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").casefold()).split())


# ---- reading ---------------------------------------------------------------------------------------------------------------------------------------

def _list_id(config, name):
    """(id, title) of the task list called `name` (read only), or raises GoogleError / InvalidArgs-free words via the caller."""
    items, _ = client.pages(config, CARD, LABEL, f"{BASE}/users/@me/lists", {"maxResults": 100}, "items", max_pages=1)
    wanted = _norm(name)
    found = [i for i in items if _norm(i.get("title")) == wanted] or [i for i in items if wanted and wanted in _norm(i.get("title"))]
    if len(found) == 1 and isinstance(found[0].get("id"), str) and re.fullmatch(ID, found[0]["id"]):
        return found[0]["id"], str(found[0].get("title") or name)
    names = ", ".join(diya_memory.printable(i.get("title") or "?", 40) for i in items[:12])
    raise client.GoogleError("not_found", f"I could not tell which Google Tasks list is meant by {diya_memory.printable(name, 40)!r}. Your lists: {names or 'none'}.")


def read_tasks(config, list_name=None, show_done=False):
    """The tasks of the default list (or the list called `list_name`), as words: each with its state, due day and id; follows a few pages and says when it stopped."""
    try:
        list_id, title = ("@default", "your default list") if not list_name else _list_id(config, list_name)
        params = {"showCompleted": "true" if show_done else "false", "showHidden": "true" if show_done else "false", "maxResults": PAGE}
        items, more = client.pages(config, CARD, LABEL, f"{BASE}/lists/{list_id}/tasks", params, "items", max_pages=MAX_PAGES)
    except client.GoogleError as exc:
        return str(exc)
    items = [t for t in items if not t.get("deleted")]
    if not items:
        return f"No {'tasks' if show_done else 'open tasks'} in Google Tasks ({title})."
    lines = []
    for task in items[:SHOWN]:
        state = "done" if task.get("status") == "completed" else "open"
        due = f", due {str(task['due'])[:10]}" if task.get("due") else ""
        lines.append(f"- {diya_memory.printable(task.get('title') or '(no title)', 120)} ({state}{due}) [id: {diya_memory.printable(task.get('id'), 40)}]")
    if len(items) > SHOWN or more:
        lines.append(f"(Only the first {min(len(items), SHOWN)} are shown; there are more in the list.)")
    return f"Google Tasks, {title}:\n" + "\n".join(lines)


def read_tool_specs(config):
    """(connector name, tool spec, function) for the read side: the open Google Tasks, any list by name, and the finished ones."""
    spec = {"type": "function", "function": {
        "name": "list_google_tasks",
        "description": "List the user's Google Tasks: the open ones by default, or the finished ones too, or another list by its name.",
        "parameters": {"type": "object", "properties": {
            "list_name": {"type": "string", "description": "Optional. The name of one of their Google Tasks lists. Leave it out for the main list."},
            "show_done": {"type": "boolean", "description": "Optional. true to show finished tasks too."},
        }, "required": []},
    }}

    def tool(list_name=None, show_done=False):
        if diya_connectors.read_token(config, CARD) is None:
            return "Google Tasks is not connected."
        return read_tasks(config, list_name if isinstance(list_name, str) and list_name.strip() else None, show_done is True)

    return (("google_tasks", spec, tool),)


# ---- finding the one task a change is about -------------------------------------------------------------------------------------------------

def find_open_task(config, title):
    """The one open task in the default list whose name is `title` (words compared without capitals or punctuation); InvalidArgs, with words, for none or several."""
    if not isinstance(title, str) or not title.strip():
        raise InvalidArgs("say which task, by its name")
    try:
        items, more = client.pages(config, CARD, LABEL, DEFAULT, {"showCompleted": "false", "maxResults": PAGE}, "items", max_pages=MAX_PAGES)
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    wanted = _norm(title)
    matches = [t for t in items if _norm(t.get("title")) == wanted and not t.get("deleted")]
    if not matches:
        looked = " (only the first part of a long list was looked at)" if more else ""
        raise InvalidArgs(f"there is no open task called {diya_memory.printable(title, 60)!r} in your Google Tasks{looked}; read the list and ask the user which one they mean")
    if len(matches) > 1:
        raise InvalidArgs(f"{len(matches)} open tasks in your Google Tasks are called {diya_memory.printable(title, 60)!r}; ask the user which one, by its due day or its notes, and do not choose")
    task = matches[0]
    if not isinstance(task.get("id"), str) or not re.fullmatch(ID, task["id"]):
        raise InvalidArgs("Google gave that task no usable id, so it cannot be changed safely")
    return task


def _resolve(config, args, said=None):
    """Add the task's exact reference (id, version, name as Google has it) to the arguments; whatever the model put there is replaced."""
    task = find_open_task(config, args.get("title"))
    kept = {k: v for k, v in args.items() if k not in ("task_id", "etag", "title")}
    return dict(kept, title=str(task.get("title")), task_id=task["id"], etag=str(task.get("etag") or ""))


# ---- the changes ---------------------------------------------------------------------------------------------------------------------------------

def _validate_ref(args):
    if not isinstance(args.get("task_id"), str) or not re.fullmatch(ID, args["task_id"]):
        raise InvalidArgs("a change needs the task found by its name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("title"), "a task")
    if not isinstance(args.get("etag", ""), str) or len(args.get("etag", "")) > 200:
        raise InvalidArgs("the task's version is not usable")


def _read_task(config, task_id):
    return client.read(config, CARD, LABEL, f"{DEFAULT}/{task_id}")


def _still_the_same(config, args):
    """The task as it is now; ActionFailed (nothing done) if it is gone, finished, or has changed since the proposal."""
    try:
        current = _read_task(config, args["task_id"])
    except client.GoogleError as exc:
        if exc.kind == "not_found":
            raise ActionFailed("That task is not in your Google Tasks any more, so nothing was done.")
        raise ActionFailed(f"{exc} Nothing was done.")
    if not current or current.get("deleted"):
        raise ActionFailed("That task is not in your Google Tasks any more, so nothing was done.")
    if current.get("status") == "completed":
        raise ActionFailed(f"'{args['title']}' is already done in Google Tasks, so nothing was done.")
    if args.get("etag") and current.get("etag") and current["etag"] != args["etag"]:
        raise ActionFailed(f"'{args['title']}' was changed in Google Tasks after it was proposed, so nothing was done. Look at it in Google and ask again if you still want this.")
    return current


def _verify(config, args, check, what):
    """The task read back after a change: `check(task)` returns '' when it is what was asked for. Anything else is ActionUncertain."""
    try:
        found = _read_task(config, args["task_id"])
    except client.GoogleError:
        raise ActionUncertain(f"Google said {what} was done, but reading it back to check did not work, so it is not confirmed. Look in Google Tasks, then record what you found.")
    problem = check(found)
    if problem:
        raise ActionUncertain(f"Google said {what} was done, but reading it back showed {problem}, so it is not confirmed. Look in Google Tasks, then record what you found.")
    return found


def complete_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CARD, LABEL, "PATCH", f"{DEFAULT}/{args['task_id']}", body={"status": "completed"}, doing=f"marking '{args['title']}' done")
    _verify(config, args, lambda t: "" if t.get("status") == "completed" else "a task that is still open", f"marking '{args['title']}' done")
    return f"Marked done in your Google Tasks and read back to check: {args['title']}."


def update_execute(config, args):
    current = _still_the_same(config, args)
    body = {}
    if args.get("new_title"):
        body["title"] = args["new_title"]
    if args.get("new_notes") is not None:
        body["notes"] = args["new_notes"]
    if args.get("due"):
        body["due"] = f"{args['due']}T00:00:00.000Z"
    if not body:
        raise ActionFailed("There was nothing to change, so nothing was done.")
    client.send(config, CARD, LABEL, "PATCH", f"{DEFAULT}/{args['task_id']}", body=body, doing=f"changing '{args['title']}'")

    def check(found):
        if "title" in body and found.get("title") != body["title"]:
            return "a different name"
        if "notes" in body and (found.get("notes") or "") != body["notes"]:
            return "different notes"
        if "due" in body and not str(found.get("due", "")).startswith(args["due"]):
            return "a different due day"
        return ""

    _verify(config, args, check, f"changing '{args['title']}'")
    return f"Changed in your Google Tasks and read back to check: {current.get('title') or args['title']} is now {_changes(args)}."


def move_execute(config, args):
    _still_the_same(config, args)
    params = {}
    if args.get("under_id"):
        params["parent"] = args["under_id"]
    client.send(config, CARD, LABEL, "POST", f"{DEFAULT}/{args['task_id']}/move", params=params or None, doing=f"moving '{args['title']}'")
    if args.get("under_id"):
        _verify(config, args, lambda t: "" if t.get("parent") == args["under_id"] else "a task that is not under the other one", f"moving '{args['title']}'")
    else:
        _verify(config, args, lambda t: "" if not t.get("parent") else "a task that is still under another", f"moving '{args['title']}'")
    return f"Moved in your Google Tasks and read back to check: {args['title']}" + (f", under '{args['under']}'." if args.get("under") else ", to the top of the list.")


def delete_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CARD, LABEL, "DELETE", f"{DEFAULT}/{args['task_id']}", ok=(200, 204), doing=f"deleting '{args['title']}'")
    try:
        found = _read_task(config, args["task_id"])
    except client.GoogleError as exc:
        if exc.kind == "not_found":
            return f"Deleted from your Google Tasks: {args['title']}. Google no longer has it."
        raise ActionUncertain("Google said the task was deleted, but reading to check did not work, so it is not confirmed. Look in Google Tasks, then record what you found.")
    if found and not found.get("deleted"):
        raise ActionUncertain("Google said the task was deleted, but it is still there, so it is not confirmed. Look in Google Tasks, then record what you found.")
    return f"Deleted from your Google Tasks: {args['title']}."


def _changes(args):
    parts = []
    if args.get("new_title"):
        parts.append(f"named '{args['new_title']}'")
    if args.get("due"):
        parts.append(f"due {args['due']}")
    if args.get("new_notes") is not None:
        parts.append("with new notes" if args["new_notes"] else "without notes")
    return ", ".join(parts) or "unchanged"


def complete_validate(args):
    gw._only(args, {"title", "task_id", "etag"}, "completing a task")
    _validate_ref(args)


def update_validate(args):
    gw._only(args, {"title", "task_id", "etag", "new_title", "new_notes", "due"}, "changing a task")
    _validate_ref(args)
    if "new_title" in args:
        gw._clean_title(args["new_title"], "a task")
    if "new_notes" in args and (not isinstance(args["new_notes"], str) or len(args["new_notes"]) > gw.NOTES_MAX or diya_memory.printable(args["new_notes"]) != args["new_notes"]):
        raise InvalidArgs(f"a task's notes are one plain line of at most {gw.NOTES_MAX} characters")
    if "due" in args and (not isinstance(args["due"], str) or not gw._DATE.fullmatch(args["due"])):
        raise InvalidArgs("when it is due must be a date, said by the user")
    if not (args.get("new_title") or args.get("due") or "new_notes" in args):
        raise InvalidArgs("say what to change: its name, its due day or its notes")


def move_validate(args):
    gw._only(args, {"title", "task_id", "etag", "under", "under_id"}, "moving a task")
    _validate_ref(args)
    if "under_id" in args and (not isinstance(args["under_id"], str) or not re.fullmatch(ID, args["under_id"])):
        raise InvalidArgs("the other task is found by its name; it cannot be given an id")


def delete_validate(args):
    gw._only(args, {"title", "task_id", "etag"}, "deleting a task")
    _validate_ref(args)


def update_prepare(args, text):
    """What the person said, only: a new name, notes or due day that are not in their words are left out (the model made them up), and a due day is read by code from their words."""
    kept = dict(args)
    notes = []
    if "new_title" in kept and not gw._own_words(kept["new_title"], text):
        kept.pop("new_title")
        notes.append("The new name was left out because it was not in the user's words.")
    if "new_notes" in kept and not gw._own_words(kept["new_notes"], text):
        kept.pop("new_notes")
        notes.append("The new notes were left out because they were not in the user's words.")
    due = kept.pop("due", None)
    if due is not None:
        try:
            if not isinstance(due, str) or diya_time.disagreement(due, text):
                raise diya_time.NotUnderstood("the day is not the user's")
            kept["due"] = diya_time.parse_when(due).local.strftime("%Y-%m-%d")
        except diya_time.NotUnderstood:
            notes.append(f"The due day {due!r} was left out because the user did not say it.")
    return kept, notes


def update_resolve(config, args, said=None):
    return _resolve(config, args)


def move_resolve(config, args, said=None):
    resolved = _resolve(config, args)
    under = resolved.pop("under", None)
    if isinstance(under, str) and under.strip():
        other = find_open_task(config, under)
        if other["id"] == resolved["task_id"]:
            raise InvalidArgs("a task cannot be put under itself")
        resolved["under"], resolved["under_id"] = str(other.get("title")), other["id"]
    return resolved


def _kind(name, label, tool_name, description, properties, required, *, validate, render, execute, asked, prepare=None, resolve=_resolve):
    return ActionKind(
        name=name, label=label, connector=CARD, validate=validate, render=render, execute=execute, asked=asked, prepare=prepare, resolve=resolve,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is changed until the user approves it on the Actions page.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


TITLE = {"type": "string", "description": "The name of the task, exactly as the user said it."}


def complete_kind():
    return _kind("google_tasks_complete", "Mark a Google Task done", "propose_complete_google_task", "Propose marking one of the user's open Google Tasks as done. Use it only when the user asks for that in Google Tasks by name.",
                 {"title": TITLE}, ["title"], validate=complete_validate, render=lambda a: f"Mark done in your Google Tasks: {a['title']}", execute=complete_execute, asked=asks.completes_google_task)


def update_kind():
    return _kind("google_tasks_update", "Change a Google Task", "propose_update_google_task", "Propose renaming a Google Task, giving it new notes or a new due day. Use it only when the user asks for that in Google Tasks by name.",
                 {"title": TITLE, "new_title": {"type": "string", "description": "Optional. The new name, in the user's words."}, "new_notes": {"type": "string", "description": "Optional. New notes, in the user's words."},
                  "due": {"type": "string", "description": "Optional. The new due day in the user's own words, e.g. 'friday'."}}, ["title"],
                 validate=update_validate, render=lambda a: f"Change the Google task '{a['title']}': now {_changes(a)}", execute=update_execute, asked=asks.changes_google_task, prepare=update_prepare, resolve=update_resolve)


def move_kind():
    return _kind("google_tasks_move", "Move a Google Task", "propose_move_google_task", "Propose moving a Google Task to the top of the list, or under another task. Use it only when the user asks for that in Google Tasks by name.",
                 {"title": TITLE, "under": {"type": "string", "description": "Optional. The name of the task to put it under. Leave it out to move it to the top."}}, ["title"],
                 validate=move_validate, render=lambda a: f"Move the Google task '{a['title']}' " + (f"under '{a['under']}'" if a.get("under") else "to the top of the list"), execute=move_execute, asked=asks.moves_google_task, resolve=move_resolve)


def delete_kind():
    return _kind("google_tasks_delete", "Delete a Google Task", "propose_delete_google_task", "Propose deleting one of the user's open Google Tasks. Diya cannot bring it back. Use it only when the user asks for that in Google Tasks by name.",
                 {"title": TITLE}, ["title"], validate=delete_validate, render=lambda a: f"Delete from your Google Tasks: {a['title']} (Diya cannot bring it back)", execute=delete_execute, asked=asks.deletes_google_task)


def action_kinds():
    return (complete_kind(), update_kind(), move_kind(), delete_kind())
