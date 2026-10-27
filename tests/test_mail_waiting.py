"""Mail waiting for a reply, found by code (diya_mail_waiting.py; docs/HOME_DESIGN.md), added 2026-10-27.

What this proves: a thread counts only when its last message is from a person and is not the owner's own, a draft, or in the bin or spam; machines are left out (no-reply and notification addresses,
List-Unsubscribe, Precedence bulk, Auto-Submitted); the oldest wait comes first; no more than MAX_THREADS threads are read, with headers only and never a message body; a thread id that is not Gmail's own is
never put into an address; what a stranger wrote has control characters made visible; and a mailbox that is not connected is said, not guessed.
"""
import dataclasses
from datetime import datetime, timedelta

import pytest

import diya_config
import diya_mail_waiting as mw
from diya_google_mail import MailError

ESC = chr(27)


class Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.headers = status, data, {}

    def json(self):
        return self._data


def message(sender, subject="Lab notes", labels=("INBOX",), minutes_ago=60, extra=()):
    headers = [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}, {"name": "Date", "value": "Tue, 27 Oct 2026 10:00:00 +0530"}]
    headers += [{"name": name, "value": value} for name, value in extra]
    stamp = int((datetime.now() - timedelta(minutes=minutes_ago)).timestamp() * 1000)
    return {"labelIds": list(labels), "internalDate": str(stamp), "payload": {"headers": headers}}


class Gmail:
    """A scripted Gmail: the listing names these threads in this order, and each thread answers with its messages. Every request is kept."""

    def __init__(self, threads, listing=None):
        self.threads, self.listing, self.calls = threads, listing, []

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if url.endswith("/messages"):
            ids = self.listing if self.listing is not None else list(self.threads)
            return Resp({"messages": [{"id": "ffff" + str(n).zfill(4), "threadId": thread} for n, thread in enumerate(ids)]})
        thread_id = url.rsplit("/", 1)[-1]
        return Resp({"id": thread_id, "messages": self.threads[thread_id]})


def mine(minutes_ago=600):
    return message("Me <me@example.com>", labels=["SENT"], minutes_ago=minutes_ago)


def found(threads, cold=False, **kwargs):
    """What waits, for threads in which the person has written first (a conversation); `cold=True` leaves the threads as given."""
    if not cold:
        threads = {key: [mine(), *messages] for key, messages in threads.items()}
    return mw.read(None, get=Gmail(threads, **kwargs), access_token="token")


def test_a_thread_whose_last_message_is_from_a_person_is_waiting():
    (item,) = found({"aaaa0001": [message('"Priya Nair" <Priya@Example.com>', "Lab notes")]})
    assert (item["from_name"], item["from_address"], item["subject"], item["thread"]) == ("Priya Nair", "priya@example.com", "Lab notes", "aaaa0001")
    assert datetime.now() - item["sent"] < timedelta(hours=2)


@pytest.mark.parametrize("labels", [["SENT"], ["DRAFT"], ["TRASH"], ["SPAM", "INBOX"]])
def test_a_thread_already_answered_or_being_answered_is_not_waiting(labels):
    assert found({"aaaa0001": [message("Priya <p@example.com>"), message("Me <me@example.com>", labels=labels)]}) == []


def test_a_cold_message_from_a_stranger_is_not_a_conversation_however_important_gmail_thinks_it_is():
    """Found on the real mailbox: single messages marked Important and Personal that were offers and surveys."""
    offer = message("Hackathon <info@hack.example>", "$15K in prizes", labels=["UNREAD", "IMPORTANT", "CATEGORY_PERSONAL", "INBOX"])
    assert found({"aaaa0001": [offer]}, cold=True) == []


def test_an_earlier_answer_does_not_hide_a_new_message_from_the_other_person():
    mine, theirs = message("Me <me@example.com>", labels=["SENT"], minutes_ago=600), message("Priya <p@example.com>", minutes_ago=30)
    assert len(found({"aaaa0001": [mine, theirs]})) == 1


@pytest.mark.parametrize("sender, extra", [
    ("Shop <noreply@shop.example>", ()), ("GitHub <notifications@github.com>", ()), ("Mail Delivery <mailer-daemon@example.com>", ()), ("Team <do-not-reply@x.example>", ()),
    ("Priya <p@example.com>", [("List-Unsubscribe", "<mailto:x@example.com>")]), ("Priya <p@example.com>", [("Precedence", "bulk")]),
    ("Priya <p@example.com>", [("Precedence", "list")]), ("Priya <p@example.com>", [("Auto-Submitted", "auto-replied")]), ("", ()),
])
def test_machines_are_not_people_waiting_for_an_answer(sender, extra):
    assert found({"aaaa0001": [message(sender, extra=extra)]}) == []


def test_a_message_marked_as_not_automatic_is_still_a_person():
    assert len(found({"aaaa0001": [message("Priya <p@example.com>", extra=[("Auto-Submitted", "no"), ("Precedence", "")])]})) == 1


@pytest.mark.parametrize("header, name, address", [
    ('"Priya Nair" <Priya@X.com>', "Priya Nair", "priya@x.com"), ("priya.nair@x.com", "Priya Nair", "priya.nair@x.com"), ("Priya <p@x.com>", "Priya", "p@x.com"), ("", "", ""), (None, "", ""),
])
def test_the_sender_is_read_from_the_header(header, name, address):
    assert mw.sender_of(header) == (name, address)


def test_the_longest_wait_comes_first():
    threads = {"aaaa0001": [message("New <n@example.com>", minutes_ago=30)], "aaaa0002": [message("Old <o@example.com>", minutes_ago=2000)], "aaaa0003": [message("Mid <m@example.com>", minutes_ago=300)]}
    assert [item["from_name"] for item in found(threads)] == ["Old", "Mid", "New"]


def test_at_most_a_few_threads_are_read_and_only_their_headers():
    threads = {f"aaaa{n:04d}": [mine(), message(f"P{n} <p{n}@example.com>")] for n in range(10)}
    gmail = Gmail(threads)
    mw.read(None, get=gmail, access_token="token")
    assert len(gmail.calls) == 1 + mw.MAX_THREADS
    assert gmail.calls[0][1]["q"] == mw.QUERY
    assert all(params["format"] == "metadata" for url, params in gmail.calls[1:])  # no message body is ever asked for


def test_a_thread_id_that_is_not_gmails_own_is_never_put_into_an_address():
    gmail = Gmail({"aaaa0001": [mine(), message("P <p@example.com>")]}, listing=["../../etc", "aaaa0001", "aaaa0001"])
    assert len(mw.read(None, get=gmail, access_token="token")) == 1
    assert [url for url, _ in gmail.calls].count(gmail.calls[1][0]) == 1 and len(gmail.calls) == 2  # the bad id and the repeat cost nothing


def test_what_a_stranger_wrote_has_its_control_characters_made_visible():
    (item,) = found({"aaaa0001": [message(f"Pri{ESC}[31mya <p@example.com>", f"Pay{ESC}[0m now")]})
    assert ESC not in item["from_name"] and ESC not in item["subject"]


def test_a_missing_time_is_skipped_not_fatal():
    bad = message("P <p@example.com>")
    bad["internalDate"] = "later"
    assert found({"aaaa0001": [bad]}) == []


def test_a_mailbox_that_is_not_connected_is_said(tmp_path):
    config = dataclasses.replace(diya_config.load_config(), connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "c.log"))
    with pytest.raises(MailError) as caught:
        mw.read(config, access_token="")
    assert "Gmail" in str(caught.value)
