"""Gmail beyond reading: drafts, sending, replying, forwarding and filing mail, each only when you approve it (DIYA-075, -076, -077, -078, -113; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Three new cards, each with ONE narrow Google permission, off until you add that permission in your Google project and press Connect:

* **Gmail: drafts** (`gmail.compose`): save a draft or replace one, and throw one away. Its list of allowed requests has no way to send: sending is the separate card below, held apart in Diya's code (Google's own
  permission for drafts is wider than that, which is why the list, and the test that pins it, matter).
* **Gmail: send** (`gmail.send`): send one email, reply to one, or forward one.
* **Gmail: organise** (`gmail.modify`): archive, mark read or unread, star, put one of your own labels on or take it off, move to the bin and bring back. It never deletes for good: that request is not on its list.

Replying and forwarding find the message through the Gmail READ card, so that card must be connected too.

Sending reaches other people, so it is the riskiest thing here (risk level 3) and has the strictest rules, all in code:

* **Recipients are only what the person typed.** Every address is checked to be in the person's own message; a guess, an address from an email it read, or a name the model turned into an address is refused. A reply goes to the
  Reply-To (or From) of the one message found, and shows that address on the card. At most 5 recipients, never a hidden copy, never an attachment, and the text is plain.
* **The one message is found now**, by the sender, the words and the days the person used (ActionKind.resolve): none, or several, refuses the proposal and says so ("the latest" is the one exception, and the card says which).
* **Everything is shown**: the card carries each recipient and the whole text, and the approval is bound to exactly that. A forward sends the original's text as Gmail has it when it is sent, checked to still have the same subject.
* **A limit**: at most 20 sent a day.
* **Never straight away**, and never retried: a send that may or may not have gone is `unknown` and the person looks in their Sent folder.
* After sending, the message is read back (if the Gmail read card is connected) and must be in Sent, to those addresses, with that subject.

The text of an email is one paragraph: Diya keeps what it asks you to approve as one line.

Importing this module has no side effects except naming what each card may ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import base64
import re
from datetime import datetime, timezone
from email.message import EmailMessage

import diya_connectors
import diya_google_cards
import diya_google_client as client
import diya_google_mail as mail
import diya_intent
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
READ = "google_mail"
DRAFTS, SEND, ORGANISE = "google_mail_drafts", "google_mail_send", "google_mail_organise"
SCOPES = {DRAFTS: "https://www.googleapis.com/auth/gmail.compose", SEND: "https://www.googleapis.com/auth/gmail.send", ORGANISE: "https://www.googleapis.com/auth/gmail.modify"}
CARD_LABELS = {DRAFTS: "Gmail: drafts", SEND: "Gmail: send", ORGANISE: "Gmail: organise"}
ID = r"[A-Za-z0-9_-]{5,64}"
MAX_RECIPIENTS = 5
SUBJECT_MAX = 150
BODY_MAX = 2200  # one line; the approval system keeps the arguments to 4000 characters in all
REFERENCES_MAX = 500
MAX_SENDS_PER_DAY = 20
FORWARD_QUOTE_CHARS = 2000
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_GMAIL = re.escape(GMAIL)

client.allow(READ, "GET", rf"{_GMAIL}/messages")
client.allow(READ, "GET", rf"{_GMAIL}/messages/{ID}")
client.allow(ORGANISE, "GET", rf"{_GMAIL}/messages")
client.allow(ORGANISE, "GET", rf"{_GMAIL}/messages/{ID}")
client.allow(ORGANISE, "GET", rf"{_GMAIL}/labels")
client.allow(ORGANISE, "POST", rf"{_GMAIL}/messages/{ID}/modify")
client.allow(ORGANISE, "POST", rf"{_GMAIL}/messages/{ID}/trash")
client.allow(ORGANISE, "POST", rf"{_GMAIL}/messages/{ID}/untrash")
client.allow(DRAFTS, "GET", rf"{_GMAIL}/drafts")
client.allow(DRAFTS, "GET", rf"{_GMAIL}/drafts/{ID}")
client.allow(DRAFTS, "POST", rf"{_GMAIL}/drafts")
client.allow(DRAFTS, "PUT", rf"{_GMAIL}/drafts/{ID}")
client.allow(DRAFTS, "DELETE", rf"{_GMAIL}/drafts/{ID}")
client.allow(SEND, "POST", rf"{_GMAIL}/messages/send")

VERBS = {
    "archive": "Archive", "read": "Mark as read", "unread": "Mark as unread", "star": "Star", "unstar": "Remove the star from", "label": "Put the label {label} on", "unlabel": "Take the label {label} off",
    "trash": "Move to the bin", "restore": "Bring back from the bin",
}
_SYSTEM_LABELS = frozenset({"inbox", "sent", "draft", "trash", "spam", "unread", "starred", "important", "chat"})  # never put on or taken off by name through "label"


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").casefold()).split())


def addresses_in(text):
    """The email addresses in a piece of text, lowercase, in order, each once."""
    seen = []
    for found in EMAIL.findall(text or ""):
        if found.lower() not in seen:
            seen.append(found.lower())
    return seen


# ---- finding the one message ---------------------------------------------------------------------------------------------------------------------

_WINDOW = {"today": "newer_than:1d", "yesterday": "newer_than:2d", "this week": "newer_than:7d", "last week": "newer_than:14d", "this month": "newer_than:30d"}
_LATEST = re.compile(r"\b(?:latest|last|most\s+recent|newest)\b", re.IGNORECASE)


def _own(value, said):
    """`value` (a name or some words the model gave) if the person said it themselves, cleaned so that it cannot be a Gmail search operator; else ''."""
    if not isinstance(value, str) or not value.strip() or not diya_intent.said_in(value, said):
        return ""
    return " ".join(re.sub(r"[^\w@.' -]", " ", value).split())[:60]


def search_for(said, sender=None, about=None, extra=""):
    """(the Gmail search, and how to describe it) for the ONE message a request is about, built by code from the person's own words: the sender and the words the model gave are used only if the person said them, and
    the days come from what they said. InvalidArgs, saying what to ask, when they named neither a sender nor words."""
    who, topic = _own(sender, said), _own(about, said)
    if not who and not topic:
        raise InvalidArgs("say which email: whose it is, or what it was about, in the user's own words; I do not choose one")
    parts = []
    if who:
        parts.append(f'from:"{who}"')
    if topic:
        parts.append(f"({topic})")
    lowered = said.lower()
    for words, query in _WINDOW.items():
        if words in lowered:
            parts.append(query)
            break
    else:
        parts.append("newer_than:60d")
    if extra:
        parts.append(extra)
    described = " and ".join(filter(None, [f"from {who}" if who else "", f"about {topic}" if topic else ""]))
    return " ".join(parts), described


def _header(meta, name):
    for item in (meta.get("payload") or {}).get("headers") or []:
        if isinstance(item, dict) and str(item.get("name", "")).lower() == name.lower():
            return str(item.get("value") or "")
    return ""


def _metadata(config, reader, message_id, full=False):
    params = {"format": "full"} if full else {"format": "metadata", "metadataHeaders": ["From", "To", "Cc", "Subject", "Date", "Message-ID", "Reply-To", "References"]}
    return client.read(config, reader, "Gmail", f"{GMAIL}/messages/{message_id}", params)


def _tidy_ids(value, limit):
    """Message ids from a header, on one line, the last ones that fit in `limit` characters."""
    kept, used = [], 0
    for token in reversed(" ".join(str(value or "").split()).split()):
        if used + len(token) + 1 > limit:
            break
        kept.append(token)
        used += len(token) + 1
    return " ".join(reversed(kept))


def _summary_of(meta):
    return {
        "id": meta.get("id"), "threadId": meta.get("threadId"), "labels": [str(x) for x in (meta.get("labelIds") or [])], "from": mail._clean(_header(meta, "From"), 100), "to": mail._clean(_header(meta, "To"), 150),
        "reply_to": _header(meta, "Reply-To") or _header(meta, "From"), "subject": mail._clean(_header(meta, "Subject") or "(no subject)", SUBJECT_MAX), "date": mail._clean(_header(meta, "Date"), 40),
        "message_id": _tidy_ids(_header(meta, "Message-ID"), 200), "references": _tidy_ids(_header(meta, "References"), REFERENCES_MAX),
    }


def _shown(message):
    return f"{message['from'][:60]}: {message['subject'][:70]} ({message['date'][:16]})"


def find_one_message(config, said, reader, sender=None, about=None, extra=""):
    """The one message the person's words point at, as a summary dict (a read); InvalidArgs, with words, for none or several."""
    query, described = search_for(said, sender, about, extra)
    try:
        listed = client.read(config, reader, "Gmail", f"{GMAIL}/messages", {"q": query, "maxResults": 8})
        ids = [m["id"] for m in (listed.get("messages") or []) if isinstance(m, dict) and isinstance(m.get("id"), str) and re.fullmatch(ID, m["id"])]
        found = [_summary_of(_metadata(config, reader, message_id)) for message_id in ids[:8]]
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    if not found:
        raise InvalidArgs(f"no email matched {described} (the last days were searched; Gmail finds words, not meanings); ask the user for the sender or the subject")
    if len(found) > 1 and not _LATEST.search(said):
        listed_text = "; ".join(f"{m['from'][:40]}, '{m['subject'][:50]}', {m['date'][:16]}" for m in found[:5])
        raise InvalidArgs(f"{len(found)} emails match {described}: {listed_text}. Ask the user which one, by its subject or date, and do not choose")
    return found[0]  # Gmail lists the newest first


