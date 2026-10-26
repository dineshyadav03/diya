"""Google Drive and Docs beyond making new things: search and read (DIYA-086, -092), rename, move, bin, restore and share (DIYA-088, -089, -090, -091), and edit a Doc (DIYA-094, -095; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Two new cards:

* **Google Drive (read)** (`drive.readonly`, off until the permission is added in Google and Connect is pressed): search your whole Drive by name, type, words inside or date; read a Google Doc, Slides or a text file (a Sheet as CSV);
  list a file's earlier versions. Reads only. What comes back is other people's words (a file can hold anything), so the Drive is NOT offered to the model as tools: code reads it for a plain request in the chat and a model with no tools words the answer, like the mail.
  A file that is not text (a PDF, a picture, a video) is listed by name and details and its contents are not read.
* **Google Drive (change)** (`drive.file`, the permission "make a folder or Doc" already uses): rename, move, put in the bin, bring back and share the files and folders **Diya made**, and add to or change the words in a Doc
  Diya made. It cannot see anything else in your Drive, so it cannot change anything else: that is Google's rule for this permission, not only Diya's.

The rules (docs/GOOGLE_CHANGES.md): a proposal the owner approves exactly as shown, never straight away; the file is found NOW by the words the person used (none or several refuses it); the file's version is checked again when the
action runs, so nothing is done to a file that changed or that you lost access to; a move shows where it comes from and where it goes, and how to put it back (the dry-run the task asks for); a bin is Drive's own bin, which keeps files
30 days, and a folder that holds files is not binned; sharing is with ONE address the person typed, for the role they said (view, comment or edit), by name and never "anyone with the link" or a whole domain; a Doc is changed
with the revision it was read at, so an edit made meanwhile means nothing is done; every change is read back; an outcome that is not known is `unknown` and never retried.

Importing this module has no side effects except naming what each card may ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import diya_connectors
import diya_google_cards
import diya_google_client as client
import diya_google_mailwrite as mw
import diya_google_write as gw
import diya_intent
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

DRIVE = "https://www.googleapis.com/drive/v3"
FILES = f"{DRIVE}/files"
DOCS = gw.DOCS_API
READ, CHANGE = "google_drive_read", "google_drive_change"
SCOPES = {READ: "https://www.googleapis.com/auth/drive.readonly", CHANGE: "https://www.googleapis.com/auth/drive.file"}
LABELS = {READ: "Google Drive (read)", CHANGE: "Google Drive (change)"}
FID = r"[A-Za-z0-9_-]{10,100}"
FOLDER, DOC, SHEET, SLIDES = gw.FOLDER_TYPE, "application/vnd.google-apps.document", "application/vnd.google-apps.spreadsheet", "application/vnd.google-apps.presentation"
KINDS = {"doc": DOC, "sheet": SHEET, "slides": SLIDES, "pdf": "application/pdf", "folder": FOLDER}
FILE_FIELDS = "id,name,mimeType,modifiedTime,size,version,parents,trashed,webViewLink,capabilities(canRename,canTrash,canEdit,canShare)"
LIST_FIELDS = f"files({FILE_FIELDS}),nextPageToken"
SHOWN = 15
READ_CHARS = 3000
MAX_TEXT_FILE = 200_000
EDIT_TEXT_MAX = 1500
ROLES = {"reader": "view", "commenter": "comment on", "writer": "edit"}
TOP_WORDS = ("my drive", "drive", "top", "the top", "top level", "root")
_F, _D = re.escape(FILES), re.escape(DOCS)

for _path in (_F, rf"{_F}/(?:root|{FID})", rf"{_F}/{FID}/export", rf"{_F}/{FID}/revisions"):
    client.allow(READ, "GET", _path)
for _path in (_F, rf"{_F}/(?:root|{FID})", rf"{_F}/{FID}/permissions", rf"{_D}/{FID}"):
    client.allow(CHANGE, "GET", _path)
client.allow(CHANGE, "PATCH", rf"{_F}/{FID}")
client.allow(CHANGE, "POST", rf"{_F}/{FID}/permissions")
client.allow(CHANGE, "DELETE", rf"{_F}/{FID}/permissions/[A-Za-z0-9_-]{{1,100}}")
client.allow(CHANGE, "POST", rf"{_D}/{FID}:batchUpdate")


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").casefold()).split())


def _esc(text):
    return str(text).replace("\\", "\\\\").replace("'", "\\'")


def _type_words(mime):
    return {FOLDER: "folder", DOC: "Google Doc", SHEET: "Google Sheet", SLIDES: "Google Slides", "application/pdf": "PDF"}.get(mime) or ("text file" if str(mime).startswith("text/") else "image" if str(mime).startswith("image/") else "file")


def _day(google_text):
    return str(google_text or "")[:16].replace("T", " ")


# ---- reading --------------------------------------------------------------------------------------------------------------------------------------

def _query(wanted, *, trashed=False, mime=None, not_mime=None, in_text=False, days=None):
    parts = [f"trashed={'true' if trashed else 'false'}"]
    if wanted:
        parts.append(f"{'fullText' if in_text else 'name'} contains '{_esc(wanted)}'")
    if mime:
        parts.append(f"mimeType='{mime}'")
    if not_mime:
        parts.append(f"mimeType!='{not_mime}'")
    if days:
        parts.append(f"modifiedTime > '{(datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')}'")
    return " and ".join(parts)


def _lookup(config, card, query, size=SHOWN + 1):
    items, _more = client.pages(config, card, LABELS[card], FILES, {"q": query, "pageSize": size, "orderBy": "modifiedTime desc", "fields": LIST_FIELDS}, "files", max_pages=1)
    return [f for f in items if isinstance(f.get("id"), str) and re.fullmatch(FID, f["id"]) and isinstance(f.get("name"), str)]


def _pick(files, wanted):
    """(the one file whose name is `wanted`, else the only one that contains it, None) or (None, why not, in words)."""
    exact = [f for f in files if _norm(f["name"]) == _norm(wanted)]
    chosen = exact or [f for f in files if _norm(wanted) in _norm(f["name"])]
    if not chosen:
        return None, f"there is no file called {diya_memory.printable(wanted, 60)!r}"
    if len(chosen) > 1:
        names = "; ".join(f"{diya_memory.printable(f['name'], 50)} ({_type_words(f.get('mimeType'))}, {_day(f.get('modifiedTime'))})" for f in chosen[:5])
        return None, f"{len(chosen)} files match {diya_memory.printable(wanted, 60)!r}: {names}. Ask which one, by its type or date, and do not choose"
    return chosen[0], None


NOT_CONNECTED = "Google Drive (read) is not connected."


class Said(str):
    """Words for the person, and how the look went (`status`): "found" (there is something to show), "nothing" (no file matched) or "problem" (it could not be read, or it was not clear which file). Compares and prints as the words."""

    status = "found"


def _said(text, status="found"):
    said = Said(text)
    said.status = status
    return said


def _which_file(config, name):
    """(the one file the person named, None) or (None, the Said that explains): used by reading a file and listing its versions."""
    if diya_connectors.read_token(config, READ) is None:
        return None, _said(NOT_CONNECTED, "problem")
    if not isinstance(name, str) or not name.strip():
        return None, _said("Say which file, by its name.", "problem")
    wanted = " ".join(re.sub(r"[^\w' &.-]", " ", name).split())[:80]
    try:
        file, problem = _pick(_lookup(config, READ, _query(wanted, not_mime=FOLDER)), wanted)
    except client.GoogleError as exc:
        return None, _said(str(exc), "problem")
    if problem:
        return None, _said(f"I could not tell which file: {problem}.", "nothing" if problem.startswith("there is no file") else "problem")
    return file, None


def search_drive(config, query=None, kind=None, days=None, in_text=False):
    """Files in the person's Drive, by name (or words inside), type and how recently they changed: each with its type and date. Never the contents."""
    if diya_connectors.read_token(config, READ) is None:
        return _said(NOT_CONNECTED, "problem")
    kind = kind if kind in KINDS else None
    days = days if isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 3650 else None
    wanted = " ".join(re.sub(r"[^\w' &.-]", " ", query or "").split())[:80] if isinstance(query, str) else ""
    try:
        files = _lookup(config, READ, _query(wanted, mime=KINDS.get(kind), days=days, in_text=in_text is True))
    except client.GoogleError as exc:
        return _said(str(exc), "problem")
    if not files:
        return _said(f"Nothing in your Google Drive matches{f' {diya_memory.printable(wanted, 60)!r}' if wanted else ''}.", "nothing")
    lines = [f"- {diya_memory.printable(f['name'], 100)} ({_type_words(f.get('mimeType'))}, changed {_day(f.get('modifiedTime'))})" for f in files[:SHOWN]]
    if len(files) > SHOWN:
        lines.append(f"(Only the first {SHOWN} are shown; narrow the search to see others.)")
    return _said("Google Drive:\n" + "\n".join(lines))


