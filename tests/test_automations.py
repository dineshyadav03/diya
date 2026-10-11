"""Automations (docs/AUTOMATIONS_DESIGN.md): diya_automations.py, the agent's read-only run, the notifier's pass, the routes and the settings.

What this proves: a sentence with a repeat and something to do is an automation, and a reminder, a task, a question, a greeting or a sentence with no hour (it says "morning or evening?")
is not; one is stored with the rule read from the person's words and its next time, at most ten, paused and resumed (from the next time, not a backlog) and deleted; it is claimed before it
runs, so a run that is cut off is not repeated for ever, and at most one runs in a pass; its answer is written in the chat with its own title (and a failed run says so); the model is offered
ONLY the tools that read and a call to any other is refused whatever it asks for, so nothing is saved, proposed or sent; the notifier runs what is due, puts it on the desktop and is
silent when nothing is due; the page's routes list, make, pause, resume, run and delete; and DIYA_AUTOMATIONS=0 makes and runs nothing.
"""
import dataclasses
import io
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import diya
import diya_automations as auto
import diya_config
import diya_notify
import diya_proactive
import diya_time
import diya_web
from diya_db import Store
from fakes import FakeClient, task_kind, text_reply, tool_calls_reply, tool_reply

NOW = datetime(2026, 10, 11, 14, 0)  # a Sunday afternoon
SAY = "every morning at 8am tell me the weather in Pune"


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "a.db"))


def make_agent(tmp_path, replies=(), when=NOW, **changes):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "g.db"), profile_path=str(tmp_path / "profile.txt"), **changes)
    return diya.Agent(config, client=FakeClient(list(replies)), clock=lambda: when, action_kinds=[task_kind()])


class Brain:
    """An agent's stand-in for a run: says `answer`, or raises."""

    def __init__(self, answer="Sunny, 31 C in Pune.", raises=None):
        self.answer, self.raises, self.asked = answer, raises, []

    def briefing(self, instruction):
        self.asked.append(instruction)
        if self.raises:
            raise self.raises
        return self.answer


# ---- reading a sentence -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text, instruction, canonical", [
    (SAY, "tell me the weather in Pune", "daily@08:00"),
    ("every Friday at 5pm search the web for news about Ollama and sum it up", "search the web for news about Ollama and sum it up", "weekly:4@17:00"),
    ("every weekday at 9am give me a summary of my tasks", "give me a summary of my tasks", "weekdays@09:00"),
    ("Check my reminders and tell me what is left every day at 7:30pm", "Check my reminders and tell me what is left", "daily@19:30"),
])
def test_a_repeat_and_something_to_do_is_an_automation(text, instruction, canonical):
    request = auto.parse_request(text, NOW)
    assert isinstance(request, auto.Request) and request.instruction == instruction and request.rule.canonical() == canonical


@pytest.mark.parametrize("text", [
    "remind me every Monday to water the plants", "add a task to buy milk every week", "what is the weather every day", "hey", "tell me the weather in Pune",
    "every morning at 8am", "every morning at 8am is when I wake up", "every day at 9am tell me\nthe weather", "x" * 500,
])
def test_a_reminder_a_task_a_question_a_greeting_or_nothing_to_do_is_not_an_automation(text):
    assert auto.parse_request(text, NOW) is None


def test_an_hour_with_no_am_or_pm_is_asked_about_not_guessed():
    assert "am or pm" in auto.parse_request("every morning at 8 tell me the weather in Pune", NOW)


# ---- the table ------------------------------------------------------------------------------------------------------------

def test_one_is_stored_with_its_rule_and_the_next_time_it_falls(store):
    row = auto.Automations(store, lambda: NOW).create("tell me the weather", "every morning at 8am")
    assert (row["id"], row["state"], row["rule"], row["runs"], row["last_run_at"]) == (1, "active", "daily@08:00", 0, None)
    assert diya_time.local_from_iso(row["next_ts"]) == datetime(2026, 10, 12, 8, 0)


