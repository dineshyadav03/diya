"""Gmail beyond reading: drafts, sending, replying, forwarding and filing mail, each only when approved (diya_google_mailwrite.py; DIYA-075, -076, -077, -078, -113; docs/GOOGLE_CHANGES.md), added 2026-10-26.

No test here reaches the real Google: a stateful stand-in Gmail answers, keeps every request, and applies what it is sent (it really builds the sent message from the raw email it receives). What this proves: each card's
list of allowed requests (the drafts card cannot send, the send card can only send, the organise card cannot delete for good); each kind is proposed only when the message asks for that thing in those words; an email
goes only to an address the person typed (a name, a guess or an address from somewhere else is refused, and nothing is recorded); a reply goes to the one message found NOW from the person's words (none, several, or a
sender they did not say refuses it, and "the latest" picks the newest); a forward reads the original again when it is sent and sends nothing if it changed; sending is counted, limited to 20 a day, never retried, read
back from Sent, and an outcome that is not known is said to be not known; a draft is saved, replaced and thrown away only as proposed; filing changes exactly the labels it says and is read back; and a request to write
mail with the card for it not connected says which card to connect.
"""
import base64
import dataclasses
import email
import json
import re
import types
from email import policy

import pytest

import diya
import diya_actions
import diya_autoapprove
import diya_catalog
import diya_config
import diya_connectors
import diya_db
import diya_intent
import diya_google_calendar as gcal
import diya_google_cards
import diya_google_client as client
import diya_google_mailwrite as mw
import diya_intent_google as asks
from fakes import FakeClient, text_reply, tool_reply

GMAIL = mw.GMAIL
CARDS = (mw.READ, mw.DRAFTS, mw.SEND, mw.ORGANISE)


def resp(status=200, body=None):
    return types.SimpleNamespace(status_code=status, headers={}, json=lambda: body if body is not None else {})


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def message(mid, sender, subject, body="Hello.", labels=("INBOX",), reply_to=None, date="Mon, 26 Oct 2026 09:00:00 +0000", references=None):
    headers = [{"name": "From", "value": sender}, {"name": "To", "value": "me@example.com"}, {"name": "Subject", "value": subject}, {"name": "Date", "value": date}, {"name": "Message-ID", "value": f"<{mid}@mail.example.com>"}]
    if reply_to:
        headers.append({"name": "Reply-To", "value": reply_to})
    if references:
        headers.append({"name": "References", "value": references})
    return {"id": mid, "threadId": f"thread{mid}", "labelIds": list(labels), "payload": {"mimeType": "text/plain", "headers": headers, "body": {"data": b64(body)}}}


def decode_raw(raw):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=policy.default)