# ---- who it may go to, and how it is built --------------------------------------------------------------------------------------------------------

def _split(value):
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def own_recipients(wanted, said, what="the recipient"):
    """The addresses among `wanted` (one text, separated by commas) that the person typed in their message, as one text; InvalidArgs, saying what to ask, for any that they did not type. Nothing else ever becomes a recipient."""
    typed = addresses_in(said)
    chosen = []
    for item in _split(wanted):
        address = item.lower()
        if not EMAIL.fullmatch(address):
            raise InvalidArgs(f"{what} must be an email address the user typed; ask them for it ({diya_memory.printable(item, 60)!r} is not one)")
        if address not in typed:
            raise InvalidArgs(f"{address} is not an address the user typed in their message, so it is not used; ask them for the address, and use exactly what they type")
        if address not in chosen:
            chosen.append(address)
    if not chosen:
        raise InvalidArgs(f"{what} must be an email address the user typed; ask them for it")
    return ", ".join(chosen)


def _addresses(value, what, *, required=True):
    found = _split(value)
    if not found:
        if required:
            raise InvalidArgs(f"{what} needs an email address")
        return []
    if len(found) > MAX_RECIPIENTS or any(not EMAIL.fullmatch(a) for a in found) or len({a.lower() for a in found}) != len(found):
        raise InvalidArgs(f"{what} is one to {MAX_RECIPIENTS} email addresses, separated by commas")
    return found


