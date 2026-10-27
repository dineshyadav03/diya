"""Looking at the one chat by category, and changing the categories, over HTTP (docs/ONE_CHAT_DESIGN.md, steps 2 to 4).

    GET  /api/categories    {"categories": [{id, name, meaning, count}], "tags": {"<message id>": "<category name>"}, "suggestions": [...], "job": {...}, "unsorted": 12}
                            the list, where the newest messages of the one chat are, the new categories Diya has suggested, what the background job (if any) is doing, and how many messages are in none
    POST /api/categories    one of
        {"action": "assign", "message_id": 12, "category": "Weather"}        put one of the person's messages in a category (what a click on its tag does)
        {"action": "add", "name": "School", "meaning": "..."}                 make a category
        {"action": "rename", "category_id": 3, "name": "Home"}                rename one (the starter ones too)
        {"action": "merge", "category_id": 3, "into_id": 5}                   fold one into another: its messages move, it is gone from the list
        {"action": "browse", "category_id": 3, "limit": 30}                   {"messages": [...]}: the person's newest messages in it, from every chat
        {"action": "undo_merge", "merge_id": 2}                               take a merge back: the category is shown again and its messages go back (unless changed since)
        {"action": "search", "query": "dentist", "category_id": 3, "when": "last week"}   {"results": [...]}: messages of yours and Diya's that contain the words, newest first,
                                                                              with the day and category of each; `category_id`, `since`/`until` (dates) and `when` (yesterday, last week...) are optional
        {"action": "suggest"}                                                 look for a new category (a background job: poll `job`)
        {"action": "sort_earlier"}                                            sort the messages that are in no category, such as those of the earlier chats (a background job)
        {"action": "answer_suggestion", "suggestion_id": 1, "accept": true, "message_ids": [4, 7]}   yes (those messages move into the new category) or no

Like every route these are behind the access token. A refusal is a 400 whose words are safe to show; everything sent back goes through diya_memory.printable().
"""
from __future__ import annotations

import threading
from datetime import date, datetime

from fastapi import HTTPException
from pydantic import BaseModel

import diya_categories
import diya_category_ideas
import diya_when
from diya_memory import printable

BROWSE_LIMIT = 100
SEARCH_LIMIT = 50
RECENT_MERGES = 5
TEXT_CHARS = 300


class Action(BaseModel):
    action: str
    message_id: int | None = None
    category: str | None = None
    category_id: int | None = None
    into_id: int | None = None
    name: str | None = None
    meaning: str | None = None
    suggestion_id: int | None = None
    accept: bool | None = None
    message_ids: list[int] | None = None
    limit: int | None = None
    merge_id: int | None = None
    query: str | None = None
    since: str | None = None
    until: str | None = None
    when: str | None = None