def _numbered(text):
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    return "\n".join(f"[¶{n}] {line[:300]}" for n, line in enumerate(lines[:60], 1)) + ("\n(Only the first 60 paragraphs are shown.)" if len(lines) > 60 else "")


def read_file(config, name):
    """The text of one file the person named: a Google Doc or Slides as numbered paragraphs (so they can be cited), a Sheet as CSV, a plain text file; anything else by its details only. Cut short."""
    file, why = _which_file(config, name)
    if why is not None:
        return why
    mime, file_id = file.get("mimeType"), file["id"]
    head = f"{diya_memory.printable(file['name'], 100)} ({_type_words(mime)}, version {diya_memory.printable(file.get('version', '?'), 20)}, changed {_day(file.get('modifiedTime'))})"
    try:
        if mime in (DOC, SLIDES):
            body = _numbered(client.read_text(config, READ, LABELS[READ], f"{FILES}/{file_id}/export", {"mimeType": "text/plain"}, READ_CHARS + 200)[:READ_CHARS])
        elif mime == SHEET:
            rows = client.read_text(config, READ, LABELS[READ], f"{FILES}/{file_id}/export", {"mimeType": "text/csv"}, READ_CHARS + 200)[:READ_CHARS].splitlines()
            body = "\n".join(f"[row {n}] {row[:300]}" for n, row in enumerate(rows[:40], 1))
        elif str(mime).startswith("text/") or mime == "application/json":
            size = str(file.get("size") or "")
            if size.isdigit() and int(size) > MAX_TEXT_FILE:
                return _said(f"{head}\nThis file is larger than Diya reads ({MAX_TEXT_FILE // 1000} KB), so only its details are shown.", "details")
            body = _numbered(client.read_text(config, READ, LABELS[READ], f"{FILES}/{file_id}", {"alt": "media"}, READ_CHARS + 200)[:READ_CHARS])
        else:
            return _said(f"{head}\nThis is not a kind of file Diya reads the contents of; only its details are shown.", "details")
    except client.GoogleError as exc:
        return _said(str(exc), "problem")
    return _said(f"{head}\n{body}" + ("\n(Cut short.)" if len(body) >= READ_CHARS - 50 else ""))