def build_raw(to, cc, subject, body, *, in_reply_to="", references=""):
    """The email as Gmail wants it (an RFC 2822 message, base64url). A line break in a header is impossible: the library refuses it."""
    message = EmailMessage()
    if to:
        message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = (references + " " + in_reply_to).strip()
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _line(value, what, limit, *, required=True):
    if value is None and not required:
        return
    if not isinstance(value, str) or not value.strip():
        raise InvalidArgs(f"{what} needs words")
    if len(value) > limit or diya_memory.printable(value) != value:
        raise InvalidArgs(f"{what} is one plain line of at most {limit} characters")


def _unknown(args, allowed, what):
    extra = sorted(set(args) - allowed)
    if extra:
        raise InvalidArgs(f"{what} has no {', '.join(extra)}")


def _id_ok(args, key, what):
    if key in args and (not isinstance(args[key], str) or not re.fullmatch(ID, args[key])):
        raise InvalidArgs(f"{what} is found by its words; it cannot be given an id")


# ---- the daily limit on sending -------------------------------------------------------------------------------------------------------------------

def _sends_key():
    return "gmail_sends:" + datetime.now(timezone.utc).strftime("%Y-%m-%d")


def sends_today(config):
    try:
        import diya_db

        conn = diya_db.Store(config.db_path).connect()
        try:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (_sends_key(),)).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
    except Exception:  # noqa: BLE001
        return 0


def _count_send(config):
    import diya_db

    conn = diya_db.Store(config.db_path).connect()
    try:
        conn.execute("INSERT INTO app_state (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1", (_sends_key(),))
        conn.commit()
    finally:
        conn.close()


# ---- sending: a new email, a reply, a forward ----------------------------------------------------------------------------------------------------

SEND_KEYS = {"mode", "to", "cc", "subject", "body", "thread_id", "in_reply_to", "references", "replying_to", "message_id", "original_subject"}


def send_validate(args):
    _unknown(args, SEND_KEYS, "an email")
    mode = args.get("mode")
    if mode not in ("new", "reply", "forward"):
        raise InvalidArgs("an email is new, a reply or a forward")
    to = _addresses(args.get("to"), "the recipient")
    cc = _addresses(args.get("cc"), "a copy recipient", required=False)
    if len(to) + len(cc) > MAX_RECIPIENTS or {a.lower() for a in to} & {a.lower() for a in cc}:
        raise InvalidArgs(f"an email goes to at most {MAX_RECIPIENTS} different email addresses")
    _line(args.get("subject"), "the subject", SUBJECT_MAX)
    body = args.get("body")
    if mode == "forward":
        if body is not None and (not isinstance(body, str) or len(body) > BODY_MAX):
            raise InvalidArgs(f"the note is at most {BODY_MAX} characters")
    else:
        _line(body, "the text of the email", BODY_MAX)
    if mode == "new":
        if set(args) & {"thread_id", "in_reply_to", "references", "replying_to", "message_id", "original_subject"}:
            raise InvalidArgs("a new email is not about another email")
        return
    _id_ok(args, "message_id", "the email")
    if not args.get("message_id") or not isinstance(args.get("replying_to"), str) or not args["replying_to"].strip() or len(args["replying_to"]) > 300:
        raise InvalidArgs("a reply or a forward is about one email, found by its words")
    if mode == "reply":
        _id_ok(args, "thread_id", "the conversation")
        if len(to) != 1 or cc:
            raise InvalidArgs("a reply goes to the one person who wrote")
        for key in ("in_reply_to", "references"):
            if key in args and (not isinstance(args[key], str) or len(args[key]) > REFERENCES_MAX or diya_memory.printable(args[key]) != args[key]):
                raise InvalidArgs(f"{key} is not usable")
    else:
        if cc or set(args) & {"thread_id", "in_reply_to", "references"}:
            raise InvalidArgs("a forward has a recipient and an optional note, and nothing else")
        _line(args.get("original_subject"), "the original's subject", SUBJECT_MAX)


def send_render(args):
    to = diya_memory.printable(args["to"], 100)
    subject = diya_memory.printable(args["subject"], 70)
    if args["mode"] == "new":
        copy = f" (copy to {diya_memory.printable(args['cc'], 60)})" if args.get("cc") else ""
        return f"Send an email to {to}{copy}: '{subject}'"
    about = diya_memory.printable(args["replying_to"], 90 if args["mode"] == "reply" else 110)
    if args["mode"] == "reply":
        return f"Reply to {about} by email to {to}: '{subject}'"
    return f"Forward {about} to {to}, text only without attachments"