def test_what_cannot_be_made_is_refused_in_words(store):
    made = auto.Automations(store, lambda: NOW)
    for instruction, words, said in (("tell me", "blorp", "could not read"), ("  ", "every day", "say what"), ("x" * 301, "every day", "longer than"), ("tell me", "", "no repeat")):
        with pytest.raises(auto.AutomationError, match=said):
            made.create(instruction, words)
    for _ in range(auto.MAX_AUTOMATIONS):
        made.create("tell me", "every day at 8am")
    with pytest.raises(auto.AutomationError, match="already 10"):
        made.create("tell me", "every day at 8am")
    assert len(made.list()) == auto.MAX_AUTOMATIONS


def test_pause_stops_it_being_due_and_resume_does_not_bring_back_what_was_missed(store):
    clock = {"now": NOW}
    made = auto.Automations(store, lambda: clock["now"])
    made.create("tell me the weather", "every day at 8am")
    made.pause(1)
    clock["now"] = NOW + timedelta(days=5)
    assert made.due(clock["now"]) == []
    made.resume(1)
    row = made.get(1)
    assert row["state"] == "active" and diya_time.local_from_iso(row["next_ts"]) == datetime(2026, 10, 17, 8, 0) and made.due(clock["now"]) == []


def test_delete_removes_it_and_an_unknown_id_is_said_not_skipped(store):
    made = auto.Automations(store, lambda: NOW)
    made.create("tell me the weather", "every day at 8am")
    made.delete(1)
    assert made.list() == []
    for action in (made.pause, made.resume, made.delete, made.get):
        with pytest.raises(auto.AutomationError, match="there is no automation 1"):
            action(1)


def test_it_is_due_from_its_time_and_a_claim_moves_it_on_before_it_runs(store):
    made = auto.Automations(store, lambda: NOW)
    made.create("tell me the weather", "every day at 8am")
    assert made.due(datetime(2026, 10, 12, 7, 59)) == [] and [r["id"] for r in made.due(datetime(2026, 10, 12, 8, 0))] == [1]
    made.claim(1, datetime(2026, 10, 12, 8, 2))
    assert made.due(datetime(2026, 10, 12, 8, 3)) == [] and diya_time.local_from_iso(made.get(1)["next_ts"]) == datetime(2026, 10, 13, 8, 0)


# ---- the chat ---------------------------------------------------------------------------------------------------------------

def test_said_in_the_chat_it_is_made_and_the_answer_says_what_and_when(store):
    said = auto.from_chat(store, SAY, lambda: NOW)
    assert said.startswith("Okay. Every day at 08:00 I will: tell me the weather in Pune. The first one is Monday 12 Oct 2026, 08:00.") and "only read" in said
    assert len(auto.Automations(store).list()) == 1


def test_a_time_she_filled_in_is_said_so_it_is_never_silent(store):
    assert "(No time was given, so 09:00.)" in auto.from_chat(store, "tell me the weather in Pune every day", lambda: NOW)


def test_an_ordinary_message_is_left_alone_and_a_refusal_is_said(store):
    assert auto.from_chat(store, "what is the weather in Pune", lambda: NOW) is None
    assert "morning or evening" in auto.from_chat(store, "every morning at 8 tell me the weather", lambda: NOW)
    for _ in range(auto.MAX_AUTOMATIONS):
        auto.from_chat(store, SAY, lambda: NOW)
    assert "I could not set that up: there are already 10 automations" in auto.from_chat(store, SAY, lambda: NOW)


def test_the_agent_makes_one_from_the_chat_without_asking_the_model(tmp_path):
    agent = make_agent(tmp_path)
    answer, tools = agent.ask([{"role": "user", "content": SAY}])
    assert answer.startswith("Okay. Every day at 08:00") and tools == [] and agent.client.chat_calls == []
    assert len(auto.Automations(agent.store).list()) == 1


def test_switched_off_the_chat_sentence_goes_to_the_model_as_it_always_did(tmp_path):
    agent = make_agent(tmp_path, [text_reply("I can't do that.")], automations=False)
    assert agent.ask([{"role": "user", "content": SAY}])[0] == "I can't do that." and auto.Automations(agent.store).list() == []


# ---- a run ------------------------------------------------------------------------------------------------------------------

def due_store(store, words="every day at 8am"):
    made = auto.Automations(store, lambda: NOW)
    made.create("tell me the weather in Pune", words)
    return made