class Job:
    """One background job at a time (sorting the earlier chats, or looking for a new category), told to the page as `job`: {kind, running, done, total, note}."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {"kind": None, "running": False, "done": 0, "total": 0, "note": ""}

    def snapshot(self):
        with self._lock:
            return dict(self._state)

    def start(self, kind, work):
        """Run `work(update)` in a thread of its own. `update(done, total, note)` tells the page how far it is. Returns False if a job is already running."""
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {"kind": kind, "running": True, "done": 0, "total": 0, "note": ""}

        def update(done=None, total=None, note=None):
            with self._lock:
                if done is not None:
                    self._state["done"] = done
                if total is not None:
                    self._state["total"] = total
                if note is not None:
                    self._state["note"] = note

        def run():
            try:
                work(update)
            except Exception as exc:  # noqa: BLE001 -- a job that fails says so on the page and leaves what it did
                update(note="That did not finish (" + type(exc).__name__ + "). What was done is kept.")
            finally:
                with self._lock:
                    self._state["running"] = False

        threading.Thread(target=run, name="categories-" + kind, daemon=True).start()
        return True


def shown(book, tail_ids):
    """The categories as the page is given them, and where the messages in `tail_ids` are."""
    listing = [{"id": c["id"], "name": printable(c["name"]), "meaning": printable(c["meaning"]), "count": c["count"]} for c in book.listing()]
    suggestions = [
        {"id": s["id"], "name": printable(s["name"]), "messages": [{"id": m["id"], "text": printable(m["text"], TEXT_CHARS)} for m in s["messages"]]} for s in book.open_suggestions()
    ]
    return {
        "categories": listing,
        "tags": {str(i): printable(name) for i, name in book.tags(tail_ids).items()},
        "suggestions": suggestions,
        "unsorted": len(book.unsorted()),
        "merges": [
            {"id": m["id"], "source": printable(m["source"]), "target": printable(m["target"]), "count": m["count"], "at": m["at"], "undone": m["undone"], "can_undo": m["can_undo"], "why_not": printable(m["why_not"])}
            for m in book.merges(RECENT_MERGES)
        ],
    }


def _day(text, what):
    """A date the person gave as YYYY-MM-DD, or None when it was left out; CategoryError in plain words when it is not a date."""
    if text is None or not str(text).strip():
        return None
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        raise diya_categories.CategoryError(f"{what} should be a date like 2026-10-12.")


def search_window(body):
    """(since, until) for a search: from `when` ("yesterday", "last week", "last month"...) read against today, else from the two dates; (None, None) for no limit on time."""
    if body.when is not None and body.when.strip():
        window = diya_when.window(body.when, datetime.now().astimezone().date())
        if window is None:
            raise diya_categories.CategoryError("I did not understand that time. Try yesterday, last week, last month, or a date like 2026-10-12.")
        return window
    return _day(body.since, "From"), _day(body.until, "Until")


def register(app, config, agent, tail_limit):
    """Add the routes to `app`, directly, like every other route. `tail_limit` is how many of the one chat's newest messages the page is given (diya_web.MAX_PAGE_MESSAGES)."""
    job = Job()

    def book():
        return diya_categories.Book(agent.store)  # looked up per request: the store is what the agent has now

    def newest_ids():
        main = agent.store.current_main_thread()
        if main is None:
            return []
        messages, _ = agent.store.get_messages_tail(main, tail_limit())
        return [m["id"] for m in messages if m["role"] == "user"]

    def everything():
        return dict(shown(book(), newest_ids()), job=job.snapshot())

    def need_sorting_on():
        if not config.categories:
            raise diya_categories.CategoryError("Sorting is turned off (DIYA_CATEGORIES=0).")

    @app.get("/api/categories")
    def categories():
        body = everything()
        if not config.categories:  # sorting is off (DIYA_CATEGORIES=0): the chat shows no category at all
            body.update(categories=[], tags={}, suggestions=[])
        return body

    @app.post("/api/categories")
    def change(body: Action):
        try:
            if body.action == "assign" and body.message_id is not None and body.category is not None:
                book().assign(body.message_id, body.category, "person")
            elif body.action == "add" and body.name is not None:
                book().add(body.name, body.meaning or "")
            elif body.action == "rename" and body.category_id is not None and body.name is not None:
                book().rename(body.category_id, body.name)
            elif body.action == "merge" and body.category_id is not None and body.into_id is not None:
                book().merge(body.category_id, body.into_id)
            elif body.action == "browse" and body.category_id is not None:
                found = book().messages_in(body.category_id, min(max(body.limit or 30, 1), BROWSE_LIMIT))
                return {
                    "messages": [
                        {"id": m["id"], "text": printable(m["text"], TEXT_CHARS), "at": m["at"], "thread_id": m["thread_id"], "source": m["source"], "reply": printable(m["reply"], TEXT_CHARS)}
                        for m in found
                    ]
                }
            elif body.action == "undo_merge" and body.merge_id is not None:
                undone = book().undo_merge(body.merge_id)
                return dict(everything(), undone={"name": printable(undone["name"]), "restored": undone["restored"], "left": undone["left"]})
            elif body.action == "search" and body.query is not None:
                since, until = search_window(body)
                found = book().search(body.query, body.category_id, since, until, min(max(body.limit or 30, 1), SEARCH_LIMIT))
                return {
                    "results": [
                        {"id": m["id"], "role": m["role"], "text": printable(m["text"], TEXT_CHARS), "at": m["at"], "thread_id": m["thread_id"], "category": printable(m["category"]) if m["category"] else None}
                        for m in found
                    ]
                }
            elif body.action == "suggest":
                need_sorting_on()

                def look(update):
                    update(note="Looking through your messages for something none of the categories covers...")
                    made = diya_category_ideas.suggest(book(), agent.client, config.model)
                    update(note="I have a suggestion for you." if made else "Nothing stood out that the categories do not already cover.")

                if not job.start("suggest", look):
                    raise diya_categories.CategoryError("Something is already running. Wait for it to finish.")
            elif body.action == "sort_earlier":
                need_sorting_on()

                def sort_them(update):
                    done = diya_category_ideas.sort_earlier(
                        book(), agent.client, config.model, diya_categories.SORT_LOCK, progress=lambda d, t: update(done=d, total=t)
                    )
                    update(note=f"Sorted {done} message{'' if done == 1 else 's'}." if done else "Every message was already in a category.")

                if not job.start("sort_earlier", sort_them):
                    raise diya_categories.CategoryError("Something is already running. Wait for it to finish.")
            elif body.action == "answer_suggestion" and body.suggestion_id is not None and body.accept is not None:
                book().answer_suggestion(body.suggestion_id, body.accept, body.message_ids)
            else:
                raise diya_categories.CategoryError("That is not something categories can do.")
        except diya_categories.CategoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return everything()