class Gmail:
    """A stand-in Gmail: messages with labels (newest last), drafts, the person's labels, and the requests Diya makes. It builds a sent message from the raw email it is sent."""

    def __init__(self):
        self.messages, self.order, self.drafts, self.requests = {}, [], {}, []
        self.labels = [{"id": "INBOX", "name": "INBOX", "type": "system"}, {"id": "Label_1", "name": "Exams", "type": "user"}, {"id": "Label_2", "name": "Receipts", "type": "user"}]
        self.send_status, self.mark_sent, self.answer_labels, self.counter = None, True, True, 100
        self.add(message("m00001", "Maya Rao <maya@example.com>", "Exam timetable", "The exam is on Friday at ten in Hall B.", reply_to="Maya Rao <maya.rao@example.org>"))
        self.add(message("m00002", "Bank of Example <alerts@bank.example>", "Your statement", "Your balance is 100 rupees. Attachment follows."))
        self.add(message("m00003", "Maya Rao <maya@example.com>", "Lab report", "Please send the lab report.", references="<old1@mail.example.com> <old2@mail.example.com>"))

    def add(self, msg):
        self.messages[msg["id"]] = msg
        self.order.append(msg["id"])

    def new_id(self, prefix="m"):
        self.counter += 1
        return f"{prefix}{self.counter:05d}"

    def search(self, q):
        sender = re.search(r'from:"([^"]*)"', q)
        words = re.search(r"\(([^)]*)\)", q)
        wanted_bin = "in:trash" in q
        found = []
        for mid in reversed(self.order):
            msg = self.messages[mid]
            if ("TRASH" in msg["labelIds"]) != wanted_bin or "DRAFT" in msg["labelIds"]:
                continue
            headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
            if sender and sender.group(1).lower() not in headers["from"].lower():
                continue
            text = (headers["subject"] + " " + base64.urlsafe_b64decode(msg["payload"]["body"]["data"] + "==").decode()).lower()
            if words and not all(w in text for w in words.group(1).lower().split()):
                continue
            found.append({"id": mid, "threadId": msg["threadId"]})
        return resp(200, {"messages": found[:8]})

    @staticmethod
    def view(msg, fmt):
        copy = json.loads(json.dumps(msg))
        if fmt == "metadata":
            copy["payload"].pop("body", None)
        return copy

    def build(self, raw, thread=None, labels=("SENT",)):
        parsed = decode_raw(raw)
        headers = [{"name": "From", "value": "me@example.com"}]
        for name in ("To", "Cc", "Subject", "In-Reply-To", "References"):
            if parsed[name]:
                headers.append({"name": name, "value": str(parsed[name])})
        mid = self.new_id()
        headers.append({"name": "Message-ID", "value": f"<{mid}@mail.example.com>"})
        body = parsed.get_content()
        return {"id": mid, "threadId": thread or f"thread{mid}", "labelIds": list(labels), "payload": {"mimeType": "text/plain", "headers": headers, "body": {"data": b64(body)}}}

    def __call__(self, *args, **kwargs):
        method, url = (args[0], args[1]) if len(args) == 2 else ("GET", args[0])
        params, body = kwargs.get("params") or {}, kwargs.get("json")
        self.requests.append((method, url, dict(params), body))
        parts = url[len(GMAIL):].strip("/").split("/")
        if parts[0] == "labels":
            return resp(200, {"labels": self.labels})
        if parts[0] == "messages":
            if len(parts) == 1:
                return self.search(params.get("q", ""))
            if parts[1] == "send" and method == "POST":
                if self.send_status:
                    return resp(self.send_status, {"error": {"message": "backend error"}})
                msg = self.build(body["raw"], body.get("threadId"), ("SENT",) if self.mark_sent else ("INBOX",))
                self.add(msg)
                return resp(200, {"id": msg["id"], "threadId": msg["threadId"], **({"labelIds": list(msg["labelIds"])} if self.answer_labels else {})})
            msg = self.messages.get(parts[1])
            if msg is None:
                return resp(404, {"error": {"message": "not found"}})
            if method == "GET":
                return resp(200, self.view(msg, params.get("format")))
            action = parts[2]
            if action == "modify":
                msg["labelIds"] = [x for x in msg["labelIds"] if x not in body["removeLabelIds"]] + [x for x in body["addLabelIds"] if x not in msg["labelIds"]]
            elif action == "trash":
                msg["labelIds"] = [x for x in msg["labelIds"] if x != "INBOX"] + ["TRASH"]
            elif action == "untrash":
                msg["labelIds"] = [x for x in msg["labelIds"] if x != "TRASH"] + ["INBOX"]
            return resp(200, msg)
        if parts[0] == "drafts":
            if len(parts) == 1 and method == "GET":
                return resp(200, {"drafts": [{"id": d["id"], "message": {"id": d["message"]["id"]}} for d in self.drafts.values()]})
            if len(parts) == 1 and method == "POST":
                msg = self.build(body["message"]["raw"], labels=("DRAFT",))
                draft = {"id": self.new_id("r-"), "message": msg}
                self.drafts[draft["id"]] = draft
                return resp(200, draft)
            draft = self.drafts.get(parts[1])
            if draft is None:
                return resp(404, {"error": {"message": "not found"}})
            if method == "GET":
                return resp(200, {"id": draft["id"], "message": self.view(draft["message"], "metadata")})
            if method == "PUT":
                draft["message"] = self.build(body["message"]["raw"], labels=("DRAFT",))
                return resp(200, draft)
            if method == "DELETE":
                del self.drafts[parts[1]]
                return resp(204)
        return resp(400)

    def mutations(self):
        return [r for r in self.requests if r[0] in ("POST", "PUT", "DELETE", "PATCH")]

    def sent(self):
        return [self.messages[m] for m in self.order if "SENT" in self.messages[m]["labelIds"]]


def header_of(msg, name):
    return next((h["value"] for h in msg["payload"]["headers"] if h["name"].lower() == name.lower()), "")


@pytest.fixture
def config(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "t.db"), connector_tokens_dir=str(tmp_path / "tok"), connectors_log_path=str(tmp_path / "c.log"),
                                 profile_path=str(tmp_path / "p.txt"), protect_secrets=False, require_token=False, mail=True, lookup=False)
    for name in CARDS:
        diya_connectors.store_token(config, name, "refresh")
    return config


@pytest.fixture
def gmail(monkeypatch):
    service = Gmail()
    monkeypatch.setattr(gcal, "access_token", lambda config, name: "tok" if name in CARDS else None)
    monkeypatch.setattr(client.httpx, "get", service)
    monkeypatch.setattr(client.httpx, "request", service)
    monkeypatch.setattr(client, "_sleep", lambda s: None)
    return service