def _forward_body(config, args):
    """The text of a forward: the person's note, then the original as Gmail has it now (read again; nothing is sent if its subject is no longer what was proposed)."""
    try:
        full = _metadata(config, READ, args["message_id"], full=True)
    except client.GoogleError as exc:
        raise ActionFailed(f"The email to forward could not be read ({exc}), so nothing was sent.")
    summary = _summary_of(full)
    if summary["subject"] != args["original_subject"]:
        raise ActionFailed("That email is not what it was when the forward was proposed, so nothing was sent.")
    original = mail._clean(mail._text_of(full.get("payload") or {}), FORWARD_QUOTE_CHARS)
    note = (args.get("body") or "").strip()
    quoted = f"---------- Forwarded message ----------\nFrom: {summary['from']}\nDate: {summary['date']}\nSubject: {summary['subject']}\nTo: {summary['to']}\n\n{original}\n\n(Text only: attachments are not included.)"
    return (note + "\n\n" if note else "") + quoted


def send_execute(config, args):
    if sends_today(config) >= MAX_SENDS_PER_DAY:
        raise ActionFailed(f"{MAX_SENDS_PER_DAY} emails have been sent today, which is as many as Diya will send in a day, so nothing was sent. It can be proposed again tomorrow.")
    to, cc = _split(args["to"]), _split(args.get("cc"))
    body = _forward_body(config, args) if args["mode"] == "forward" else args["body"]
    payload = {"raw": build_raw(to, cc, args["subject"], body, in_reply_to=args.get("in_reply_to", ""), references=args.get("references", ""))}
    if args["mode"] == "reply" and args.get("thread_id"):
        payload["threadId"] = args["thread_id"]
    try:
        response = client.send(config, SEND, CARD_LABELS[SEND], "POST", f"{GMAIL}/messages/send", body=payload, doing="sending the email")
    except ActionUncertain:
        _count_send(config)  # it may have gone, so it counts
        raise
    _count_send(config)
    data = client.as_json(response)
    sent_id = data.get("id")
    if not isinstance(sent_id, str) or not re.fullmatch(ID, sent_id):
        raise ActionUncertain("Google said the email was sent but gave no usable id to check it by, so it is not confirmed. Look in your Sent folder in Gmail, then record what you found.")
    if data.get("labelIds") is not None and "SENT" not in data["labelIds"]:
        raise ActionUncertain("Google said the email was sent, but it is not marked as sent, so it is not confirmed. Look in your Sent folder in Gmail, then record what you found.")
    where = ", ".join(to + cc)
    if diya_connectors.read_token(config, READ) is None:
        return f"Sent to {where}: '{args['subject']}'. Gmail confirmed it (message {sent_id}); it was not read back because the Gmail read card is not connected."
    try:
        meta = _metadata(config, READ, sent_id)
    except client.GoogleError:
        raise ActionUncertain("Google said the email was sent, but reading it back to check did not work, so it is not confirmed. Look in your Sent folder in Gmail, then record what you found.")
    sent_to = sorted(addresses_in(_header(meta, "To") + " " + _header(meta, "Cc")))
    if "SENT" not in (meta.get("labelIds") or []) or sent_to != sorted(a.lower() for a in to + cc) or _header(meta, "Subject") != args["subject"]:
        raise ActionUncertain("Google said the email was sent, but reading it back showed something different (the folder, the recipients or the subject), so it is not confirmed. Look in your Sent folder in Gmail, then record what you found.")
    return f"Sent to {where} and read back from your Sent folder: '{args['subject']}'."


def new_prepare(args, text):
    """A new email goes only to addresses the person typed; nothing about another email is taken from the model."""
    kept = {k: v for k, v in args.items() if k in ("to", "cc", "subject", "body")}
    kept["to"] = own_recipients(kept.get("to"), text)
    if kept.get("cc"):
        copies = [a for a in _split(own_recipients(kept["cc"], text, "a copy recipient")) if a not in _split(kept["to"])]
        if copies:
            kept["cc"] = ", ".join(copies)
        else:
            kept.pop("cc")
    kept["mode"] = "new"
    return kept, []


def reply_resolve(config, args, said):
    message = find_one_message(config, said, READ, args.get("sender"), args.get("about"))
    reply_to = addresses_in(message["reply_to"])
    if not reply_to:
        raise InvalidArgs("that email has no address to reply to")
    subject = message["subject"] if message["subject"].lower().startswith("re:") else f"Re: {message['subject']}"
    resolved = {"mode": "reply", "to": reply_to[0], "subject": subject[:SUBJECT_MAX], "body": args.get("body"), "thread_id": message["threadId"], "replying_to": _shown(message), "message_id": message["id"]}
    if message["message_id"]:
        resolved["in_reply_to"] = message["message_id"]
        if message["references"]:
            resolved["references"] = message["references"]
    return {k: v for k, v in resolved.items() if v}