def list_revisions(config, name):
    """The earlier versions of one file the person named: when, and by whom."""
    file, why = _which_file(config, name)
    if why is not None:
        return why
    try:
        data = client.read(config, READ, LABELS[READ], f"{FILES}/{file['id']}/revisions", {"pageSize": 10, "fields": "revisions(id,modifiedTime,lastModifyingUser(displayName))"})
    except client.GoogleError as exc:
        return _said(str(exc), "problem")
    revisions = [r for r in (data.get("revisions") or []) if isinstance(r, dict)]
    if not revisions:
        return _said(f"{diya_memory.printable(file['name'], 100)} has no earlier versions that Google keeps.", "details")
    lines = [f"- {_day(r.get('modifiedTime'))} by {diya_memory.printable((r.get('lastModifyingUser') or {}).get('displayName') or 'someone', 40)}" for r in revisions[-10:]]
    return _said(f"Versions of {diya_memory.printable(file['name'], 100)}, oldest first:\n" + "\n".join(lines))


# ---- the chat's way in: a plain request to look through the Drive (the model is given no tool) -----------------------------------------------
#
# What a file says is written by anyone, so the Drive is NOT offered to the model as tools (that would put the whole Drive, other people's words and the web search side by side in one turn: docs/AUTHORITY_MODEL.md, "the one
# open accounting"). Like the mail, code reads, and a model with no tools words the answer. `request` says what the person asked for; `run` does the read.

_MAX_ASK = 200
_LEAD = r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*"
_NOUN = r"(?:file|doc|document|sheet|spreadsheet|slides?|presentation|pdf)"
_OF = r"(?:in|on|from)\s+(?:my\s+)?(?:google\s+)?drive"
_NAME = r"(?P<name>[A-Za-z0-9][A-Za-z0-9 '&._-]{0,78}?)"
_SEARCH = (
    re.compile(_LEAD + r"(?:search|look\s+(?:through|in)|find|list|show)\s+(?:me\s+)?(?:in\s+)?(?:my\s+|the\s+)?(?:google\s+)?drive(?:\s+(?:for|about)\s+(?P<q>[^?]+?))?\s*\??$", re.IGNORECASE),
    re.compile(_LEAD + r"(?:find|search\s+for|show|list)\s+(?:me\s+)?(?:my\s+|the\s+|any\s+|all\s+)?(?P<q>[^?]*?)\s*(?P<kind>" + _NOUN + r")s?\s+" + _OF + r"\s*\??$", re.IGNORECASE),
    re.compile(_LEAD + r"(?:what|which)\s+(?:files|docs|documents|sheets)\s+do\s+i\s+have\s+(?:about|on)\s+(?P<q>.+?)\s+" + _OF + r"\s*\??$", re.IGNORECASE),
)
_READ = (
    re.compile(_LEAD + r"(?:read|open|show|summari[sz]e)\s+(?:me\s+)?(?:the\s+|my\s+)?" + _NOUN + r"\s+(?:called\s+|named\s+)?" + _NAME + r"(?:\s+" + _OF + r")?\s*\??$", re.IGNORECASE),
    re.compile(_LEAD + r"(?:read|open|show|summari[sz]e)\s+(?:me\s+)?(?:the\s+|my\s+)?" + _NAME + r"\s+" + _NOUN + r"(?:\s+" + _OF + r")?\s*\??$", re.IGNORECASE),
    re.compile(_LEAD + r"(?:read|open|show|summari[sz]e)\s+(?:me\s+)?(?:the\s+|my\s+)?" + _NAME + r"\s+" + _OF + r"\s*\??$", re.IGNORECASE),
    re.compile(_LEAD + r"what\s+(?:does|do)\s+(?:my\s+|the\s+)?" + _NAME + r"\s+" + _NOUN + r"\s+say\s*\??$", re.IGNORECASE),
)
_VERSIONS = (
    re.compile(_LEAD + r"(?:what\s+are\s+)?(?:the\s+)?(?:earlier\s+versions?|older\s+versions?|version\s+history|revisions?|history)\s+of\s+(?:the\s+|my\s+)?" + _NAME + r"(?:\s+" + _NOUN + r")?\s*\??$", re.IGNORECASE),
    re.compile(_LEAD + r"who\s+(?:changed|edited)\s+(?:the\s+|my\s+)?" + _NAME + r"(?:\s+" + _NOUN + r")?\s*\??$", re.IGNORECASE),
)
_KIND_OF_NOUN = {"doc": "doc", "document": "doc", "sheet": "sheet", "spreadsheet": "sheet", "slide": "slides", "slides": "slides", "presentation": "slides", "pdf": "pdf"}


def request(text):
    """{"action": "search"|"read"|"versions", ...} when the message is a plain request to look through the person's Google Drive, else None. Not a request to change anything, not a question about something else, not a long message."""
    if not isinstance(text, str) or not text.strip() or len(text) > _MAX_ASK or "\n" in text.strip():
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    if any(change(flat) for change in (asks.renames_drive_file, asks.moves_drive_file, asks.trashes_drive_file, asks.restores_drive_file, asks.shares_drive_file, asks.unshares_drive_file, asks.edits_google_doc)):
        return None
    said_drive = re.search(r"\bdrive\b", flat, re.IGNORECASE) is not None
    for pattern in _SEARCH:
        found = pattern.search(flat)
        if found:
            groups = found.groupdict()
            query = re.sub(r"^(?:my|the|any|all)\s+", "", " ".join((groups.get("q") or "").split()).strip(" .'-"), flags=re.IGNORECASE)
            return {"action": "search", "query": query, "kind": _KIND_OF_NOUN.get((groups.get("kind") or "").lower()), "said_drive": True}
    for pattern in _VERSIONS:
        found = pattern.search(flat)
        if found:
            return {"action": "versions", "name": " ".join(found.group("name").split()).strip(" .'-"), "said_drive": said_drive}
    for pattern in _READ:
        found = pattern.search(flat)
        if found:
            name = " ".join(found.group("name").split()).strip(" .'-")
            if name and not re.fullmatch(r"(?:it|that|this|them|news|email|mail|messages?)", name, re.IGNORECASE):
                return {"action": "read", "name": name, "said_drive": said_drive}
    return None