def agent_for(config, replies=()):
    return diya.Agent(config, client=FakeClient(list(replies)), action_kinds=list(mw.action_kinds()))


def propose(config, message_text, tool, args):
    agent = agent_for(config, [tool_reply(tool, json.dumps(args)), text_reply("ok")])
    agent.ask([{"role": "user", "content": message_text}])
    return agent


def run_approved(agent):
    (action,) = agent.actions.pending()
    agent.actions.approve(action["id"], action["args_hash"], "ui")
    return agent.actions.run(action["id"])


# ---- what each card may ask for -----------------------------------------------------------------------------------------------------------------

def test_each_card_has_one_permission_and_the_drafts_card_cannot_send():
    assert mw.SCOPES == {mw.DRAFTS: "https://www.googleapis.com/auth/gmail.compose", mw.SEND: "https://www.googleapis.com/auth/gmail.send", mw.ORGANISE: "https://www.googleapis.com/auth/gmail.modify"}
    send, draft, organise = f"{GMAIL}/messages/send", f"{GMAIL}/drafts/r-1234567", f"{GMAIL}/messages/m00001"
    assert not client.permitted(mw.DRAFTS, "POST", send) and not client.permitted(mw.DRAFTS, "POST", f"{GMAIL}/drafts/send") and not client.permitted(mw.DRAFTS, "GET", organise)
    assert client.permitted(mw.DRAFTS, "POST", f"{GMAIL}/drafts") and client.permitted(mw.DRAFTS, "PUT", draft) and client.permitted(mw.DRAFTS, "DELETE", draft)


def test_the_send_card_can_only_send_and_the_organise_card_never_deletes_for_good_or_sends():
    for method, url in (("GET", f"{GMAIL}/messages"), ("GET", f"{GMAIL}/messages/m00001"), ("DELETE", f"{GMAIL}/messages/m00001"), ("POST", f"{GMAIL}/messages/batchDelete"), ("POST", f"{GMAIL}/drafts"), ("POST", f"{GMAIL}/messages/m00001/trash")):
        assert not client.permitted(mw.SEND, method, url), (method, url)
    assert client.permitted(mw.SEND, "POST", f"{GMAIL}/messages/send")
    for method, url in (("DELETE", f"{GMAIL}/messages/m00001"), ("POST", f"{GMAIL}/messages/batchDelete"), ("POST", f"{GMAIL}/messages/send"), ("POST", f"{GMAIL}/messages/batchModify"), ("POST", f"{GMAIL}/drafts"),
                        ("DELETE", f"{GMAIL}/labels/Label_1"), ("POST", f"{GMAIL}/labels")):
        assert not client.permitted(mw.ORGANISE, method, url), (method, url)
    for tail in ("modify", "trash", "untrash"):
        assert client.permitted(mw.ORGANISE, "POST", f"{GMAIL}/messages/m00001/{tail}")


def test_the_read_card_can_read_mail_and_do_nothing_else():
    assert client.permitted(mw.READ, "GET", f"{GMAIL}/messages") and client.permitted(mw.READ, "GET", f"{GMAIL}/messages/m00001")
    assert not any(client.permitted(mw.READ, m, f"{GMAIL}/messages/m00001") for m in ("POST", "PUT", "DELETE", "PATCH")) and not client.permitted(mw.READ, "POST", f"{GMAIL}/messages/send")


def test_the_cards_are_real_connectors_with_their_one_permission_and_are_known_to_disconnect(config):
    from diya_connector_tools import real_connectors

    made = {c.name: c for c in real_connectors(config)}
    for name, scope in mw.SCOPES.items():
        assert made[name].scope == scope and made[name].implemented and name in gcal.every_card() and name in diya_google_cards.names()
    assert not any("send" in line.lower() and "never" not in line.lower() and "cannot" not in line.lower() and "only" not in line.lower() and "at most" not in line.lower() for line in made[mw.SEND].access)