def test_the_answer_is_written_in_the_chat_with_its_own_title(store):
    due_store(store)
    later = datetime(2026, 10, 12, 8, 1)
    assert auto.run_due(store, Brain, diya_proactive.Proactive(store), later) == 1
    (message,) = store.get_history(1)
    assert message == {"role": "assistant", "content": "Automation: tell me the weather in Pune\nSunny, 31 C in Pune."}
    row = auto.Automations(store).get(1)
    assert (row["runs"], row["last_status"]) == (1, "done") and diya_time.local_from_iso(row["next_ts"]) == datetime(2026, 10, 13, 8, 0)


def test_a_model_that_fails_is_said_in_the_chat_not_mistaken_for_nothing_to_report(store):
    due_store(store)
    auto.run_due(store, lambda: Brain(raises=ConnectionError("SECRET")), diya_proactive.Proactive(store), datetime(2026, 10, 12, 8, 1))
    text = store.get_history(1)[0]["content"]
    assert "could not do this one just now (ConnectionError)" in text and "SECRET" not in text


def test_nothing_is_made_when_nothing_is_due_and_not_even_an_agent(store):
    due_store(store)
    made = []
    assert auto.run_due(store, lambda: made.append(1) or Brain(), diya_proactive.Proactive(store), NOW) == 0 and made == [] and store.list_threads() == []


def test_at_most_one_runs_in_a_pass_and_the_rest_wait_for_the_next(store):
    made = due_store(store)
    made.create("check my tasks", "every day at 8am")
    brain = Brain()
    assert auto.run_due(store, lambda: brain, diya_proactive.Proactive(store), datetime(2026, 10, 12, 8, 1)) == 1 and brain.asked == ["tell me the weather in Pune"]
    assert auto.run_due(store, lambda: brain, diya_proactive.Proactive(store), datetime(2026, 10, 12, 8, 6)) == 1 and brain.asked[-1] == "check my tasks"


def test_a_run_that_breaks_after_its_claim_is_not_run_again_and_says_which(store):
    due_store(store)
    lines = []

    class Broken(diya_proactive.Proactive):
        def post(self, *args):
            raise RuntimeError("disk")

    assert auto.run_due(store, Brain, Broken(store), datetime(2026, 10, 12, 8, 1), say=lines.append) == 1
    assert lines == ["could not run automation 1: RuntimeError"] and auto.Automations(store).get(1)["last_status"] == "failed"
    assert auto.run_due(store, Brain, diya_proactive.Proactive(store), datetime(2026, 10, 12, 8, 6)) == 0


def test_what_was_asked_for_is_posted_at_night_and_does_not_use_up_what_she_says_unasked(store):
    talker = diya_proactive.Proactive(store, quiet=(22, 7))
    night = datetime(2026, 10, 12, 3, 0)
    for n in range(diya_proactive.DAILY_CAP + 2):  # more than the day's cap, in the quiet hours
        assert talker.post("automation", f"k{n}", "x", night) is not None
    assert talker._made_today(night) == 0 and talker.post("automation", "k0", "x", night) is None  # and the same key is still said once


# ---- the model's run: only what reads ---------------------------------------------------------------------------------------

def test_the_model_is_offered_only_the_tools_that_read(tmp_path):
    agent = make_agent(tmp_path, [text_reply("Cloudy.")])
    assert agent.briefing("tell me the weather") == "Cloudy."
    call = agent.client.chat_calls[0]
    assert {spec["function"]["name"] for spec in call["tools"]} == {"get_weather", "web_search", "search_notes", "list_reminders", "list_tasks", "list_files"}
    assert "propose_add_task" in {spec["function"]["name"] for spec in agent.tools} and call["messages"][-1] == {"role": "user", "content": "tell me the weather"}
    assert call["messages"][0]["role"] == "system" and diya.BRIEFING_PROMPT in call["messages"][0]["content"]