def run(config, found):
    """The answer to a request (see `request`) as text, built by code from what Google says: a list, the numbered paragraphs of a file, or its earlier versions."""
    if found["action"] == "search":
        return search_drive(config, found.get("query") or None, found.get("kind"))
    if found["action"] == "versions":
        return list_revisions(config, found["name"])
    return read_file(config, found["name"])


# ---- finding the one file Diya made -----------------------------------------------------------------------------------------------------------------

def _own(value, said):
    """`value` (a name the model gave) if the person said it themselves, cleaned; else ''."""
    if not isinstance(value, str) or not value.strip() or not diya_intent.said_in(value, said):
        return ""
    return " ".join(re.sub(r"[^\w' &.-]", " ", value).split())[:80]


def find_file(config, name, said, *, trashed=False, folder=None, mime=None):
    """The one file or folder Diya made (the only kind this card can see) whose name has the words the person used (a read); InvalidArgs, with words, for none or several."""
    wanted = _own(name, said)
    if not wanted:
        raise InvalidArgs("say which file, by its name, in the user's own words; I do not choose one")
    try:
        files = _lookup(config, CHANGE, _query(wanted, trashed=trashed, mime=FOLDER if folder is True else mime, not_mime=FOLDER if folder is False else None))
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    file, problem = _pick(files, wanted)
    if problem:
        raise InvalidArgs(f"{problem} (only files and folders that Diya made can be changed; ask the user which one)")
    return file


def _ref(file):
    return {"name": diya_memory.printable(file["name"], 100), "file_id": file["id"], "version": diya_memory.printable(file.get("version") or "", 30)}


def _validate_ref(args):
    if not isinstance(args.get("file_id"), str) or not re.fullmatch(FID, args["file_id"]):
        raise InvalidArgs("a change needs the file found by its name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("name"), "a file")
    if not isinstance(args.get("version", ""), str) or len(args.get("version", "")) > 30:
        raise InvalidArgs("the file's version is not usable")


def _can(file, ability):
    return (file.get("capabilities") or {}).get(ability, True) is not False


def _still_the_same(config, args, *, trashed=False):
    """The file as it is now; ActionFailed (nothing done) if it is gone, in the wrong place (bin or not), changed since the proposal, or no longer something you may change."""
    try:
        now = client.read(config, CHANGE, LABELS[CHANGE], f"{FILES}/{args['file_id']}", {"fields": FILE_FIELDS})
    except client.GoogleError as exc:
        if exc.kind == "not_found":
            raise ActionFailed("That file is not in your Drive any more, or Diya can no longer see it, so nothing was done.")
        raise ActionFailed(f"{exc} Nothing was done.")
    if bool(now.get("trashed")) != trashed:
        raise ActionFailed(f"That file is {'in the bin' if now.get('trashed') else 'not in the bin'}, so nothing was done.")
    if args.get("version") and now.get("version") and str(now["version"]) != args["version"]:
        raise ActionFailed(f"{args['name']} was changed in Google Drive after it was proposed, so nothing was done. Look at it in Google and ask again if you still want this.")
    return now


def _patch(body, params, doing):
    """What a change to a file asks of the one client (its send, called in the kind's execute function): the fields to read back, the changes, and what is being done in words."""
    return {"params": dict({"fields": FILE_FIELDS}, **params), "body": body, "doing": doing}


def _verify(config, args, check, what):
    try:
        found = client.read(config, CHANGE, LABELS[CHANGE], f"{FILES}/{args['file_id']}", {"fields": FILE_FIELDS})
    except client.GoogleError:
        raise ActionUncertain(f"Google said {what} was done, but reading it back to check did not work, so it is not confirmed. Look in Google Drive, then record what you found.")
    problem = check(found)
    if problem:
        raise ActionUncertain(f"Google said {what} was done, but reading it back showed {problem}, so it is not confirmed. Look in Google Drive, then record what you found.")
    return found


# ---- rename -----------------------------------------------------------------------------------------------------------------------------------------

def _clean_name(value, what):
    gw._clean_title(value, what)
    if any(ch in value for ch in "/\\<>:\"|?*"):
        raise InvalidArgs(f"{what}'s name cannot have / \\ < > : \" | ? or * in it")


def rename_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "new_name")}
    if not gw._own_words(kept.get("new_name"), text):
        kept.pop("new_name", None)
    return kept, ["The new name was left out because it was not in the user's words."] if "new_name" not in kept else []


def rename_resolve(config, args, said):
    if not args.get("new_name"):
        raise InvalidArgs("say what to rename it to, in the user's own words; I do not choose a name")
    file = find_file(config, args.get("name"), said)
    if not _can(file, "canRename"):
        raise InvalidArgs(f"you may not rename {diya_memory.printable(file['name'], 60)}")
    if file["name"] == args["new_name"]:
        raise InvalidArgs("it already has that name")
    return dict(_ref(file), new_name=args["new_name"])


def rename_validate(args):
    gw._only(args, {"name", "file_id", "version", "new_name"}, "renaming a file")
    _validate_ref(args)
    _clean_name(args.get("new_name"), "a file")


def rename_render(args):
    return f"Rename the Drive file '{diya_memory.printable(args['name'], 90)}' to '{diya_memory.printable(args['new_name'], 90)}' (undo: rename it back)"


def rename_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CHANGE, LABELS[CHANGE], "PATCH", f"{FILES}/{args['file_id']}", **_patch({"name": args["new_name"]}, {}, f"renaming '{args['name']}'"))
    _verify(config, args, lambda f: "" if f.get("name") == args["new_name"] else "a different name", f"renaming '{args['name']}'")
    return f"Renamed in your Google Drive and read back to check: '{args['name']}' is now '{args['new_name']}'."