def forward_resolve(config, args, said):
    message = find_one_message(config, said, READ, args.get("sender"), args.get("about"))
    subject = message["subject"] if message["subject"].lower().startswith("fwd:") else f"Fwd: {message['subject']}"
    resolved = {"mode": "forward", "to": own_recipients(args.get("to"), said, "the person to forward it to"), "subject": subject[:SUBJECT_MAX], "replying_to": _shown(message), "message_id": message["id"],
                "original_subject": message["subject"]}
    if isinstance(args.get("body"), str) and args["body"].strip():
        resolved["body"] = args["body"]
    return resolved


# ---- drafts ---------------------------------------------------------------------------------------------------------------------------------------

DRAFT_KEYS = {"to", "cc", "subject", "body", "replaces", "replaces_id"}


def draft_validate(args):
    _unknown(args, DRAFT_KEYS, "a draft")
    to, cc = _addresses(args.get("to"), "the recipient", required=False), _addresses(args.get("cc"), "a copy recipient", required=False)
    if len(to) + len(cc) > MAX_RECIPIENTS:
        raise InvalidArgs(f"a draft goes to at most {MAX_RECIPIENTS} email addresses, or to none yet")
    _line(args.get("subject"), "the subject", SUBJECT_MAX)
    _line(args.get("body"), "the text of the draft", BODY_MAX)
    _id_ok(args, "replaces_id", "the draft it replaces")
    if ("replaces" in args) != ("replaces_id" in args):
        raise InvalidArgs("replacing a draft needs the draft found by its subject")


def draft_render(args):
    to = f" to {diya_memory.printable(args['to'], 100)}" if args.get("to") else " with no recipient yet"
    subject = diya_memory.printable(args["subject"], 70)
    if args.get("replaces_id"):
        return f"Replace the draft '{diya_memory.printable(args['replaces'], 70)}'{to}: now '{subject}' (a draft is not sent)"
    return f"Save a draft email{to}: '{subject}' (a draft is not sent)"


def draft_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("to", "cc", "subject", "body", "replaces")}
    if kept.get("to"):
        kept["to"] = own_recipients(kept["to"], text)
    else:
        kept.pop("to", None)
    if kept.get("cc"):
        copies = [a for a in _split(own_recipients(kept["cc"], text, "a copy recipient")) if a not in _split(kept.get("to"))]
        if copies:
            kept["cc"] = ", ".join(copies)
        else:
            kept.pop("cc")
    return kept, []


def _drafts(config):
    """The person's drafts as (id, subject, to) triples, a few, newest first: read with the drafts card only (it can list and read drafts, not mail)."""
    listed = client.read(config, DRAFTS, CARD_LABELS[DRAFTS], f"{GMAIL}/drafts", {"maxResults": 20})
    found = []
    for item in (listed.get("drafts") or [])[:20]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(ID, item["id"]):
            continue
        meta = client.read(config, DRAFTS, CARD_LABELS[DRAFTS], f"{GMAIL}/drafts/{item['id']}", {"format": "metadata"}).get("message") or {}
        found.append((item["id"], mail._clean(_header(meta, "Subject") or "(no subject)", SUBJECT_MAX), mail._clean(_header(meta, "To"), 100)))
    return found


def _find_draft(config, subject):
    if not isinstance(subject, str) or not subject.strip():
        raise InvalidArgs("say which draft, by its subject")
    try:
        drafts = _drafts(config)
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    wanted = _norm(subject)
    matches = [d for d in drafts if _norm(d[1]) == wanted] or [d for d in drafts if wanted and wanted in _norm(d[1])]
    if not matches:
        raise InvalidArgs(f"there is no draft called {diya_memory.printable(subject, 60)!r}; ask the user which draft")
    if len(matches) > 1:
        raise InvalidArgs(f"{len(matches)} drafts match {diya_memory.printable(subject, 60)!r}; ask the user which one, by its recipient, and do not choose")
    return matches[0]


def draft_resolve(config, args, said):
    kept = {k: v for k, v in args.items() if k not in ("replaces", "replaces_id")}
    replaces = args.get("replaces")
    if isinstance(replaces, str) and replaces.strip() and diya_intent.said_in(replaces, said):
        draft_id, subject, _to = _find_draft(config, replaces)
        kept["replaces_id"], kept["replaces"] = draft_id, subject
    return kept