# ---- the words that ask ----------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, fn, expected", [
    ("send an email to dad@example.com saying I will be late", asks.sends_mail, True),
    ("email dad@example.com that i will be late", asks.sends_mail, True),
    ("send an email to dad saying I will be late", asks.sends_mail, True),  # a name: Diya turns it into an address only through the contacts
    ("send an email saying I will be late", asks.sends_mail, False),  # no one named
    ("draft an email to dad@example.com about sunday", asks.sends_mail, False),  # a draft is not a send
    ("reply to maya@example.com's email saying yes", asks.sends_mail, False),  # a reply is not a new email
    ("how do i send an email to dad@example.com", asks.sends_mail, False),
    ("don't send an email to dad@example.com", asks.sends_mail, False),
    ("reply to Maya's email saying thanks", asks.replies_to_mail, True),
    ("reply to Maya saying thanks", asks.replies_to_mail, False),  # no mail word: could be any chat
    ("forward the email from the bank to mum@example.com", asks.forwards_mail, True),
    ("forward the email from the bank to mum", asks.forwards_mail, False),
    ("draft an email to dad about sunday", asks.drafts_mail, True),
    ("save a draft email to dad@example.com", asks.drafts_mail, True),
    ("send the draft", asks.drafts_mail, False),
    ("delete the draft about sunday", asks.discards_draft, True),
    ("archive the email from the bank", asks.organises_mail, True),
    ("mark the email from maya as read", asks.organises_mail, True),
    ("put the label Exams on maya's email", asks.organises_mail, True),
    ("move the email from the bank to the bin", asks.organises_mail, True),
    ("bring back the email from the bank", asks.organises_mail, True),
    ("archive it", asks.organises_mail, False),  # no mail word
    ("delete the draft email about sunday", asks.organises_mail, False),  # a draft goes to the drafts card
    ("mark buy milk as done", asks.organises_mail, False),
])
def test_each_kind_is_asked_for_only_in_its_own_words(text, fn, expected):
    assert fn(text) is expected


def test_a_request_to_write_mail_is_told_which_card_to_connect_or_passes_to_the_model(config):
    assert mw.write_request(config, "send an email to dad@example.com saying hi") == ("ok", None)
    diya_connectors.disconnect(config, mw.SEND)
    state, words = mw.write_request(config, "send an email to dad@example.com saying hi")
    assert state == "connect" and "'Gmail: send'" in words and "Connections page" in words and "ask you before" in words
    assert mw.write_request(config, "delete all my emails")[0] == "bulk" and mw.write_request(config, "write my essay")[0] == "unknown"
    assert mw.write_request(config, "archive every email in my inbox")[0] == "bulk"
    assert not diya_intent.wants_mail_written("restore my email password") and diya_intent.wants_mail_written("bring back the email from the bank") and diya_intent.wants_mail_written("star the email from maya")
    diya_connectors.store_token(config, mw.SEND, "refresh")
    assert mw.write_request(config, "send an email to dad@example.com saying all emails are read") == ("ok", None)  # the words of an email may say "all"
    diya_connectors.disconnect(config, mw.ORGANISE)
    assert mw.write_request(config, "archive the email from the bank")[1].count("'Gmail: organise'") == 1


# ---- a new email -----------------------------------------------------------------------------------------------------------------------------------

def test_a_new_email_is_proposed_shown_whole_approved_sent_and_read_back_from_sent(config, gmail):
    agent = propose(config, "send an email to dad@example.com saying I will be late", "propose_send_gmail", {"to": "dad@example.com", "subject": "Running late", "body": "Hi Dad, I will be late tonight. See you soon."})
    (action,) = agent.actions.actions()
    assert action["status"] == "pending" and action["summary"] == "Send an email to dad@example.com: 'Running late'"
    assert action["args"] == {"mode": "new", "to": "dad@example.com", "subject": "Running late", "body": "Hi Dad, I will be late tonight. See you soon."}
    assert gmail.mutations() == []  # proposing sent nothing
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "read back from your Sent folder" in done["result"]
    (sent,) = gmail.sent()
    assert header_of(sent, "To") == "dad@example.com" and header_of(sent, "Subject") == "Running late" and not header_of(sent, "Bcc") and len([r for r in gmail.mutations() if r[1].endswith("/messages/send")]) == 1


def test_an_address_the_person_did_not_type_is_refused_and_nothing_is_recorded(config, gmail):
    for wrong in ("boss@example.com", "Dad", "dad@example.com, boss@example.com"):
        agent = propose(config, "send an email to dad@example.com saying I will be late", "propose_send_gmail", {"to": wrong, "subject": "Late", "body": "I will be late."})
        assert agent.actions.actions() == [], wrong
    assert gmail.mutations() == []


def test_a_copy_goes_only_to_a_typed_address_and_a_hidden_copy_does_not_exist(config, gmail):
    agent = propose(config, "send an email to dad@example.com and cc mum@example.com saying I will be late", "propose_send_gmail",
                    {"to": "dad@example.com", "cc": "mum@example.com", "subject": "Late", "body": "I will be late.", "bcc": "spy@example.com"})
    (dropped,) = agent.actions.actions()
    assert "bcc" not in dropped["args"] and "spy@example.com" not in json.dumps(dropped["args"])  # an argument it does not have is dropped, never sent
    agent = propose(config, "send an email to dad@example.com and cc mum@example.com saying I will be late", "propose_send_gmail", {"to": "dad@example.com", "cc": "mum@example.com", "subject": "Late", "body": "I will be late."})
    (action,) = agent.actions.actions()
    assert action["summary"] == "Send an email to dad@example.com (copy to mum@example.com): 'Late'"
    run_approved(agent)
    (sent,) = gmail.sent()
    assert header_of(sent, "Cc") == "mum@example.com" and not header_of(sent, "Bcc")