# ---- move (with the dry run shown: from where, to where, how to put it back) ----------------------------------------------------------------

def _parent_name(config, parent_id):
    try:
        found = client.read(config, CHANGE, LABELS[CHANGE], f"{FILES}/{parent_id}", {"fields": "id,name"})
        return diya_memory.printable(found.get("name") or "a folder", 60)
    except client.GoogleError:
        return "a folder Diya cannot name"


def _root_id(config):
    try:
        return client.read(config, CHANGE, LABELS[CHANGE], f"{FILES}/root", {"fields": "id"}).get("id")
    except client.GoogleError:
        return None


def move_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "to")}
    return kept, []


def move_resolve(config, args, said):
    file = find_file(config, args.get("name"), said, folder=False)
    parents = [p for p in (file.get("parents") or []) if isinstance(p, str)]
    if len(parents) != 1:
        raise InvalidArgs(f"{diya_memory.printable(file['name'], 60)} is not in exactly one place, so it is not moved")
    to = args.get("to")
    if not isinstance(to, str) or not diya_intent.said_in(to, said):
        raise InvalidArgs("say which folder it goes into, by its name, in the user's own words (or 'My Drive' for the top); I do not choose")
    if _norm(to) in TOP_WORDS:
        to_id, to_name = "root", "the top of My Drive"
    else:
        target = find_file(config, to, said, folder=True)
        to_id, to_name = target["id"], diya_memory.printable(target["name"], 60)
    root = _root_id(config)
    from_id = parents[0]
    from_name = "the top of My Drive" if from_id == root else _parent_name(config, from_id)
    if to_id == from_id or (to_id == "root" and from_id == root):
        raise InvalidArgs(f"{diya_memory.printable(file['name'], 60)} is already there")
    return dict(_ref(file), from_id=from_id, from_name=from_name, to_id=to_id, to_name=to_name)


def move_validate(args):
    gw._only(args, {"name", "file_id", "version", "from_id", "from_name", "to_id", "to_name"}, "moving a file")
    _validate_ref(args)
    for key in ("from_id", "to_id"):
        if not isinstance(args.get(key), str) or not re.fullmatch(rf"(?:root|{FID})", args[key]):
            raise InvalidArgs("a folder is found by its name; it cannot be given an id")
    gw._clean_title(args.get("from_name"), "a folder")
    gw._clean_title(args.get("to_name"), "a folder")


def move_render(args):
    return (f"Move the Drive file '{diya_memory.printable(args['name'], 70)}' from '{diya_memory.printable(args['from_name'], 50)}' into '{diya_memory.printable(args['to_name'], 50)}' "
            f"(undo: move it back into '{diya_memory.printable(args['from_name'], 50)}')")


def move_execute(config, args):
    now = _still_the_same(config, args)
    if [p for p in (now.get("parents") or []) if p] != [args["from_id"]]:
        raise ActionFailed("That file is not where it was when the move was proposed, so nothing was done.")
    client.send(config, CHANGE, LABELS[CHANGE], "PATCH", f"{FILES}/{args['file_id']}", **_patch({}, {"addParents": args["to_id"], "removeParents": args["from_id"]}, f"moving '{args['name']}'"))
    wanted = args["to_id"] if args["to_id"] != "root" else _root_id(config)
    _verify(config, args, lambda f: "" if wanted and [p for p in (f.get("parents") or [])] == [wanted] else "it in a different place", f"moving '{args['name']}'")
    return f"Moved in your Google Drive and read back to check: '{args['name']}' is now in '{args['to_name']}' (it was in '{args['from_name']}')."


# ---- the bin, and back -------------------------------------------------------------------------------------------------------------------------

def trash_resolve(config, args, said):
    file = find_file(config, args.get("name"), said)
    if not _can(file, "canTrash"):
        raise InvalidArgs(f"you may not put {diya_memory.printable(file['name'], 60)} in the bin")
    if file.get("mimeType") == FOLDER:
        try:
            inside = _lookup(config, CHANGE, f"'{file['id']}' in parents and trashed=false", size=1)
        except client.GoogleError as exc:
            raise InvalidArgs(f"{exc} Nothing was proposed.")
        if inside:
            raise InvalidArgs(f"the folder {diya_memory.printable(file['name'], 60)} holds files, so it is not binned; move or bin them one at a time first")
    return dict(_ref(file), kind="folder" if file.get("mimeType") == FOLDER else "file")


def trash_validate(args):
    gw._only(args, {"name", "file_id", "version", "kind"}, "putting a file in the bin")
    _validate_ref(args)
    if args.get("kind") not in ("file", "folder"):
        raise InvalidArgs("it is a file or a folder")


def trash_render(args):
    return f"Move the Drive {args['kind']} '{diya_memory.printable(args['name'], 100)}' to the bin (Drive keeps it there 30 days; bring it back from the bin or by asking Diya)"


def trash_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CHANGE, LABELS[CHANGE], "PATCH", f"{FILES}/{args['file_id']}", **_patch({"trashed": True}, {}, f"binning '{args['name']}'"))
    _verify(config, args, lambda f: "" if f.get("trashed") is True else "a file that is not in the bin", f"binning '{args['name']}'")
    return f"Moved to the bin of your Google Drive and read back to check: '{args['name']}'. It stays there 30 days."


def restore_resolve(config, args, said):
    file = find_file(config, args.get("name"), said, trashed=True)
    return dict(_ref(file), kind="folder" if file.get("mimeType") == FOLDER else "file")