def draft_execute(config, args):
    raw = build_raw(_split(args.get("to")), _split(args.get("cc")), args["subject"], args["body"])
    if args.get("replaces_id"):
        response = client.send(config, DRAFTS, CARD_LABELS[DRAFTS], "PUT", f"{GMAIL}/drafts/{args['replaces_id']}", body={"id": args["replaces_id"], "message": {"raw": raw}}, doing="replacing the draft")
    else:
        response = client.send(config, DRAFTS, CARD_LABELS[DRAFTS], "POST", f"{GMAIL}/drafts", body={"message": {"raw": raw}}, ok=(200, 201), doing="saving the draft")
    draft_id = client.as_json(response).get("id")
    if not isinstance(draft_id, str) or not re.fullmatch(ID, draft_id):
        raise ActionUncertain("Google said the draft was saved but gave no usable id to check it by, so it is not confirmed. Look in your Drafts folder in Gmail, then record what you found.")
    try:
        meta = client.read(config, DRAFTS, CARD_LABELS[DRAFTS], f"{GMAIL}/drafts/{draft_id}", {"format": "metadata"}).get("message") or {}
    except client.GoogleError:
        raise ActionUncertain("Google said the draft was saved, but reading it back to check did not work, so it is not confirmed. Look in your Drafts folder in Gmail, then record what you found.")
    if _header(meta, "Subject") != args["subject"]:
        raise ActionUncertain("Google said the draft was saved, but reading it back showed a different subject, so it is not confirmed. Look in your Drafts folder in Gmail, then record what you found.")
    return f"{'Replaced' if args.get('replaces_id') else 'Saved'} the draft and read it back to check: '{args['subject']}'. It is in your Drafts folder; it has not been sent."


def discard_validate(args):
    _unknown(args, {"subject", "draft_id", "to_shown"}, "throwing away a draft")
    _line(args.get("subject"), "the draft's subject", SUBJECT_MAX)
    _line(args.get("to_shown"), "who the draft is to", 100, required=False)
    if not isinstance(args.get("draft_id"), str) or not re.fullmatch(ID, args["draft_id"]):
        raise InvalidArgs("a draft is found by its subject; it cannot be given an id")


def discard_resolve(config, args, said):
    draft_id, subject, to = _find_draft(config, args.get("subject"))
    return {"subject": subject, "draft_id": draft_id, "to_shown": to or "no recipient yet"}


def discard_render(args):
    return f"Throw away the draft '{diya_memory.printable(args['subject'], 80)}' (to {diya_memory.printable(args.get('to_shown') or 'no recipient yet', 80)}); Diya cannot bring it back"


def discard_execute(config, args):
    try:
        meta = client.read(config, DRAFTS, CARD_LABELS[DRAFTS], f"{GMAIL}/drafts/{args['draft_id']}", {"format": "metadata"}).get("message") or {}
    except client.GoogleError as exc:
        raise ActionFailed(f"That draft is not in your Drafts any more ({exc}), so nothing was done.")
    if mail._clean(_header(meta, "Subject") or "(no subject)", SUBJECT_MAX) != args["subject"]:
        raise ActionFailed("That draft was changed after this was proposed, so nothing was done. Look at it in Gmail and ask again if you still want it thrown away.")
    client.send(config, DRAFTS, CARD_LABELS[DRAFTS], "DELETE", f"{GMAIL}/drafts/{args['draft_id']}", ok=(200, 204), doing="throwing the draft away")
    try:
        client.read(config, DRAFTS, CARD_LABELS[DRAFTS], f"{GMAIL}/drafts/{args['draft_id']}", {"format": "metadata"})
    except client.GoogleError as exc:
        if exc.kind == "not_found":
            return f"Threw away the draft '{args['subject']}'. Google no longer has it."
        raise ActionUncertain("Google said the draft was thrown away, but reading to check did not work, so it is not confirmed. Look in your Drafts folder in Gmail, then record what you found.")
    raise ActionUncertain("Google said the draft was thrown away, but it is still there, so it is not confirmed. Look in your Drafts folder in Gmail, then record what you found.")


# ---- filing mail -----------------------------------------------------------------------------------------------------------------------------------

def _user_label(config, name, said):
    """(id, name) of the person's own label called `name` (it must be in their words and already exist: Diya never makes labels); InvalidArgs otherwise."""
    if not isinstance(name, str) or not name.strip() or not diya_intent.said_in(name, said):
        raise InvalidArgs("say which label, in the user's own words; I do not choose one")
    try:
        data = client.read(config, ORGANISE, CARD_LABELS[ORGANISE], f"{GMAIL}/labels")
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    users = [x for x in (data.get("labels") or []) if isinstance(x, dict) and x.get("type") == "user" and isinstance(x.get("id"), str) and re.fullmatch(ID, x["id"])]
    wanted = _norm(name)
    found = [x for x in users if _norm(x.get("name")) == wanted]
    if wanted in _SYSTEM_LABELS or len(found) != 1:
        names = ", ".join(diya_memory.printable(x.get("name"), 30) for x in users)[:200]
        raise InvalidArgs(f"there is no label of yours called {diya_memory.printable(name, 40)!r} (Diya does not make labels). Your labels: {names or 'none'}")
    return found[0]["id"], diya_memory.printable(found[0].get("name"), 40)


ORGANISE_KEYS = {"action", "message_id", "shown", "label", "label_id"}


def organise_validate(args):
    _unknown(args, ORGANISE_KEYS, "filing mail")
    if args.get("action") not in VERBS:
        raise InvalidArgs(f"filing mail is one of: {', '.join(VERBS)}")
    _id_ok(args, "message_id", "an email")
    if not args.get("message_id"):
        raise InvalidArgs("an email is found by its words")
    _line(args.get("shown"), "the email's description", 300)
    if args["action"] in ("label", "unlabel"):
        _line(args.get("label"), "the label", 40)
        if not isinstance(args.get("label_id"), str) or not re.fullmatch(ID, args["label_id"]):
            raise InvalidArgs("a label is found by its name; it cannot be given an id")
    elif "label" in args or "label_id" in args:
        raise InvalidArgs(f"{args['action']} has no label")