def test_a_header_cannot_be_smuggled_in_through_the_subject():
    with pytest.raises(ValueError):
        mw.build_raw(["a@example.com"], [], "Hi\nBcc: evil@example.com", "text")
    assert decode_raw(mw.build_raw(["a@example.com"], [], "Hi", "text"))["Bcc"] is None


def test_no_model_text_reaches_an_address_through_a_reply_or_forward_field(config, gmail):
    assert mw.own_recipients("dad@example.com", "mail dad@example.com") == "dad@example.com"
    with pytest.raises(diya_actions.InvalidArgs, match="not an address the user typed"):
        mw.own_recipients("evil@example.com", "mail dad@example.com")
    with pytest.raises(diya_actions.InvalidArgs, match="must be an email address the user typed"):
        mw.own_recipients("dad", "mail dad@example.com")


def test_the_daily_limit_stops_the_twenty_first_send_and_sends_nothing(config, gmail):
    conn = diya_db.Store(config.db_path).connect()
    conn.execute("INSERT INTO app_state (key, value) VALUES (?, ?)", (mw._sends_key(), str(mw.MAX_SENDS_PER_DAY)))
    conn.commit()
    conn.close()
    agent = propose(config, "send an email to dad@example.com saying hi", "propose_send_gmail", {"to": "dad@example.com", "subject": "Hi", "body": "Hi Dad."})
    done = run_approved(agent)
    assert done["status"] == "failed" and "as many as Diya will send in a day" in done["result"] and gmail.mutations() == []


def test_a_send_that_may_have_gone_is_unknown_counted_and_never_tried_again(config, gmail):
    gmail.send_status = 500
    agent = propose(config, "send an email to dad@example.com saying hi", "propose_send_gmail", {"to": "dad@example.com", "subject": "Hi", "body": "Hi Dad."})
    done = run_approved(agent)
    assert done["status"] == "unknown" and "may or may not have been done" in done["result"] and "Look in Google" in done["result"]
    assert len([r for r in gmail.requests if r[1].endswith("/messages/send")]) == 1 and mw.sends_today(config) == 1
    with pytest.raises(diya_actions.ActionError):
        agent.actions.run(done["id"])  # it is not run a second time


def test_a_send_google_does_not_mark_as_sent_is_not_confirmed(config, gmail):
    gmail.mark_sent = False
    agent = propose(config, "send an email to dad@example.com saying hi", "propose_send_gmail", {"to": "dad@example.com", "subject": "Hi", "body": "Hi Dad."})
    done = run_approved(agent)
    assert done["status"] == "unknown" and "not marked as sent" in done["result"] and mw.sends_today(config) == 1


def test_a_send_that_does_not_read_back_as_sent_is_not_confirmed(config, gmail):
    gmail.mark_sent, gmail.answer_labels = False, False  # the answer says nothing about folders, and the message is read back in the inbox
    agent = propose(config, "send an email to dad@example.com saying hi", "propose_send_gmail", {"to": "dad@example.com", "subject": "Hi", "body": "Hi Dad."})
    done = run_approved(agent)
    assert done["status"] == "unknown" and "reading it back showed something different" in done["result"]


def test_without_the_read_card_a_send_is_confirmed_by_googles_answer_and_says_it_was_not_read_back(config, gmail):
    diya_connectors.disconnect(config, mw.READ)
    agent = propose(config, "send an email to dad@example.com saying hi", "propose_send_gmail", {"to": "dad@example.com", "subject": "Hi", "body": "Hi Dad."})
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "not read back because the Gmail read card is not connected" in done["result"]


# ---- a reply ---------------------------------------------------------------------------------------------------------------------------------------

def test_a_reply_is_found_now_from_the_persons_words_and_goes_to_the_reply_to_address(config, gmail):
    agent = propose(config, "reply to Maya's email about the exam timetable saying thanks, I will be there", "propose_reply_gmail", {"sender": "Maya", "about": "exam timetable", "body": "Thanks, I will be there."})
    (action,) = agent.actions.actions()
    assert action["args"]["to"] == "maya.rao@example.org" and action["args"]["subject"] == "Re: Exam timetable" and action["args"]["thread_id"] == "threadm00001" and action["args"]["message_id"] == "m00001"
    assert action["summary"].startswith("Reply to Maya Rao <maya@example.com>: Exam timetable") and "by email to maya.rao@example.org" in action["summary"]
    assert gmail.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded"
    (sent,) = gmail.sent()
    assert header_of(sent, "To") == "maya.rao@example.org" and header_of(sent, "In-Reply-To") == "<m00001@mail.example.com>" and sent["threadId"] == "threadm00001"