def restore_render(args):
    return f"Bring the Drive {args['kind']} '{diya_memory.printable(args['name'], 100)}' back from the bin"


def restore_execute(config, args):
    _still_the_same(config, args, trashed=True)
    client.send(config, CHANGE, LABELS[CHANGE], "PATCH", f"{FILES}/{args['file_id']}", **_patch({"trashed": False}, {}, f"bringing back '{args['name']}'"))
    _verify(config, args, lambda f: "" if f.get("trashed") is False else "a file that is still in the bin", f"bringing back '{args['name']}'")
    return f"Brought back from the bin and read back to check: '{args['name']}'."


# ---- sharing: one typed address, the role they said, never public ---------------------------------------------------------------------------------

_ROLE_WORDS = {"reader": r"\b(?:view\w*|read\w*|see)\b", "commenter": r"\bcomment\w*\b", "writer": r"\b(?:edit\w*|write|change)\b"}


def share_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "email", "role")}
    kept["email"] = mw.precheck_recipients(kept.get("email"), text, "the person to share with")
    if len(mw._split(kept["email"])) != 1:
        raise InvalidArgs("a file is shared with one person at a time")
    pattern = _ROLE_WORDS.get(kept.get("role"))
    if not pattern or not re.search(pattern, text, re.IGNORECASE):
        raise InvalidArgs("say whether they can view, comment or edit, in the user's own words; I do not choose")
    return kept, []


def _permissions(config, file_id):
    data = client.read(config, CHANGE, LABELS[CHANGE], f"{FILES}/{file_id}/permissions", {"fields": "permissions(id,type,role,emailAddress)"})
    return [p for p in (data.get("permissions") or []) if isinstance(p, dict)]


def share_resolve(config, args, said):
    file = find_file(config, args.get("name"), said)
    if not _can(file, "canShare"):
        raise InvalidArgs(f"you may not share {diya_memory.printable(file['name'], 60)}")
    email, note = mw.people(config, args["email"], said, "the person to share with")  # an address typed stays as typed; a name is one contact with one address (the card says so)
    if len(mw._split(email)) != 1:
        raise InvalidArgs("a file is shared with one person at a time")
    args = dict(args, email=email)
    try:
        have = [p for p in _permissions(config, file["id"]) if str(p.get("emailAddress", "")).lower() == args["email"].lower()]
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    order = ("reader", "commenter", "writer")
    if have and have[0].get("role") in order and order.index(have[0]["role"]) >= order.index(args["role"]):
        raise InvalidArgs(f"{args['email']} can already {ROLES[have[0]['role']]} it")
    return dict(_ref(file), email=args["email"], role=args["role"], **({"contacts": note} if note else {}))


def share_validate(args):
    gw._only(args, {"name", "file_id", "version", "email", "role", "contacts"}, "sharing a file")
    _validate_ref(args)
    mw._line(args.get("contacts"), "the note about the contacts used", 200, required=False)
    if len(mw._addresses(args.get("email"), "the person to share with")) != 1:
        raise InvalidArgs("a file is shared with one person at a time")
    if args.get("role") not in ROLES:
        raise InvalidArgs("a file is shared to view, to comment or to edit")


def share_render(args):
    via = f" ({diya_memory.printable(args['contacts'], 50)})" if args.get("contacts") else ""
    return f"Share the Drive file '{diya_memory.printable(args['name'], 70)}' with {args['email']}{via} so they can {ROLES[args['role']]} it (Google emails them; only that address, never anyone with the link)"


def share_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CHANGE, LABELS[CHANGE], "POST", f"{FILES}/{args['file_id']}/permissions", params={"sendNotificationEmail": "true", "fields": "id,type,role,emailAddress"},
                body={"type": "user", "role": args["role"], "emailAddress": args["email"]}, doing=f"sharing '{args['name']}'")
    try:
        found = [p for p in _permissions(config, args["file_id"]) if str(p.get("emailAddress", "")).lower() == args["email"].lower() and p.get("type") == "user"]
    except client.GoogleError:
        raise ActionUncertain("Google said the file was shared, but reading to check did not work, so it is not confirmed. Look in Google Drive, then record what you found.")
    if not found or found[0].get("role") != args["role"]:
        raise ActionUncertain("Google said the file was shared, but reading it back showed something different, so it is not confirmed. Look in Google Drive, then record what you found.")
    return f"Shared '{args['name']}' with {args['email']} ({args['role']}) and read back to check; Google emailed them."


def unshare_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "email")}
    kept["email"] = mw.own_recipients(kept.get("email"), text, "the person to stop sharing with")
    if len(mw._split(kept["email"])) != 1:
        raise InvalidArgs("a file is unshared from one person at a time")
    return kept, []


def unshare_resolve(config, args, said):
    file = find_file(config, args.get("name"), said)
    try:
        have = [p for p in _permissions(config, file["id"]) if str(p.get("emailAddress", "")).lower() == args["email"].lower() and p.get("type") == "user"]
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    if not have or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(have[0].get("id"))):
        raise InvalidArgs(f"{diya_memory.printable(file['name'], 60)} is not shared with {args['email']}")
    return dict(_ref(file), email=args["email"], permission_id=have[0]["id"])


def unshare_validate(args):
    gw._only(args, {"name", "file_id", "version", "email", "permission_id"}, "unsharing a file")
    _validate_ref(args)
    if len(mw._addresses(args.get("email"), "the person")) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(args.get("permission_id"))):
        raise InvalidArgs("a file is unshared from one person, found by its address")


def unshare_render(args):
    return f"Stop sharing the Drive file '{diya_memory.printable(args['name'], 90)}' with {args['email']} (they lose access; share it again to give it back)"