def organise_resolve(config, args, said):
    action = args.get("action")
    if action not in VERBS:
        raise InvalidArgs(f"filing mail is one of: {', '.join(VERBS)}")
    message = find_one_message(config, said, ORGANISE, args.get("sender"), args.get("about"), extra="in:trash" if action == "restore" else "")
    resolved = {"action": action, "message_id": message["id"], "shown": _shown(message)}
    if action in ("label", "unlabel"):
        resolved["label_id"], resolved["label"] = _user_label(config, args.get("label"), said)
    return resolved


def organise_render(args):
    verb = VERBS[args["action"]].format(label=diya_memory.printable(args.get("label"), 40))
    return f"{verb} the email {diya_memory.printable(args['shown'], 170)}"


def _labels_changed(args):
    """(labels to add, labels to remove) for the action."""
    table = {
        "archive": ([], ["INBOX"]), "read": ([], ["UNREAD"]), "unread": (["UNREAD"], []), "star": (["STARRED"], []), "unstar": ([], ["STARRED"]),
        "label": ([args.get("label_id")], []), "unlabel": ([], [args.get("label_id")]),
    }
    return table[args["action"]]


def organise_execute(config, args):
    try:
        current = _metadata(config, ORGANISE, args["message_id"])
    except client.GoogleError as exc:
        raise ActionFailed(f"That email could not be read ({exc}), so nothing was done.")
    if _shown(_summary_of(current)) != args["shown"]:
        raise ActionFailed("That is not the email that was proposed, so nothing was done.")
    action = args["action"]
    in_bin = "TRASH" in (current.get("labelIds") or [])
    if action == "restore" and not in_bin:
        raise ActionFailed("That email is not in the bin any more, so nothing was done.")
    if action != "restore" and in_bin:
        raise ActionFailed("That email is in the bin, so nothing was done.")
    if action == "trash":
        client.send(config, ORGANISE, CARD_LABELS[ORGANISE], "POST", f"{GMAIL}/messages/{args['message_id']}/trash", doing="moving the email to the bin")
    elif action == "restore":
        client.send(config, ORGANISE, CARD_LABELS[ORGANISE], "POST", f"{GMAIL}/messages/{args['message_id']}/untrash", doing="bringing the email back")
    else:
        add, remove = _labels_changed(args)
        client.send(config, ORGANISE, CARD_LABELS[ORGANISE], "POST", f"{GMAIL}/messages/{args['message_id']}/modify", body={"addLabelIds": add, "removeLabelIds": remove}, doing="filing the email")
    try:
        labels = set(_metadata(config, ORGANISE, args["message_id"]).get("labelIds") or [])
    except client.GoogleError:
        raise ActionUncertain("Google said it was done, but reading the email back to check did not work, so it is not confirmed. Look in Gmail, then record what you found.")
    if action == "trash":
        done = "TRASH" in labels
    elif action == "restore":
        done = "TRASH" not in labels
    else:
        add, remove = _labels_changed(args)
        done = all(a in labels for a in add) and not any(r in labels for r in remove)
    if not done:
        raise ActionUncertain("Google said it was done, but reading the email back showed it was not, so it is not confirmed. Look in Gmail, then record what you found.")
    return f"Done and read back to check: {organise_render(args)}."


# ---- what to say to a request to write mail ------------------------------------------------------------------------------------------------------

_BULK = re.compile(r"\b(?:all|every|each|any)\s+(?:of\s+)?(?:(?:my|the|your)\s+)?(?:\w+\s+){0,2}?(?:e-?mails?|mails?|messages?|drafts?)\b|\b(?:my|the)\s+(?:whole\s+)?inbox\b|\bbulk\b", re.IGNORECASE)


def write_request(config, text):
    """What to do with a message that asks to send, write or file mail: ("ok", None) when the card for it is connected (the model may propose it, and the person approves); ("connect", the sentence) when it is not;
    ("bulk", the sentence) for filing many at once, which Diya never does; ("unknown", None) when it is not one of these kinds."""
    if asks.drafts_mail(text) or asks.discards_draft(text):
        needs = DRAFTS
    elif asks.forwards_mail(text) or asks.replies_to_mail(text) or asks.sends_mail(text):
        needs = SEND
    elif asks.organises_mail(text):
        needs = ORGANISE
    else:
        return "unknown", None
    if needs != SEND and _BULK.search(text or ""):  # the words of an email that is being sent may say "all"; filing or throwing away many at once is what is refused
        return "bulk", "I send and file one email at a time, and I ask you before each one. I do not change many emails at once."
    if not diya_connectors.is_connected(config, needs):
        return "connect", f"I can only do that once you connect '{CARD_LABELS[needs]}' on the Connections page. I would still ask you before anything is sent or changed."
    return "ok", None


# ---- the kinds, their tools and the cards ---------------------------------------------------------------------------------------------------------