def test_several_matching_emails_refuse_the_reply_and_the_latest_picks_the_newest(config, gmail):
    agent = propose(config, "reply to Maya's email saying thanks", "propose_reply_gmail", {"sender": "Maya", "body": "Thanks."})
    assert agent.actions.actions() == [] and gmail.mutations() == []
    agent = propose(config, "reply to Maya's latest email saying thanks", "propose_reply_gmail", {"sender": "Maya", "body": "Thanks."})
    (action,) = agent.actions.actions()
    assert action["args"]["message_id"] == "m00003" and action["args"]["subject"] == "Re: Lab report" and action["args"]["references"].endswith("<old2@mail.example.com>")


def test_a_sender_the_person_did_not_say_is_not_searched_for_and_a_search_cannot_be_widened(config, gmail):
    agent = propose(config, "reply to the email about the exam timetable saying thanks", "propose_reply_gmail", {"sender": "Bank", "about": "exam timetable", "body": "Thanks."})
    (action,) = agent.actions.actions()
    assert action["args"]["message_id"] == "m00001"  # "Bank" was not the person's word, so only their words were searched
    with pytest.raises(diya_actions.InvalidArgs, match="say which email"):
        mw.search_for("reply to maya's email", 'Maya" OR in:anywhere', None)  # not the person's words
    query, _ = mw.search_for('reply to Maya" OR in:anywhere', 'Maya" OR in:anywhere', None)  # even their own words cannot add an operator or close the quote
    assert query.count('"') == 2 and "in:" not in query
    assert mw.search_for("reply to maya's email", "Maya")[0].startswith('from:"Maya"')
    with pytest.raises(diya_actions.InvalidArgs, match="say which email"):
        mw.search_for("reply to the email", "Bank", None)


def test_no_email_found_refuses_the_reply(config, gmail):
    agent = propose(config, "reply to Sam's email saying thanks", "propose_reply_gmail", {"sender": "Sam", "body": "Thanks."})
    assert agent.actions.actions() == []


# ---- a forward -------------------------------------------------------------------------------------------------------------------------------------

def test_a_forward_goes_to_a_typed_address_and_carries_the_original_text_read_when_it_is_sent(config, gmail):
    agent = propose(config, "forward the email from the bank to mum@example.com saying see this", "propose_forward_gmail", {"sender": "bank", "to": "mum@example.com", "body": "See this."})
    (action,) = agent.actions.actions()
    assert action["args"]["mode"] == "forward" and action["args"]["to"] == "mum@example.com" and action["args"]["subject"] == "Fwd: Your statement" and "text only without attachments" in action["summary"]
    done = run_approved(agent)
    assert done["status"] == "succeeded"
    (sent,) = gmail.sent()
    text = base64.urlsafe_b64decode(sent["payload"]["body"]["data"] + "==").decode()
    assert header_of(sent, "To") == "mum@example.com" and text.startswith("See this.") and "Forwarded message" in text and "Your balance is 100 rupees." in text and "attachments are not included" in text


def test_a_forward_to_an_address_not_typed_is_refused(config, gmail):
    agent = propose(config, "forward the email from the bank to mum@example.com", "propose_forward_gmail", {"sender": "bank", "to": "other@example.com"})
    assert agent.actions.actions() == []


def test_a_forward_of_an_email_that_changed_sends_nothing(config, gmail):
    agent = propose(config, "forward the email from the bank to mum@example.com", "propose_forward_gmail", {"sender": "bank", "to": "mum@example.com"})
    for h in gmail.messages["m00002"]["payload"]["headers"]:
        if h["name"] == "Subject":
            h["value"] = "Something else"
    done = run_approved(agent)
    assert done["status"] == "failed" and "not what it was" in done["result"] and gmail.mutations() == []


# ---- drafts ------------------------------------------------------------------------------------------------------------------------------------------

def test_a_draft_is_saved_with_no_recipient_needed_and_read_back_and_never_sent(config, gmail):
    agent = propose(config, "draft an email to dad about sunday lunch", "propose_gmail_draft", {"subject": "Sunday lunch", "body": "Hi Dad, are you free for lunch on Sunday?"})
    (action,) = agent.actions.actions()
    assert action["summary"] == "Save a draft email with no recipient yet: 'Sunday lunch' (a draft is not sent)" and "to" not in action["args"]
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "has not been sent" in done["result"] and len(gmail.drafts) == 1 and gmail.sent() == []
    assert not [r for r in gmail.requests if r[1].endswith("/messages/send")]