def unshare_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CHANGE, LABELS[CHANGE], "DELETE", f"{FILES}/{args['file_id']}/permissions/{args['permission_id']}", ok=(200, 204), doing=f"unsharing '{args['name']}'")
    try:
        left = [p for p in _permissions(config, args["file_id"]) if str(p.get("emailAddress", "")).lower() == args["email"].lower()]
    except client.GoogleError:
        raise ActionUncertain("Google said the file was unshared, but reading to check did not work, so it is not confirmed. Look in Google Drive, then record what you found.")
    if left:
        raise ActionUncertain("Google said the file was unshared, but they still have access, so it is not confirmed. Look in Google Drive, then record what you found.")
    return f"Stopped sharing '{args['name']}' with {args['email']} and read back to check."


# ---- edit a Doc Diya made, with the revision it was read at -------------------------------------------------------------------------------

def edit_prepare(args, text):
    """The words to find and the words to put are the person's; text to ADD is shown whole for the approval."""
    kept = {k: v for k, v in args.items() if k in ("name", "mode", "text", "find")}
    if kept.get("mode") not in ("append", "replace"):
        raise InvalidArgs("a document is added to (append) or has words replaced (replace)")
    if kept["mode"] == "replace" and not (gw._own_words(kept.get("find"), text) and gw._own_words(kept.get("text"), text)):
        raise InvalidArgs("to change words in a document the user must have said both the old words and the new words; ask them, and do not choose")
    if kept["mode"] == "append":
        kept.pop("find", None)
    return kept, []


def _doc(config, file_id):
    return client.read(config, CHANGE, LABELS[CHANGE], f"{DOCS}/{file_id}")


def edit_resolve(config, args, said):
    file = find_file(config, args.get("name"), said, mime=DOC)
    try:
        doc = _doc(config, file["id"])
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    revision = doc.get("revisionId")
    if not isinstance(revision, str) or not revision or len(revision) > 200:
        raise InvalidArgs("Google gave that document no version to guard the edit with, so it is not edited")
    resolved = {"name": diya_memory.printable(file["name"], 100), "file_id": file["id"], "revision": revision, "mode": args["mode"], "text": args.get("text")}
    if args["mode"] == "replace":
        count = gw._document_text(doc).count(args["find"])
        if not 1 <= count <= 10:
            raise InvalidArgs(f"{args['find']!r} is in the document {count} times; a change is made when it is there 1 to 10 times")
        resolved["find"], resolved["count"] = args["find"], count
    return resolved


def edit_validate(args):
    gw._only(args, {"name", "file_id", "revision", "mode", "text", "find", "count"}, "editing a document")
    if not isinstance(args.get("file_id"), str) or not re.fullmatch(FID, args["file_id"]):
        raise InvalidArgs("a document is found by its name; it cannot be given an id")
    gw._clean_title(args.get("name"), "a document")
    if not isinstance(args.get("revision"), str) or not args["revision"] or len(args["revision"]) > 200:
        raise InvalidArgs("the document's version is not usable")
    if args.get("mode") not in ("append", "replace"):
        raise InvalidArgs("a document is added to (append) or has words replaced (replace)")
    text = args.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > EDIT_TEXT_MAX:
        raise InvalidArgs(f"the words to put in are 1 to {EDIT_TEXT_MAX} characters")
    if args["mode"] == "replace":
        if not isinstance(args.get("find"), str) or not args["find"].strip() or len(args["find"]) > 300 or not isinstance(args.get("count"), int) or isinstance(args.get("count"), bool) or not 1 <= args["count"] <= 10:
            raise InvalidArgs("words to replace need the old words and how many places they are in (1 to 10)")
    elif "find" in args or "count" in args:
        raise InvalidArgs("adding to the end has no words to find")


def edit_render(args):
    if args["mode"] == "append":
        return f"Add to the end of the Google Doc '{diya_memory.printable(args['name'], 70)}': {diya_memory.printable(args['text'], 160)} (the whole text is in the fields below)"
    return f"In the Google Doc '{diya_memory.printable(args['name'], 60)}' change '{diya_memory.printable(args['find'], 70)}' to '{diya_memory.printable(args['text'], 70)}' in {args['count']} place{'s' if args['count'] != 1 else ''}"


def edit_execute(config, args):
    try:
        doc = _doc(config, args["file_id"])
    except client.GoogleError as exc:
        raise ActionFailed(f"That document could not be read ({exc}), so nothing was done.")
    if doc.get("revisionId") != args["revision"]:
        raise ActionFailed(f"{args['name']} was changed (by you or someone else) after this edit was proposed, so nothing was done and the document is as it was. Look at it in Google and ask again if you still want this.")
    before = gw._document_text(doc)
    if args["mode"] == "append":
        request = {"insertText": {"endOfSegmentLocation": {"segmentId": ""}, "text": "\n" + args["text"]}}
    else:
        if before.count(args["find"]) != args["count"]:
            raise ActionFailed("The words are not in the document the number of times they were when this was proposed, so nothing was done.")
        request = {"replaceAllText": {"containsText": {"text": args["find"], "matchCase": True}, "replaceText": args["text"]}}
    response = client.send(config, CHANGE, LABELS[CHANGE], "POST", f"{DOCS}/{args['file_id']}:batchUpdate", body={"requests": [request], "writeControl": {"requiredRevisionId": args["revision"]}}, doing=f"editing '{args['name']}'")
    if args["mode"] == "replace":
        changed = (((client.as_json(response).get("replies") or [{}])[0] or {}).get("replaceAllText") or {}).get("occurrencesChanged")
        if changed != args["count"]:
            raise ActionUncertain(f"Google said the document was edited, but changed {changed} places and {args['count']} were asked for, so it is not confirmed. Look in Google Docs, then record what you found.")
    try:
        after = gw._document_text(_doc(config, args["file_id"]))
    except client.GoogleError:
        raise ActionUncertain("Google said the document was edited, but reading it back to check did not work, so it is not confirmed. Look in Google Docs, then record what you found.")
    if args["text"] not in after or (args["mode"] == "replace" and after.count(args["text"]) < args["count"]):
        raise ActionUncertain("Google said the document was edited, but reading it back did not show the new words, so it is not confirmed. Look in Google Docs, then record what you found.")
    return f"Edited the Google Doc '{args['name']}' and read it back to check ({'added to the end' if args['mode'] == 'append' else str(args['count']) + ' place(s) changed'})."