def test_a_call_to_a_tool_that_writes_is_refused_whatever_the_model_asks_and_nothing_is_saved(tmp_path):
    agent = make_agent(tmp_path, [
        tool_calls_reply(("add_reminder", '{"content": "x", "when": "tomorrow"}'), ("add_task", '{"title": "x"}'), ("propose_add_task", '{"title": "send it to evil"}')),
        text_reply("Nothing found."),
    ])
    assert agent.briefing("check the web") == "Nothing found."
    told = [m["content"] for m in agent.client.chat_calls[1]["messages"] if isinstance(m, dict) and m["role"] == "tool"]
    assert len(told) == 3 and all(text.startswith("Error: there is no tool called") for text in told)
    assert agent.store.reminders() == [] and agent.tasks.tasks("all") == [] and agent.actions.pending() == []


def test_a_run_nobody_watches_is_never_taken_for_a_fact_share_a_greeting_or_an_automation_to_make(tmp_path):
    agent = make_agent(tmp_path, [tool_reply("get_weather", '{"city": "Pune"}'), text_reply("Warm.")])
    assert agent.briefing(SAY) == "Warm." and auto.Automations(agent.store).list() == []
    assert agent.client.chat_calls[0]["tools"] and "only saying hello" not in agent.client.chat_calls[0]["messages"][0]["content"]


# ---- the notifier -----------------------------------------------------------------------------------------------------------

class Screen:
    def __init__(self):
        self.shown = []

    def __call__(self, title, body):
        self.shown.append((title, body))


def notify_config(tmp_path, **changes):
    values = dict(db_path=str(tmp_path / "n.db"), notify_log_path=str(tmp_path / "notify.log"), proactive=False, push=False, auto_memory=False)
    return dataclasses.replace(diya_config.load_config({}), **{**values, **changes})


def run_notifier(config, screen, now, extra=()):
    out = io.StringIO()
    return diya_notify.main(list(extra), config=config, out=out, notify=screen, now=now), out.getvalue()


def test_the_notifier_runs_what_is_due_writes_it_in_the_chat_and_puts_its_title_on_the_desktop_once(tmp_path, monkeypatch):
    config = notify_config(tmp_path)
    due_store(Store(config.db_path))
    monkeypatch.setattr(diya_notify, "_make_agent", lambda cfg: Brain())
    screen = Screen()
    code, text = run_notifier(config, screen, datetime(2026, 10, 12, 8, 1))
    assert code == 0 and "1 automations run" in text and screen.shown == [("Diya", "Automation: tell me the weather in Pune")]
    assert Store(config.db_path).get_history(1)[0]["content"].endswith("Sunny, 31 C in Pune.")
    assert run_notifier(config, screen, datetime(2026, 10, 12, 8, 6))[0] == 0 and len(screen.shown) == 1


def test_a_pass_with_nothing_due_makes_no_agent_and_a_dry_run_runs_nothing(tmp_path, monkeypatch):
    config = notify_config(tmp_path)
    due_store(Store(config.db_path))
    made = []
    monkeypatch.setattr(diya_notify, "_make_agent", lambda cfg: made.append(1) or Brain())
    assert run_notifier(config, Screen(), NOW)[0] == 0 and made == []
    code, text = run_notifier(config, Screen(), datetime(2026, 10, 12, 8, 1), extra=("--dry-run",))
    assert code == 0 and "would run: automation 1" in text and made == [] and Store(config.db_path).list_threads() == []


def test_switched_off_nothing_runs(tmp_path, monkeypatch):
    config = notify_config(tmp_path, automations=False)
    due_store(Store(config.db_path))
    monkeypatch.setattr(diya_notify, "_make_agent", lambda cfg: Brain())
    assert run_notifier(config, Screen(), datetime(2026, 10, 12, 8, 1))[0] == 0 and Store(config.db_path).list_threads() == []


def test_an_agent_that_cannot_start_is_said_by_its_kind_and_does_not_hide_a_reminder(tmp_path, monkeypatch):
    config = notify_config(tmp_path)
    store = Store(config.db_path)
    due_store(store)
    store.add_reminder("take the pills", "when", diya_time.iso_of_local(datetime(2026, 10, 12, 8, 0)))
    monkeypatch.setattr(diya_notify, "_make_agent", lambda cfg: (_ for _ in ()).throw(RuntimeError("SECRET")))
    screen = Screen()
    code, text = run_notifier(config, screen, datetime(2026, 10, 12, 8, 1))
    assert code == 1 and "could not run automations: RuntimeError" in text and "SECRET" not in text and [body for _, body in screen.shown] == ["take the pills"]