def test_a_draft_to_an_address_not_typed_is_refused(config, gmail):
    agent = propose(config, "draft an email to dad about sunday lunch", "propose_gmail_draft", {"to": "dad@example.com", "subject": "Sunday lunch", "body": "Hi Dad."})
    assert agent.actions.actions() == []
    agent = propose(config, "draft an email to dad@example.com about sunday lunch", "propose_gmail_draft", {"to": "dad@example.com", "subject": "Sunday lunch", "body": "Hi Dad."})
    (action,) = agent.actions.actions()
    assert action["args"]["to"] == "dad@example.com"


def test_a_draft_is_replaced_by_its_subject_and_a_made_up_id_is_ignored(config, gmail):
    run_approved(propose(config, "draft an email about sunday lunch", "propose_gmail_draft", {"subject": "Sunday lunch", "body": "Version one."}))
    (draft_id,) = gmail.drafts
    agent = propose(config, "draft an email about sunday lunch, replace the draft sunday lunch", "propose_gmail_draft",
                    {"subject": "Sunday lunch", "body": "Version two.", "replaces": "sunday lunch", "replaces_id": "r-evil0000"})
    (action,) = [a for a in agent.actions.actions() if a["status"] == "pending"]
    assert action["args"]["replaces_id"] == draft_id and action["summary"].startswith("Replace the draft 'Sunday lunch'")
    done = run_approved(agent)
    assert done["status"] == "succeeded" and list(gmail.drafts) == [draft_id] and base64.urlsafe_b64decode(gmail.drafts[draft_id]["message"]["payload"]["body"]["data"] + "==").decode().strip() == "Version two."


def test_a_draft_is_thrown_away_only_when_it_is_the_one_proposed(config, gmail):
    run_approved(propose(config, "draft an email about sunday lunch", "propose_gmail_draft", {"subject": "Sunday lunch", "body": "Version one."}))
    agent = propose(config, "delete the draft sunday lunch", "propose_discard_gmail_draft", {"subject": "sunday lunch"})
    (action,) = [a for a in agent.actions.actions() if a["status"] == "pending"]
    assert "Diya cannot bring it back" in action["summary"] and len(gmail.drafts) == 1
    (draft,) = gmail.drafts.values()
    for h in draft["message"]["payload"]["headers"]:
        if h["name"] == "Subject":
            h["value"] = "Changed since"
    done = run_approved(agent)
    assert done["status"] == "failed" and "changed after this was proposed" in done["result"] and len(gmail.drafts) == 1
    agent = propose(config, "delete the draft changed since", "propose_discard_gmail_draft", {"subject": "changed since"})
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "no longer has it" in done["result"] and gmail.drafts == {}


def test_a_draft_that_does_not_exist_cannot_be_proposed_for_throwing_away(config, gmail):
    agent = propose(config, "delete the draft about nothing", "propose_discard_gmail_draft", {"subject": "nothing"})
    assert agent.actions.actions() == []


# ---- filing mail ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("action, said, extra, check", [
    ("archive", "archive the email from the bank", {}, lambda labels: "INBOX" not in labels),
    ("read", "mark the email from the bank as read", {}, lambda labels: "UNREAD" not in labels),
    ("unread", "mark the email from the bank as unread", {}, lambda labels: "UNREAD" in labels),
    ("star", "star the email from the bank", {}, lambda labels: "STARRED" in labels),
    ("trash", "move the email from the bank to the bin", {}, lambda labels: "TRASH" in labels and "INBOX" not in labels),
    ("label", "put the label Exams on the email from the bank", {"label": "Exams"}, lambda labels: "Label_1" in labels),
])
def test_filing_changes_exactly_what_it_says_and_is_read_back(config, gmail, action, said, extra, check):
    gmail.messages["m00002"]["labelIds"].append("UNREAD") if action == "read" else None
    agent = propose(config, said, "propose_organise_gmail", {"action": action, "sender": "bank", **extra})
    (proposed,) = agent.actions.actions()
    assert proposed["status"] == "pending" and proposed["args"]["message_id"] == "m00002" and gmail.mutations() == []
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "read back to check" in done["result"] and check(gmail.messages["m00002"]["labelIds"])
    assert [r[1].rsplit("/", 1)[-1] for r in gmail.mutations()] == ["trash" if action == "trash" else "modify"]