# ---- the kinds, their tools and the cards -------------------------------------------------------------------------------------------------------

def _kind(name, label, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=CHANGE, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is changed until the user approves it on the Actions page. It works only on files and folders Diya made.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


NAME = {"type": "string", "description": "The name of the file or folder, exactly as the user said it."}


def action_kinds():
    return (
        _kind("google_drive_rename", "Rename a Drive file", "propose_rename_drive_file", "Propose renaming one file or folder in the user's Google Drive. Use it only when the user asks for that, naming it and the new name.",
              {"name": NAME, "new_name": {"type": "string", "description": "The new name, exactly as the user said it."}}, ["name", "new_name"], validate=rename_validate, render=rename_render, execute=rename_execute,
              asked=asks.renames_drive_file, prepare=rename_prepare, resolve=rename_resolve),
        _kind("google_drive_move", "Move a Drive file", "propose_move_drive_file", "Propose moving one file into a folder (or to the top of My Drive) in the user's Google Drive. Use it only when the user asks for that, naming the file and the folder.",
              {"name": NAME, "to": {"type": "string", "description": "The folder's name as the user said it, or 'My Drive' for the top."}}, ["name", "to"], validate=move_validate, render=move_render, execute=move_execute,
              asked=asks.moves_drive_file, prepare=move_prepare, resolve=move_resolve),
        _kind("google_drive_trash", "Put a Drive file in the bin", "propose_trash_drive_file", "Propose putting one file (or an empty folder) in the Google Drive bin, which keeps it 30 days. Use it only when the user asks for that, naming it.",
              {"name": NAME}, ["name"], validate=trash_validate, render=trash_render, execute=trash_execute, asked=asks.trashes_drive_file, resolve=trash_resolve),
        _kind("google_drive_restore", "Bring a Drive file back", "propose_restore_drive_file", "Propose bringing one file or folder back from the Google Drive bin. Use it only when the user asks for that, naming it.",
              {"name": NAME}, ["name"], validate=trash_validate, render=restore_render, execute=restore_execute, asked=asks.restores_drive_file, resolve=restore_resolve),
        _kind("google_drive_share", "Share a Drive file", "propose_share_drive_file",
              "Propose sharing one file with ONE email address the user typed, as a viewer, commenter or editor as they said. Google emails them. Never for 'anyone with the link'. Use it only when the user asks for that.",
              {"name": NAME, "email": {"type": "string", "description": "The email address exactly as the user typed it, or the person's name exactly as the user said it (Diya looks a name up in their contacts). Never guess an address."}, "role": {"type": "string", "enum": list(ROLES), "description": "reader (view), commenter or writer (edit), as the user said."}},
              ["name", "email", "role"], validate=share_validate, render=share_render, execute=share_execute, asked=asks.shares_drive_file, prepare=share_prepare, resolve=share_resolve),
        _kind("google_drive_unshare", "Stop sharing a Drive file", "propose_unshare_drive_file", "Propose stopping the sharing of one file with one email address the user typed. Use it only when the user asks for that.",
              {"name": NAME, "email": {"type": "string", "description": "The email address, exactly as the user typed it."}}, ["name", "email"], validate=unshare_validate, render=unshare_render, execute=unshare_execute,
              asked=asks.unshares_drive_file, prepare=unshare_prepare, resolve=unshare_resolve),
        _kind("google_docs_edit", "Edit a Google Doc", "propose_edit_google_doc",
              "Propose adding text to the end of a Google Doc, or changing words in it (the user must have said the old and the new words). Use it only when the user asks for that, naming the Doc.",
              {"name": NAME, "mode": {"type": "string", "enum": ["append", "replace"], "description": "append: add to the end; replace: change words."}, "text": {"type": "string", "description": "The words to add, or the new words, on one line."},
               "find": {"type": "string", "description": "Only for replace: the old words, exactly as the user said them."}}, ["name", "mode", "text"], validate=edit_validate, render=edit_render, execute=edit_execute,
              asked=asks.edits_google_doc, prepare=edit_prepare, resolve=edit_resolve),
    )


def connectors():
    return (
        diya_google_cards.card(READ, LABELS[READ], "Search your whole Drive and read a file when you ask: Docs, Slides, Sheets and text files. Nothing is changed.", SCOPES[READ], "Google Drive API",
                               ("Searches your Drive by name, words inside, type and date, and reads a Google Doc, Slides, a Sheet or a text file when you ask.", "Lists a file's earlier versions.",
                                "Cannot change, move, share or delete anything, and does not read pictures, PDFs or videos.")),
        diya_google_cards.card(CHANGE, LABELS[CHANGE], "Rename, move, bin, bring back and share the files Diya made, and change the words in a Doc Diya made, when you approve each one.", SCOPES[CHANGE], "Google Drive API and Google Docs API",
                               ("Renames, moves, puts in the bin, brings back and shares files and folders Diya made, and adds to or changes the words in a Doc Diya made, only when you approve that one change.",
                                "Sees only what Diya made itself (the narrow drive.file permission), so it cannot touch anything else in your Drive.",
                                "Cannot share with anyone you did not name by address, make anything public, or delete for good.")),
    )