def _kind(name, label, connector, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=connector, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is done until the user approves it on the Actions page.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


TO = {"type": "string", "description": "The email address, exactly as the user typed it in their message (several: separated by commas). Never guess or look one up."}
SUBJECT = {"type": "string", "description": "The subject, in a few words."}
BODY = {"type": "string", "description": "The text of the email, plain, in one paragraph, in the user's voice, short. It is shown to the user in full before they approve."}
FIND = {"sender": {"type": "string", "description": "Whose email it is, exactly as the user said it."}, "about": {"type": "string", "description": "Optional. Words from what it was about, exactly as the user said them."}}


def send_kind():
    return _kind("gmail_send", "Send an email", SEND, "propose_send_gmail", "Propose sending a NEW email to an address the user typed in their message. Use it only when the user asks you to send or write an email to that address.",
                 {"to": TO, "cc": TO, "subject": SUBJECT, "body": BODY}, ["to", "subject", "body"], validate=send_validate, render=send_render, execute=send_execute, asked=asks.sends_mail, prepare=new_prepare)


def reply_kind():
    return _kind("gmail_reply", "Reply to an email", SEND, "propose_reply_gmail", "Propose replying to one email the user names (whose it is, or what it was about). The reply goes to the person who wrote it. Use it only when the user asks you to reply.",
                 {**FIND, "body": BODY}, ["body"], validate=send_validate, render=send_render, execute=send_execute, asked=asks.replies_to_mail, resolve=reply_resolve)


def forward_kind():
    return _kind("gmail_forward", "Forward an email", SEND, "propose_forward_gmail", "Propose forwarding one email the user names to an address the user typed. Use it only when the user asks you to forward it.",
                 {**FIND, "to": TO, "body": {"type": "string", "description": "Optional. A line to put above the forwarded email."}}, ["to"], validate=send_validate, render=send_render, execute=send_execute, asked=asks.forwards_mail,
                 resolve=forward_resolve)


def draft_kind():
    return _kind("gmail_draft", "Save an email draft", DRAFTS, "propose_gmail_draft", "Propose saving a DRAFT email (it is not sent). The recipient is optional, and only an address the user typed. Use it only when the user asks you to draft an email.",
                 {"to": TO, "cc": TO, "subject": SUBJECT, "body": BODY, "replaces": {"type": "string", "description": "Optional. The subject of an existing draft to replace, as the user said it."}}, ["subject", "body"],
                 validate=draft_validate, render=draft_render, execute=draft_execute, asked=asks.drafts_mail, prepare=draft_prepare, resolve=draft_resolve)


def discard_kind():
    return _kind("gmail_draft_discard", "Throw away an email draft", DRAFTS, "propose_discard_gmail_draft", "Propose throwing away one draft email, found by its subject. Diya cannot bring it back. Use it only when the user asks for that.",
                 {"subject": SUBJECT}, ["subject"], validate=discard_validate, render=discard_render, execute=discard_execute, asked=asks.discards_draft, resolve=discard_resolve)


def organise_kind():
    return _kind("gmail_organise", "File an email", ORGANISE, "propose_organise_gmail",
                 "Propose filing one email the user names: archive it, mark it read or unread, star or unstar it, put one of their own labels on it or take it off, move it to the bin, or bring it back. Use it only when the user asks for that.",
                 {"action": {"type": "string", "enum": list(VERBS), "description": "What to do."}, **FIND, "label": {"type": "string", "description": "Only for label or unlabel: the name of one of their own labels, as they said it."}}, ["action"],
                 validate=organise_validate, render=organise_render, execute=organise_execute, asked=asks.organises_mail, resolve=organise_resolve)


def action_kinds():
    return (draft_kind(), discard_kind(), send_kind(), reply_kind(), forward_kind(), organise_kind())


def connectors():
    return (
        diya_google_cards.card(DRAFTS, CARD_LABELS[DRAFTS], "Save and replace email drafts, and throw one away, when you approve it. It never sends.", SCOPES[DRAFTS], "Gmail API",
                               ("Saves or replaces a draft email in your Drafts folder, only when you approve that draft.", "Throws a draft away, only when you approve that, and Diya cannot bring it back.",
                                "Cannot send anything: Diya gives this card no request that sends (sending is the separate 'Gmail: send' card).")),
        diya_google_cards.card(SEND, CARD_LABELS[SEND], "Send, reply to or forward an email when you approve it, to an address you typed.", SCOPES[SEND], "Gmail API",
                               ("Sends one email, a reply or a forward, only when you approve exactly that email, to the addresses you typed (a reply goes to the person who wrote).",
                                "Sends at most 20 a day, never with a hidden copy or an attachment. A reply or a forward finds the email through the 'Gmail' read card, which must be connected too.",
                                "Cannot read your mail itself, and never sends anything you did not approve.")),
        diya_google_cards.card(ORGANISE, CARD_LABELS[ORGANISE], "Archive, mark read or unread, star, label and bin an email when you approve it.", SCOPES[ORGANISE], "Gmail API",
                               ("Files one email you name: archive, read or unread, star, one of your own labels, the bin and back, only when you approve it.", "Reads which email you mean, and what it looks like afterwards.",
                                "Cannot delete anything for good, send mail, or make labels.")),
    )
