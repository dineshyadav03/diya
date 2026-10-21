"""Putting what is said into categories, on its own (docs/ONE_CHAT_DESIGN.md, step 2).

Diya has one chat. Each exchange (the person's message and the reply to it) gets exactly ONE category, so the chat can be looked at by category without being split into chats. There is no "Other":
a message always lands in the closest category on the list.

Code decides what code can know, in this order: a tool that ran (the weather tool means Weather), then the shape of the message (a greeting, a question about Diya, a reminder request, a fact the
person shares about themselves, a weather word, a short "quick check"). The model is asked only for what is left, as one short question after the reply, never before it: "which of these categories
is this message in?" Its answer is checked against the list. If it gives no usable answer twice, the exchange takes the category of the one before it (a conversation stays on its subject), else Chat.
The model is NOT allowed to make up a category while sorting: measured on the owner's real messages it named one "File access limits". New categories are proposed to the person (later), never made quietly.

Nothing here reaches outside this computer, and a category is only a label: it changes nothing Diya says or remembers.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

import diya_db
import diya_intent
import diya_when

# (name, what belongs in it). The names are what the person sees; the words are what the model is told. A person can rename a category or add one; these are where it starts, and every one of the
# owner's first 110 real messages fits one of them.
STARTER = (
    ("Weather", "the weather, temperature, rain or a forecast"),
    ("Reminders & tasks", "reminders, things to do, a to-do list, being reminded of something, or when something was done"),
    ("About me", "facts about the person (their life, family, pets, health, studies, plans) and what the assistant knows or remembers about them"),
    ("About Diya", "what the assistant is and can do, which model it uses, how to connect it to an account or set something up"),
    ("Learning", "a question about the world: how something works, a fact, a person, news, or something to look up"),
    ("Chat", "greetings, small talk, thanks, jokes, and quick tests of whether it is working"),
)
FALLBACK = "Chat"
MAX_TEXT_CHARS = 600  # how much of a message the model is shown (a long message is sorted by its start)
MAX_CHECK_WORDS = 8  # "quick check", "final verification test", "testing processing state": a short message about trying the thing out

# A tool that ran says what the exchange was about. The first one run decides.
TOOL_CATEGORY = {
    "get_weather": "Weather",
    "add_reminder": "Reminders & tasks",
    "list_reminders": "Reminders & tasks",
    "add_task": "Reminders & tasks",
    "list_tasks": "Reminders & tasks",
    "search_notes": "About me",
    "list_files": "About Diya",
    "web_search": "Learning",
    "study_repo": "Learning",
    "read_mail": "About me",
}
_WEATHER = re.compile(r"\b(?:weather|temperature|forecast|raining|rain|sunny|humidity)\b", re.IGNORECASE)
_TRYING_IT_OUT = re.compile(r"\b(?:check|checks|test|tests|testing|sanity|verification|verify|still\s+working)\b", re.IGNORECASE)


def by_code(text, tools_called=()):
    """The category the exchange is in when code can tell, else None (the model is asked). `tools_called` is the names of the tools that ran, in order."""
    if not isinstance(text, str) or not text.strip():
        return None
    for name in tools_called or ():
        if name in TOOL_CATEGORY:
            return TOOL_CATEGORY[name]
    if diya_intent.is_small_talk(text):
        return "Chat"
    if diya_intent.asks_about_diya(text):
        return "About Diya"
    if diya_intent.is_reminder_request(text) or diya_intent.is_task_request(text):
        return "Reminders & tasks"
    if diya_intent.is_fact_share(text):
        return "About me"
    if _WEATHER.search(text):
        return "Weather"
    if len(text.split()) <= MAX_CHECK_WORDS and _TRYING_IT_OUT.search(text):  # last: "check the weather" and "remind me to check the audit" are caught above
        return "Chat"
    return None


def prompt_for(text, categories):
    """The question put to the model: the categories (name and what belongs in it) and the message. `categories` is [(name, meaning), ...]."""
    listed = "\n".join(f"- {name}: {meaning}" if meaning else f"- {name}" for name, meaning in categories)
    shown = " ".join(str(text).split())[:MAX_TEXT_CHARS]
    return (
        "You sort one message that a person sent to their personal assistant into exactly one category.\n\n"
        f"Categories:\n{listed}\n\n"
        f"Message: \"{shown}\"\n\n"
        "Answer with only the name of the category the message belongs in. Pick the closest one, even if it is not a perfect fit."
    )


def read_answer(answer, names):
    """The category the model named, as one of `names` (spelled as in the list), or None if it named none or more than one. Case, quotes and a trailing full stop are ignored; a reply with extra
    words around a category's name counts only if exactly one category's name is in it."""
    if not isinstance(answer, str) or not answer.strip():
        return None
    reply = answer.strip().splitlines()[0].strip(" \"'`*.").strip()
    lowered = {name.lower(): name for name in names}
    if reply.lower() in lowered:
        return lowered[reply.lower()]
    inside = [name for lowered_name, name in lowered.items() if re.search(rf"(?<!\w){re.escape(lowered_name)}(?!\w)", reply.lower())]
    return inside[0] if len(inside) == 1 else None


def by_model(client, model, text, categories, tries=2):
    """Ask the model which category the message is in: the name as in `categories`, or None if it gave no usable answer in `tries` asks."""
    names = [name for name, _ in categories]
    for _ in range(tries):
        reply = client.chat.completions.create(model=model, temperature=0, max_tokens=16, messages=[{"role": "user", "content": prompt_for(text, categories)}])
        named = read_answer(reply.choices[0].message.content, names)
        if named:
            return named
    return None


# ---- the list the person sees, and where each message is ---------------------------------------------------------------------

MAX_NAME_WORDS = 3
MAX_NAME_CHARS = 30
MAX_MEANING_CHARS = 200
SEARCH_SCAN = 2000  # how many matching messages a search looks through before the date filter and the limit
MAX_SEARCH_CHARS = 100  # the longest search that is looked for
MAX_CATEGORIES = 30  # a person can have this many; more would stop being a way to look at the chat


# One message is sorted at a time, whoever is doing the sorting (a chat that has just been answered, or the earlier chats being sorted in the background).
SORT_LOCK = threading.Lock()


class CategoryError(ValueError):
    """Something the person asked for cannot be done; the words are safe to show them."""


def clean_name(raw):
    """A category name as it is kept: letters, digits, spaces, &, ' and -, one to three words, at most 30 characters, first letter capital. Raises CategoryError with what is wrong."""
    name = " ".join(re.sub(r"[^\w &'-]", "", str(raw or "")).split()).strip(" -'&")
    if not name:
        raise CategoryError("A category needs a name.")
    if len(name) > MAX_NAME_CHARS or len(name.split()) > MAX_NAME_WORDS:
        raise CategoryError(f"A category name is at most {MAX_NAME_WORDS} words and {MAX_NAME_CHARS} characters.")
    return name[0].upper() + name[1:]


