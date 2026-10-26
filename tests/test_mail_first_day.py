"""What the first real use of Gmail showed (2026-10-26, the day it was connected), kept as tests (docs/GMAIL_DESIGN.md).

The owner asked "did anyone email me this week?". Diya searched Gmail for mail FROM a person called "anyone", found nothing, said "your inbox is clear", and, told "but there are mails", said it had no access to
Gmail at all. Four faults, each fixed in code: "anyone/someone/people" are not senders; a search that finds nothing is reported by code and never as an empty inbox; a message that disputes the report before it
looks at the recent inbox again; and while Gmail is connected the model is told so, so that it cannot say it has no access. The stand-in Gmail and the helpers are those of tests/test_google_mail.py.
"""
import pytest

import diya
import diya_connectors
import diya_google_mail as gm
import diya_intent as intent
from fakes import text_reply
from test_google_calendar import config  # noqa: F401 -- a fixture
from test_google_mail import EXAM, FEES, Gmail, ask, connected, feed, make_agent  # noqa: F401 -- `connected` is a fixture


@pytest.mark.parametrize("text, query", [
    ("did anyone email me this week?", "newer_than:7d"), ("has anybody emailed me today", "newer_than:1d"), ("did someone email me", "in:inbox newer_than:7d"),
    ("did somebody write to me yesterday", "newer_than:2d"), ("did anyone reply to my email", "in:inbox newer_than:7d"), ("what mail came in this week", "newer_than:7d"),
    ("are there any mails from people?", "in:inbox newer_than:7d"), ("anything from anyone about the exam?", "exam"), ("did everyone reply to my email", "in:inbox newer_than:7d"),
])
def test_anyone_someone_and_people_are_not_senders_and_not_search_words(text, query):
    assert gm.mail_query(text)[0] == query


@pytest.mark.parametrize("text, query", [
    ("did the bank email me", 'from:"bank"'), ("any email from Sarah", 'from:"sarah"'), ("did Sarah reply to my email", 'from:"sarah"'), ("what did my professor email me about the exam?", 'from:"professor" exam'),
])
def test_a_real_sender_is_still_searched_for(text, query):
    assert gm.mail_query(text)[0] == query


def test_a_search_that_finds_nothing_is_said_by_code_and_never_as_an_empty_inbox(tmp_path, monkeypatch, connected):
    feed(monkeypatch, Gmail([]))
    agent = make_agent(tmp_path, [])  # no model reply is available: if the model were asked, the test would fail
    answer, tools = ask(agent, "any email from the college?")
    assert tools == ["read_mail"] and agent.client.chat_calls == []
    assert answer.startswith("Nothing matched that search (from college).") and "does not mean there is no mail" in answer and "- no message matched" in answer
    assert "inbox is clear" not in answer.lower() and "no new messages" not in answer.lower()
    latest = agent.store.journal_recent(limit=1)[0]
    assert latest["tool"] == "read_mail" and latest["status"] == "ok"  # a search that found nothing is a search that worked


def test_but_there_are_mails_after_a_report_looks_at_the_recent_inbox_again(tmp_path, monkeypatch, connected):
    gmail = feed(monkeypatch, Gmail([EXAM, FEES]))
    agent = make_agent(tmp_path, [text_reply("Dr Rao wrote that the exam moved, and Accounts sent a fee reminder.")])
    before = "No emails from nobody.\n\n" + gm.REPORT_MARK + " from nobody:\n\n- no message matched"
    answer, tools = agent.ask([{"role": "user", "content": "did anyone email me"}, {"role": "assistant", "content": before}, {"role": "user", "content": "but there are mails"}])
    assert tools == ["read_mail"] and "Dr Rao wrote" in answer and "Exam moved" in answer
    assert gmail.asked[0][1]["q"] == "in:inbox newer_than:7d"  # the whole recent inbox, not the search that found nothing


def test_a_dispute_that_does_not_follow_a_mail_report_is_not_a_mail_question(tmp_path, monkeypatch, connected):
    gmail = feed(monkeypatch, Gmail([EXAM]))
    agent = make_agent(tmp_path, [text_reply("I did not look at your mail.")])
    answer, tools = agent.ask([{"role": "user", "content": "what is the capital of france"}, {"role": "assistant", "content": "Paris."}, {"role": "user", "content": "but there are mails"}])
    assert gmail.asked == [] and tools == []  # nothing before it was a mail report: it goes the ordinary way


@pytest.mark.parametrize("text", ["but there are mails", "there are emails in my inbox", "i have emails", "check again", "look again", "are you sure?", "you missed some emails", "but there are mails from the college"])
def test_a_short_dispute_of_a_mail_report_is_recognised(text):
    assert intent.disputes_mail_answer(text)


@pytest.mark.parametrize("text", ["what is the capital of france", "remind me to call mom", "", None, 5, "x" * 200, "but\nthere are mails", "thanks that is helpful"])
def test_anything_else_is_not_a_dispute(text):
    assert not intent.disputes_mail_answer(text)


def isolated_agent(tmp_path, replies, connected_mail):
    """An agent whose connector tokens are in a temporary folder (never the real one), with Gmail signed in or not."""
    agent = make_agent(tmp_path, replies, connector_tokens_dir=str(tmp_path / "tokens"), connectors_log_path=str(tmp_path / "connectors.log"))
    if connected_mail:
        diya_connectors.store_token(agent.config, gm.TOKEN, "a-made-up-refresh-token")
    return agent


def test_while_gmail_is_connected_the_model_is_told_so_when_mail_comes_up_in_a_way_the_mail_step_does_not_take(tmp_path, monkeypatch, connected):
    feed(monkeypatch, Gmail([EXAM]))
    agent = isolated_agent(tmp_path, [text_reply("Nice. Ask me plainly if you want mail looked at, for example 'check my inbox'.")], True)
    ask(agent, "i like using gmail for school")  # mentions mail, but is not a question the mail step takes: the model answers, and must not say it has no access
    assert diya.MAIL_CONNECTED_NOTE in str(agent.client.chat_calls[0]["messages"]).replace("\'", "'") or "Gmail IS connected" in str(agent.client.chat_calls[0]["messages"])
    assert "Never say you have no access" in diya.MAIL_CONNECTED_NOTE


def test_the_note_is_not_sent_when_mail_is_not_mentioned_or_gmail_is_not_connected(tmp_path, monkeypatch, connected):
    agent = isolated_agent(tmp_path, [text_reply("Paris.")], True)
    ask(agent, "what is the capital of france")
    assert "Gmail IS connected" not in str(agent.client.chat_calls[0]["messages"])
    other = isolated_agent(tmp_path / "other", [text_reply("It is a mail service.")], False)
    ask(other, "i like using gmail for school")
    assert "Gmail IS connected" not in str(other.client.chat_calls[0]["messages"])