def test_a_message_in_the_bin_is_brought_back_by_name_and_only_from_the_bin(config, gmail):
    gmail.messages["m00002"]["labelIds"] = ["TRASH"]
    agent = propose(config, "bring back the email from the bank", "propose_organise_gmail", {"action": "restore", "sender": "bank"})
    done = run_approved(agent)
    assert done["status"] == "succeeded" and "TRASH" not in gmail.messages["m00002"]["labelIds"] and "INBOX" in gmail.messages["m00002"]["labelIds"]


def test_a_label_that_does_not_exist_or_is_a_system_label_is_refused_and_none_is_made(config, gmail):
    for label in ("Holidays", "INBOX", "Trash"):
        agent = propose(config, f"put the label {label} on the email from the bank", "propose_organise_gmail", {"action": "label", "sender": "bank", "label": label})
        assert agent.actions.actions() == [], label
    assert not [r for r in gmail.requests if r[1].endswith("/labels") and r[0] != "GET"]


def test_an_email_that_is_already_in_the_bin_is_not_filed(config, gmail):
    agent = propose(config, "archive the email from the bank", "propose_organise_gmail", {"action": "archive", "sender": "bank"})
    gmail.messages["m00002"]["labelIds"] = ["TRASH"]
    done = run_approved(agent)
    assert done["status"] == "failed" and "in the bin" in done["result"] and gmail.mutations() == []


def test_a_filing_the_server_did_not_apply_is_not_confirmed(config, gmail, monkeypatch):
    agent = propose(config, "star the email from the bank", "propose_organise_gmail", {"action": "star", "sender": "bank"})
    original = gmail.__call__

    def ignoring(*args, **kwargs):
        if len(args) == 2 and args[0] == "POST" and args[1].endswith("/modify"):
            gmail.requests.append(("POST", args[1], {}, kwargs.get("json")))
            return resp(200, gmail.messages["m00002"])
        return original(*args, **kwargs)

    monkeypatch.setattr(client.httpx, "request", ignoring)
    done = run_approved(agent)
    assert done["status"] == "unknown" and "showed it was not" in done["result"]


# ---- the chat, the catalog and the switches ---------------------------------------------------------------------------------------------------------

def test_a_request_to_send_with_the_send_card_not_connected_says_which_card_and_calls_no_model(config, gmail):
    diya_connectors.disconnect(config, mw.SEND)
    agent = agent_for(config)
    answer, tools = agent.ask([{"role": "user", "content": "send an email to dad@example.com saying I will be late"}])
    assert "'Gmail: send'" in answer and tools == [] and agent.client.chat_calls == [] and gmail.requests == []


def test_a_request_for_many_emails_at_once_is_refused_in_words(config, gmail):
    agent = agent_for(config)
    answer, tools = agent.ask([{"role": "user", "content": "delete all my emails from the bank"}])
    assert "one email at a time" in answer and agent.client.chat_calls == [] and gmail.requests == []


def test_every_kind_is_in_the_catalog_with_its_tier_and_none_can_be_done_straight_away():
    expected = {"propose_gmail_draft": 2, "propose_discard_gmail_draft": 3, "propose_send_gmail": 3, "propose_reply_gmail": 3, "propose_forward_gmail": 3, "propose_organise_gmail": 2}
    assert {name: diya_catalog.CATALOG[name].tier for name in expected} == expected
    assert {k.tool_name for k in mw.action_kinds()} == set(expected)
    assert not {k.name for k in mw.action_kinds()} & set(diya_autoapprove.AUTO_KINDS) and all(k.auto_ok is None for k in mw.action_kinds())
    assert all(diya_catalog.CATALOG[name].approval == "owner approves each action" for name in expected)


def test_the_models_tool_cannot_name_an_address_or_an_id_for_a_reply_a_forward_or_a_filing():
    kinds = {k.name: k for k in mw.action_kinds()}
    for name in ("gmail_reply", "gmail_organise"):
        assert not set(kinds[name].tool["function"]["parameters"]["properties"]) & {"to", "cc", "bcc", "message_id", "thread_id", "label_id", "draft_id"}
    assert "bcc" not in kinds["gmail_send"].tool["function"]["parameters"]["properties"]


def test_the_arguments_of_a_long_reply_stay_inside_what_the_approval_system_keeps(config, gmail):
    gmail.messages["m00003"]["payload"]["headers"][-1]["value"] = " ".join(f"<ref{n:03d}@mail.example.com>" for n in range(60))
    agent = propose(config, "reply to Maya's latest email saying thanks", "propose_reply_gmail", {"sender": "Maya", "body": "x" * mw.BODY_MAX})
    (action,) = agent.actions.actions()
    assert len(diya_actions.canonical(action["args"])) <= diya_actions.MAX_ARGS_CHARS and len(action["args"]["references"]) <= mw.REFERENCES_MAX