class Book:
    """The categories and which one each message is in, kept in the store (tables categories and message_categories, migration 18). The starter categories are made the first time it is used."""

    def __init__(self, store):
        self.store = store

    def _open(self):
        conn = self.store.connect()
        if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            now = datetime.now(timezone.utc).isoformat()
            conn.executemany(
                "INSERT OR IGNORE INTO categories (name, meaning, origin, position, created_at) VALUES (?, ?, ?, ?, ?)",
                [(name, meaning, name, position, now) for position, (name, meaning) in enumerate(STARTER)],
            )
            conn.commit()
        return conn

    def categories(self):
        """[(name, meaning)] in the order the person sees them: what the model is shown."""
        conn = self._open()
        try:
            return [(name, meaning or "") for name, meaning in conn.execute("SELECT name, meaning FROM categories WHERE merged_into IS NULL ORDER BY position, id")]
        finally:
            conn.close()

    def listing(self):
        """[{id, name, meaning, count}] in order: `count` is how many messages are in it."""
        conn = self._open()
        try:
            rows = conn.execute(
                "SELECT c.id, c.name, c.meaning, (SELECT COUNT(*) FROM message_categories m WHERE m.category_id = c.id) FROM categories c WHERE c.merged_into IS NULL ORDER BY c.position, c.id"
            ).fetchall()
            return [{"id": i, "name": name, "meaning": meaning or "", "count": count} for i, name, meaning, count in rows]
        finally:
            conn.close()

    @staticmethod
    def _find(conn, name):
        """The id and current name of the category called `name` (case ignored), or the starter one that was originally called that; None if there is none."""
        row = conn.execute("SELECT id, name, merged_into FROM categories WHERE name = ?", (str(name),)).fetchone()
        row = row or conn.execute("SELECT id, name, merged_into FROM categories WHERE origin = ? COLLATE NOCASE", (str(name),)).fetchone()
        for _ in range(20):  # a merged category points at the one it went into, which may itself have been merged
            if row is None or row[2] is None:
                break
            row = conn.execute("SELECT id, name, merged_into FROM categories WHERE id = ?", (row[2],)).fetchone()
        return None if row is None else (row[0], row[1])

    def assign(self, message_id, name, source):
        """Put the person's message in the category called `name`. Returns the category's current name. CategoryError if there is no such category or no such message of the person's."""
        conn = self._open()
        try:
            found = self._find(conn, name)
            if found is None:
                raise CategoryError("There is no category called that.")
            if conn.execute("SELECT 1 FROM messages WHERE id = ? AND role = 'user'", (int(message_id),)).fetchone() is None:
                raise CategoryError("There is no such message of yours.")
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO message_categories (message_id, category_id, source, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(message_id) DO UPDATE SET category_id = excluded.category_id, source = excluded.source, created_at = excluded.created_at "
                "WHERE message_categories.source != 'person' OR excluded.source = 'person'",  # what the person chose is only ever changed by the person (task DIYA-157)
                (int(message_id), found[0], source, now),
            )
            conn.commit()
            return conn.execute("SELECT c.name FROM message_categories mc JOIN categories c ON c.id = mc.category_id WHERE mc.message_id = ?", (int(message_id),)).fetchone()[0]
        finally:
            conn.close()

    def tags(self, message_ids):
        """{message_id: category name} for those of `message_ids` that are in a category."""
        ids = [int(i) for i in message_ids]
        if not ids:
            return {}
        conn = self._open()
        try:
            marks = ",".join("?" * len(ids))
            rows = conn.execute(
                f"SELECT m.message_id, c.name FROM message_categories m JOIN categories c ON c.id = m.category_id WHERE m.message_id IN ({marks})", ids
            ).fetchall()
            return {message_id: name for message_id, name in rows}
        finally:
            conn.close()

    def previous(self, message_id):
        """The category of the person's message just before this one in the same chat that has one, or None: a conversation stays on its subject when a message cannot be placed."""
        conn = self._open()
        try:
            row = conn.execute(
                "SELECT c.name FROM messages me JOIN messages m ON m.thread_id = me.thread_id AND m.id < me.id AND m.role = 'user' "
                "JOIN message_categories mc ON mc.message_id = m.id JOIN categories c ON c.id = mc.category_id WHERE me.id = ? ORDER BY m.id DESC LIMIT 1",
                (int(message_id),),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def add(self, name, meaning=""):
        """Make a category the person asked for. Returns its id. CategoryError if the name is not usable, is taken, or there are already MAX_CATEGORIES."""
        name = clean_name(name)
        meaning = " ".join(str(meaning or "").split())[:MAX_MEANING_CHARS]
        conn = self._open()
        try:
            if conn.execute("SELECT COUNT(*) FROM categories WHERE merged_into IS NULL").fetchone()[0] >= MAX_CATEGORIES:
                raise CategoryError(f"There are already {MAX_CATEGORIES} categories.")
            if self._find(conn, name) is not None:
                raise CategoryError("There is a category called that already.")
            position = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM categories WHERE merged_into IS NULL").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO categories (name, meaning, origin, position, created_at) VALUES (?, ?, NULL, ?, ?)", (name, meaning, position, datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def rename(self, category_id, name):
        """Give a category a new name. Returns the name as kept. CategoryError if there is no such category or the name is not usable or is another category's."""
        name = clean_name(name)
        conn = self._open()
        try:
            if conn.execute("SELECT 1 FROM categories WHERE id = ? AND merged_into IS NULL", (int(category_id),)).fetchone() is None:
                raise CategoryError("There is no such category.")
            taken = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
            if taken is not None and taken[0] != int(category_id):
                raise CategoryError("There is a category called that already.")
            conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, int(category_id)))
            conn.commit()
            return name
        finally:
            conn.close()

    def state(self, key):
        """A small remembered value (app_state), or None."""
        conn = self._open()
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (str(key),)).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def set_state(self, key, value):
        conn = self._open()
        try:
            conn.execute("INSERT OR REPLACE INTO app_state (key, value) VALUES (?, ?)", (str(key), str(value)))
            conn.commit()
        finally:
            conn.close()

    def merge(self, source_id, target_id):
        """Fold the category `source_id` into `target_id`: its messages move there and it is gone from the list (a hidden row is kept, so code that knows the source by its starter name still finds
        the target). Returns the target's name. CategoryError if either is not there or they are the same."""
        source_id, target_id = int(source_id), int(target_id)
        if source_id == target_id:
            raise CategoryError("A category cannot be merged into itself.")
        conn = self._open()
        try:
            live = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM categories WHERE merged_into IS NULL")}
            if source_id not in live or target_id not in live:
                raise CategoryError("There is no such category.")
            moved = [[mid, how, at] for mid, how, at in conn.execute("SELECT message_id, source, created_at FROM message_categories WHERE category_id = ? ORDER BY message_id", (source_id,))]
            conn.execute("UPDATE message_categories SET category_id = ? WHERE category_id = ?", (target_id, source_id))
            conn.execute("UPDATE categories SET merged_into = ?, name = name || ' [merged ' || id || ']' WHERE id = ?", (target_id, source_id))
            conn.execute(
                "INSERT INTO category_merges (source_id, target_id, source_name, target_name, moved, merged_at) VALUES (?, ?, ?, ?, ?, ?)",
                (source_id, target_id, live[source_id], live[target_id], json.dumps(moved), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return live[target_id]
        finally:
            conn.close()

    @staticmethod
    def _undo_blocker(conn, merge):
        """Why this merge cannot be undone now, in plain words, or None when it can. `merge` is a row of (id, source_id, target_id, source_name, target_name, undone_at)."""
        _id, source_id, target_id, source_name, target_name, undone_at = merge
        if undone_at is not None:
            return "That merge was already undone."
        source = conn.execute("SELECT merged_into FROM categories WHERE id = ?", (source_id,)).fetchone()
        if source is None or source[0] != target_id:
            return "That category is not in the state the merge left it, so it cannot be brought back."
        target = conn.execute("SELECT merged_into, name FROM categories WHERE id = ?", (target_id,)).fetchone()
        if target is None or target[0] is not None:
            return f"{target_name} was merged into another category after this, so undo that merge first."
        if conn.execute("SELECT 1 FROM categories WHERE merged_into IS NULL AND name = ? COLLATE NOCASE", (source_name,)).fetchone():
            return f"There is already a category called {source_name}; rename it first."
        return None

    def merges(self, limit=10):
        """The newest merges first: [{id, source, target, count, at, undone, can_undo, why_not}]. `count` is how many messages the merge moved; `can_undo` is whether undoing it would work right now."""
        conn = self._open()
        try:
            rows = conn.execute(
                "SELECT id, source_id, target_id, source_name, target_name, undone_at, moved, merged_at FROM category_merges ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
            found = []
            for row in rows:
                why = self._undo_blocker(conn, row[:6])
                found.append({
                    "id": row[0], "source": row[3], "target": row[4], "count": len(json.loads(row[6])), "at": row[7],
                    "undone": row[5] is not None, "can_undo": why is None, "why_not": why or "",
                })
            return found
        finally:
            conn.close()

    def undo_merge(self, merge_id):
        """Take a merge back as one act: the category is shown again under its own name, and each message the merge moved goes back to it unless it has been changed since (moved by the person, sorted
        again). Returns {name, restored, left}: `left` is how many were not put back because they had been changed. CategoryError, changing nothing, if there is no such merge or it cannot be undone."""
        conn = self._open()
        try:
            row = conn.execute("SELECT id, source_id, target_id, source_name, target_name, undone_at, moved FROM category_merges WHERE id = ?", (int(merge_id),)).fetchone()
            if row is None:
                raise CategoryError("There is no such merge.")
            why = self._undo_blocker(conn, row[:6])
            if why:
                raise CategoryError(why)
            _id, source_id, target_id, source_name, _target_name, _undone, moved = row
            moved = json.loads(moved)
            conn.execute("UPDATE categories SET merged_into = NULL, name = ? WHERE id = ?", (source_name, source_id))
            restored = 0
            for message_id, how, at in moved:
                restored += conn.execute(
                    "UPDATE message_categories SET category_id = ? WHERE message_id = ? AND category_id = ? AND source = ? AND created_at = ?", (source_id, message_id, target_id, how, at)
                ).rowcount
            conn.execute("UPDATE category_merges SET undone_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), row[0]))
            conn.commit()
            return {"name": source_name, "restored": restored, "left": len(moved) - restored}
        finally:
            conn.close()

    def search(self, query, category_id=None, since=None, until=None, limit=30):
        """The person's words and Diya's, newest first, that contain `query` (case ignored; `%` and `_` are only themselves): [{id, role, text, at, thread_id, category}] across the one chat and every
        earlier one. `category_id` keeps only what is in that category (a reply counts as the category of the message it answers); `since` and `until` are the person's own calendar days (dates), both
        included. `text` is a short piece around the words found. Nothing is changed. [] for a query under two characters."""
        query = " ".join(str(query or "").split())[:MAX_SEARCH_CHARS]
        if len(query) < 2:
            return []
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        sql = (
            "SELECT m.id, m.role, m.content, m.created_at, m.thread_id, COALESCE(c1.name, c2.name), COALESCE(mc1.category_id, mc2.category_id) "
            "FROM messages m "
            "LEFT JOIN message_categories mc1 ON mc1.message_id = m.id LEFT JOIN categories c1 ON c1.id = mc1.category_id "
            "LEFT JOIN message_categories mc2 ON m.role = 'assistant' AND mc2.message_id = "
            "(SELECT u.id FROM messages u WHERE u.thread_id = m.thread_id AND u.id < m.id AND u.role = 'user' ORDER BY u.id DESC LIMIT 1) "
            "LEFT JOIN categories c2 ON c2.id = mc2.category_id "
            "WHERE m.role IN ('user', 'assistant') AND m.content LIKE ? ESCAPE '\\' "
        )
        args = [like]
        if category_id is not None:
            sql += "AND COALESCE(mc1.category_id, mc2.category_id) = ? "
            args.append(int(category_id))
        sql += "ORDER BY m.id DESC LIMIT ?"
        args.append(SEARCH_SCAN)
        conn = self._open()
        try:
            rows = conn.execute(sql, args).fetchall()
        finally:
            conn.close()
        found = []
        for message_id, role, content, at, thread_id, category, _category_id in rows:
            if since is not None or until is not None:
                try:
                    day = diya_when.local_date(at)
                except (ValueError, TypeError, AttributeError):
                    continue
                if (since is not None and day < since) or (until is not None and day > until):
                    continue
            found.append({"id": message_id, "role": role, "text": diya_db.around(content, query), "at": at, "thread_id": thread_id, "category": category})
            if len(found) >= int(limit):
                break
        return found

    def messages_in(self, category_id, limit=30):
        """The person's newest messages in a category, from every chat: [{id, text, at, thread_id, source, reply}] newest first (`reply` is the start of what Diya answered)."""
        conn = self._open()
        try:
            rows = conn.execute(
                "SELECT m.id, m.content, m.created_at, m.thread_id, mc.source, "
                "(SELECT a.content FROM messages a WHERE a.thread_id = m.thread_id AND a.id > m.id AND a.role = 'assistant' ORDER BY a.id LIMIT 1) "
                "FROM message_categories mc JOIN messages m ON m.id = mc.message_id WHERE mc.category_id = ? ORDER BY m.id DESC LIMIT ?",
                (int(category_id), int(limit)),
            ).fetchall()
            return [{"id": i, "text": text, "at": at, "thread_id": thread, "source": source, "reply": reply or ""} for i, text, at, thread, source, reply in rows]
        finally:
            conn.close()

    def unsorted(self, limit=None):
        """The person's messages that are in no category yet, oldest first: [(id, text)]."""
        conn = self._open()
        try:
            sql = "SELECT m.id, m.content FROM messages m LEFT JOIN message_categories mc ON mc.message_id = m.id WHERE m.role = 'user' AND mc.message_id IS NULL ORDER BY m.id"
            return [(i, text) for i, text in conn.execute(sql + (" LIMIT ?" if limit else ""), (int(limit),) if limit else ())]
        finally:
            conn.close()

    def recent_for_ideas(self, limit):
        """[(id, text)] of the person's newest distinct messages that no rule could place (the model sorted them, or they stayed with the one before), oldest first: the ones a category may be missing for. Messages a rule placed (a greeting, the weather) and ones the person placed themselves are left out."""
        conn = self._open()
        try:
            rows = conn.execute(
                "SELECT m.id, m.content FROM messages m LEFT JOIN message_categories mc ON mc.message_id = m.id "
                "WHERE m.role = 'user' AND mc.source IN ('model', 'continued') ORDER BY m.id DESC"
            ).fetchall()
        finally:
            conn.close()
        seen, found = set(), []
        for message_id, text in rows:
            key = " ".join(text.lower().split())
            if key in seen:
                continue
            seen.add(key)
            found.append((message_id, text))
            if len(found) >= int(limit):
                break
        return list(reversed(found))

    def starter_names(self):
        """The names the starter categories were made with (a renamed one is still known by its first name)."""
        conn = self._open()
        try:
            return [row[0] for row in conn.execute("SELECT origin FROM categories WHERE origin IS NOT NULL")]
        finally:
            conn.close()

    # --- new categories Diya suggests ---

    def open_suggestions(self):
        """[{id, name, message_ids, messages: [{id, text}]}] the person has not answered yet."""
        import json

        conn = self._open()
        try:
            rows = conn.execute("SELECT id, name, message_ids FROM category_suggestions WHERE status = 'open' ORDER BY id").fetchall()
            found = []
            for sid, name, ids_json in rows:
                ids = [int(i) for i in json.loads(ids_json)]
                marks = ",".join("?" * len(ids)) or "NULL"
                texts = dict(conn.execute(f"SELECT id, content FROM messages WHERE id IN ({marks})", ids).fetchall())
                found.append({"id": sid, "name": name, "message_ids": ids, "messages": [{"id": i, "text": texts[i]} for i in ids if i in texts]})
            return found
        finally:
            conn.close()

    def known_suggestion_names(self):
        """Names already suggested (open, accepted or declined), lower case: a name the person said no to is not suggested again."""
        conn = self._open()
        try:
            return {row[0].lower() for row in conn.execute("SELECT name FROM category_suggestions")}
        finally:
            conn.close()

    def add_suggestion(self, name, message_ids):
        """Keep a suggestion for the person to answer. Returns its id."""
        import json

        conn = self._open()
        try:
            cur = conn.execute(
                "INSERT INTO category_suggestions (name, message_ids, created_at) VALUES (?, ?, ?)",
                (clean_name(name), json.dumps([int(i) for i in message_ids]), datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def answer_suggestion(self, suggestion_id, accept, only=None):
        """The person's answer. Yes: the category is made (or the one with that name is used) and the messages it was about move into it, as the person's own choice; `only` is the ids of the messages
        they left ticked (None: all of them). No: it is remembered so it is not suggested again. Returns the category's name when accepted, else None. CategoryError if there is no open suggestion with
        that id, or a yes with no message ticked."""
        mine = [s for s in self.open_suggestions() if s["id"] == int(suggestion_id)]
        if not mine:
            raise CategoryError("There is no such suggestion.")
        suggestion = mine[0]
        name = None
        if accept:
            chosen = suggestion["message_ids"] if only is None else [i for i in suggestion["message_ids"] if i in {int(x) for x in only}]
            if not chosen:
                raise CategoryError("Tick at least one message to move, or say no.")
            try:
                self.add(suggestion["name"])
            except CategoryError:
                pass  # a category called that is there already: the messages go into it
            for message_id in chosen:
                name = self.assign(message_id, suggestion["name"], "person")
        conn = self._open()
        try:
            conn.execute(
                "UPDATE category_suggestions SET status = ?, decided_at = ? WHERE id = ?",
                ("accepted" if accept else "declined", datetime.now(timezone.utc).isoformat(), int(suggestion_id)),
            )
            conn.commit()
            return name or (self.assign_name(suggestion["name"]) if accept else None)
        finally:
            conn.close()

    def assign_name(self, name):
        """The current name of the category called `name`, or None."""
        conn = self._open()
        try:
            found = self._find(conn, name)
            return found[1] if found else None
        finally:
            conn.close()


def sort(book, client, model, message_id, text, tools_called=()):
    """Put one message of the person's in a category and say which: code first, then the model, then the one before it (else Chat). The model not answering at all loses nothing: the message still
    lands. Returns (the category's name as the person sees it, how it was decided)."""
    chosen, source = by_code(text, tools_called), "code"
    if chosen is None:
        try:
            chosen = by_model(client, model, text, book.categories())
        except Exception:  # noqa: BLE001 -- Ollama down or slow: the exchange is still sorted, by the next two rules
            chosen = None
        source = "model"
    if chosen is None:
        chosen, source = book.previous(message_id) or FALLBACK, "continued"
    return book.assign(message_id, chosen, source), source