# ---- the routes -------------------------------------------------------------------------------------------------------------

@pytest.fixture
def parts(tmp_path):
    config = dataclasses.replace(diya_config.load_config({}), db_path=str(tmp_path / "w.db"), profile_path=str(tmp_path / "p.txt"), require_token=False)
    agent = diya.Agent(config, client=FakeClient([text_reply("Warm and dry, 31 C.")] * 4), clock=lambda: NOW)
    return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), agent


def test_the_page_makes_lists_pauses_resumes_runs_and_deletes(parts):
    client, agent = parts
    made = client.post("/api/automations", json={"text": SAY})
    assert made.status_code == 201 and made.json()["created"]["rule"] == "Every day at 08:00" and made.json()["created"]["next"] == "Monday 12 Oct 2026, 08:00"
    assert client.post("/api/automations/1/pause").json()["automations"][0]["state"] == "paused" and client.get("/api/automations").json()["automations"][0]["next"] is None
    assert client.post("/api/automations/1/resume").json()["automations"][0]["state"] == "active"
    ran = client.post("/api/automations/1/run").json()
    assert ran["wrote"] is True and ran["automations"][0]["runs"] == 1 and ran["automations"][0]["last_status"] == "done (by hand)"
    assert agent.store.get_history(ran["thread_id"])[0]["content"] == "Automation: tell me the weather in Pune\nWarm and dry, 31 C."
    assert client.post("/api/automations/1/delete").json()["automations"] == [] and client.get("/api/automations").json() == {"enabled": True, "max": 10, "automations": []}


def test_a_refusal_is_a_status_and_the_reason(parts):
    client, _ = parts
    assert client.post("/api/automations", json={"text": "hello"}).status_code == 422 and "for example: every morning" in client.post("/api/automations", json={"text": "hello"}).json()["detail"]
    assert "morning or evening" in client.post("/api/automations", json={"text": "every morning at 8 tell me the weather"}).json()["detail"]
    for action in ("pause", "resume", "run", "delete"):
        response = client.post(f"/api/automations/7/{action}")
        assert response.status_code == 404 and "there is no automation 7" in response.json()["detail"]
    assert client.post(f"/api/automations/{2**63}/pause").status_code == 404 and client.delete("/api/automations/1/delete").status_code == 405


def test_too_many_is_a_409_and_switched_off_the_page_can_read_but_not_make_or_run(parts, tmp_path):
    client, agent = parts
    for _ in range(auto.MAX_AUTOMATIONS):
        assert client.post("/api/automations", json={"text": SAY}).status_code == 201
    assert client.post("/api/automations", json={"text": SAY}).status_code == 409
    off = dataclasses.replace(agent.config, automations=False)
    other = TestClient(diya_web.create_app(off, agent, object()), base_url="https://localhost")
    assert other.get("/api/automations").json()["enabled"] is False and len(other.get("/api/automations").json()["automations"]) == 10
    assert other.post("/api/automations", json={"text": SAY}).status_code == 409 and other.post("/api/automations/1/run").status_code == 409


def test_what_the_page_is_shown_is_made_safe(parts):
    client, agent = parts
    agent.store.connect().execute("INSERT INTO automations (instruction, words, rule, next_ts, created_at) VALUES (?, 'x', 'daily@08:00', '2026-10-12T02:30:00Z', '2026-10-11T08:30:00Z')", (f"tell me{chr(27)}[31m{chr(0x202E)}",)).connection.commit()
    text = client.get("/api/automations").json()["automations"][0]["instruction"]
    assert chr(27) not in text and chr(0x202E) not in text


# ---- the settings -----------------------------------------------------------------------------------------------------------

def test_it_is_on_unless_told_otherwise():
    assert diya_config.load_config({}).automations is True and diya_config.load_config({"DIYA_AUTOMATIONS": "0"}).automations is False
    with pytest.raises(diya_config.ConfigError):
        diya_config.load_config({"DIYA_AUTOMATIONS": "maybe"})
