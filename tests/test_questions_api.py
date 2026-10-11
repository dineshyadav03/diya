"""The questions Diya raises herself, over HTTP (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5): diya_questions_api.py, the quiet-hours setting, Dreaming's refill and the
desktop notifier's one line.

What this proves: with automatic memory off nothing is made, listed or answered; the list is at most what the pace allows, in words made by code, and empty in the quiet
hours (a setting) though the questions are still there; each answer does what it says through the route and a refused one changes nothing and leaves the question open;
an accepted offer makes a real reminder at the time the question said; the notifier says only THAT there is a question, once, never in the quiet hours; and Dreaming's pass
makes the questions.
"""
import dataclasses
import io
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_notify
import diya_questions as q
import diya_time
import diya_web
import dreaming
from diya_db import Store
from diya_memory import Memory
from fakes import ByQuestionClient, FakeClient, text_reply

SUNDAY = datetime(2026, 10, 11, 9, 0)
CREATED = "2026-10-11T03:30:00+00:00"


def make_config(tmp_path, **changes):
    settings = dict(db_path=str(tmp_path / "d.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"),
                    dream_pending_path=str(tmp_path / "pending.jsonl"), profile_path=str(tmp_path / "profile.txt"), notify_log_path=str(tmp_path / "notify.log"),
                    auto_memory=True, require_token=False)
    return dataclasses.replace(diya_config.load_config({}), **{**settings, **changes})


@pytest.fixture
def parts(tmp_path):
    clock = {"now": SUNDAY}

    def build(**changes):
        config = make_config(tmp_path, **changes)
        agent = diya.Agent(config, client=FakeClient([]), clock=lambda: clock["now"])
        return TestClient(diya_web.create_app(config, agent, object()), base_url="https://localhost"), agent, config, clock
    return build


def waiting(memory, text, flags=("ask:sensitive:model_private",), position=0):
    fact_id = memory.add_candidate(text, batch_first=1, batch_last=1, position=position, model="m", extracted_at=CREATED, raw="- " + text)
    memory.set_flags(fact_id, list(flags), "system")
    return fact_id


# --- the list ---------------------------------------------------------------------------------------------------------------

def test_with_automatic_memory_off_nothing_is_made_listed_or_answered(parts):
    client, agent, _, _ = parts(auto_memory=False)
    waiting(Memory(agent.store), "takes metformin")
    assert client.get("/api/questions").json() == {"questions": []}
    assert q.Questions(agent.store)._rows("") == []
    assert client.post("/api/questions/seen", json={"ids": [1]}).json() == {"seen": 0}
    response = client.post("/api/questions/1/answer", json={"answer": "no"})
    assert response.status_code == 409 and "off" in response.json()["detail"]


def test_a_waiting_fact_is_put_to_the_person_in_words_with_the_answers_it_offers(parts):
    client, agent, _, _ = parts()
    waiting(Memory(agent.store), "takes metformin")
    body = client.get("/api/questions").json()
    assert body == {"questions": [{
        "id": 1, "kind": "sensitive", "fact_id": 1,
        "text": "“takes metformin” looks private, so I did not keep it without asking. May I remember it?",
        "options": [{"answer": "yes", "label": "Yes, remember it"}, {"answer": "no", "label": "No, do not"}]}]}


def test_asking_again_does_not_make_more_than_the_pace_allows(parts):
    client, agent, _, clock = parts()
    memory = Memory(agent.store)
    for n in range(6):
        waiting(memory, f"private thing number {n}", position=n)
    assert len(client.get("/api/questions").json()["questions"]) == 2
    assert len(client.get("/api/questions").json()["questions"]) == 2
    clock["now"] = SUNDAY + timedelta(hours=25)
    assert len(client.get("/api/questions").json()["questions"]) == 3


def test_in_the_quiet_hours_the_list_is_empty_though_the_questions_are_there(parts):
    client, agent, _, clock = parts()
    waiting(Memory(agent.store), "takes metformin")
    clock["now"] = datetime(2026, 10, 11, 23, 0)
    assert client.get("/api/questions").json() == {"questions": []} and len(q.Questions(agent.store).open()) == 1
    clock["now"] = datetime(2026, 10, 12, 8, 0)
    assert len(client.get("/api/questions").json()["questions"]) == 1


def test_the_quiet_hours_are_a_setting_and_off_means_there_are_none(parts):
    client, agent, _, clock = parts(questions_quiet="off")
    waiting(Memory(agent.store), "takes metformin")
    clock["now"] = datetime(2026, 10, 11, 23, 0)
    assert len(client.get("/api/questions").json()["questions"]) == 1
    clock["now"] = SUNDAY
    other, agent2, _, _ = parts(questions_quiet="09-17", db_path=str(agent.store.path) + "2")
    waiting(Memory(agent2.store), "takes metformin")
    assert other.get("/api/questions").json() == {"questions": []}  # 09:00 is inside 09-17


@pytest.mark.parametrize("setting", ["22", "25-3", "7-7", "late"])
def test_a_quiet_hours_setting_that_is_not_two_hours_is_refused_at_start(setting):
    with pytest.raises(diya_config.ConfigError, match="DIYA_QUESTIONS_QUIET"):
        diya_config.load_config({"DIYA_QUESTIONS_QUIET": setting})


def test_the_quiet_hours_default_to_ten_at_night_until_seven():
    assert diya_config.load_config({}).questions_quiet == "22-07" and diya_time.parse_quiet(diya_config.load_config({}).questions_quiet) == (22, 7)
    assert diya_config.load_config({"DIYA_QUESTIONS_QUIET": " off "}).questions_quiet == "off"


def test_a_question_whose_fact_has_gone_is_not_listed(parts):
    client, agent, _, _ = parts()
    fact = waiting(Memory(agent.store), "takes metformin")
    q.Questions(agent.store).refill(Memory(agent.store), SUNDAY)
    conn = agent.store.connect()
    conn.execute("DELETE FROM facts WHERE id = ?", (fact,))
    conn.commit()
    conn.close()
    assert client.get("/api/questions").json() == {"questions": []}


# --- seen -------------------------------------------------------------------------------------------------------------------

def test_telling_the_page_a_question_was_shown_starts_its_day(parts):
    client, agent, _, _ = parts()
    waiting(Memory(agent.store), "takes metformin")
    client.get("/api/questions")
    assert client.post("/api/questions/seen", json={"ids": [1]}).json() == {"seen": 1}
    assert q.Questions(agent.store).get(1)["shown_at"] == q._iso(SUNDAY)


def test_ids_that_cannot_be_questions_are_ignored_and_a_long_list_is_cut(parts):
    client, agent, _, _ = parts()
    body = client.post("/api/questions/seen", json={"ids": [0, -3, 2**63, 5] + list(range(100, 140))}).json()
    assert body == {"seen": 1 + (20 - 4)}  # only the first twenty are looked at; of those, 0, -3 and 2**63 cannot be questions


def test_the_longest_list_looked_at_is_twenty():
    import diya_questions_api

    assert diya_questions_api.MAX_SEEN == 20


@pytest.mark.parametrize("body", [{}, {"ids": "1"}, {"ids": ["a"]}, {"ids": None}])
def test_a_seen_body_that_is_not_a_list_of_numbers_is_refused(parts, body):
    client, _, _, _ = parts()
    assert client.post("/api/questions/seen", json=body).status_code == 422


# --- answering --------------------------------------------------------------------------------------------------------------

def test_yes_remembers_the_fact_and_no_longer_lists_the_question(parts):
    client, agent, _, _ = parts()
    memory = Memory(agent.store)
    fact = waiting(memory, "takes metformin")
    client.get("/api/questions")
    body = client.post("/api/questions/1/answer", json={"answer": "yes"}).json()
    assert body == {"question": {"id": 1, "state": "answered", "answer": "yes"}} and memory.get(fact)["status"] == "accepted"
    assert client.get("/api/questions").json() == {"questions": []}


def test_edit_rewords_and_remembers(parts):
    client, agent, _, _ = parts()
    memory = Memory(agent.store)
    fact = waiting(memory, "might like tea", ["ask:doubt:ungrounded"])
    client.get("/api/questions")
    assert client.post("/api/questions/1/answer", json={"answer": "edit", "text": "likes green tea"}).status_code == 200
    assert (memory.get(fact)["status"], memory.get(fact)["text"]) == ("accepted", "likes green tea")


def test_the_checks_are_run_again_after_an_answer(parts):
    client, agent, _, _ = parts()
    memory = Memory(agent.store)
    first = waiting(memory, "likes green tea", ["ask:doubt:ungrounded"], 0)
    twin = waiting(memory, "likes green tea", ["ask:doubt:ungrounded"], 1)
    client.get("/api/questions")
    client.post("/api/questions/1/answer", json={"answer": "yes"})
    assert f"duplicate:{first}" in memory.get(twin)["flags"]


@pytest.mark.parametrize("question_id, status, reason", [(99, 404, "there is no question 99"), (0, 404, "there is no question 0"), (2**63, 404, "there is no question")])
def test_a_question_that_is_not_there_is_a_404(parts, question_id, status, reason):
    client, _, _, _ = parts()
    response = client.post(f"/api/questions/{question_id}/answer", json={"answer": "yes"})
    assert response.status_code == status and reason in response.json()["detail"]


def test_an_answer_the_question_does_not_offer_is_a_422_and_changes_nothing(parts):
    client, agent, _, _ = parts()
    memory = Memory(agent.store)
    fact = waiting(memory, "takes metformin")
    client.get("/api/questions")
    for body in ({"answer": "maybe"}, {"answer": "edit", "text": "x"}, {"answer": "keep"}):
        assert client.post("/api/questions/1/answer", json=body).status_code == 422
    assert memory.get(fact)["status"] == "candidate" and q.Questions(agent.store).get(1)["state"] == "open"


def test_an_edit_with_nothing_in_it_is_a_422(parts):
    client, agent, _, _ = parts()
    waiting(Memory(agent.store), "might like tea", ["ask:doubt:ungrounded"])
    client.get("/api/questions")
    assert client.post("/api/questions/1/answer", json={"answer": "edit", "text": "  -  "}).status_code == 422


def test_a_question_answered_twice_is_a_409(parts):
    client, agent, _, _ = parts()
    waiting(Memory(agent.store), "takes metformin")
    client.get("/api/questions")
    client.post("/api/questions/1/answer", json={"answer": "no"})
    response = client.post("/api/questions/1/answer", json={"answer": "no"})
    assert response.status_code == 409 and "only an open question" in response.json()["detail"]


def test_an_answer_the_memory_refuses_is_a_409_and_leaves_the_question_open(parts):
    client, agent, _, _ = parts()
    memory = Memory(agent.store)
    memory.add_manual("takes metformin", "api")
    fact = waiting(memory, "Takes metformin")
    client.get("/api/questions")
    response = client.post("/api/questions/1/answer", json={"answer": "yes"})
    assert response.status_code == 409 and "says the same thing" in response.json()["detail"]
    assert memory.get(fact)["status"] == "candidate" and q.Questions(agent.store).get(1)["state"] == "open"


@pytest.mark.parametrize("body", [{}, {"answer": 5}, {"answer": None}, {"text": "x"}])
def test_a_body_with_no_answer_is_a_422(parts, body):
    client, agent, _, _ = parts()
    waiting(Memory(agent.store), "takes metformin")
    client.get("/api/questions")
    assert client.post("/api/questions/1/answer", json=body).status_code == 422


def test_yes_to_an_offer_makes_a_reminder_at_the_time_the_question_said(parts):
    client, agent, _, clock = parts()
    memory = Memory(agent.store)
    fact = memory.add_manual("has a dentist appointment on Friday at 3pm", "api")
    conn = agent.store.connect()
    conn.execute("UPDATE facts SET created_at = ? WHERE id = ?", (CREATED, fact))
    conn.commit()
    conn.close()
    clock["now"] = SUNDAY + timedelta(hours=1)
    (question,) = client.get("/api/questions").json()["questions"]
    assert "Want a reminder at Friday 16 Oct 2026, 14:00?" in question["text"]
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "yes"})
    (reminder,) = agent.store.reminders("pending")
    assert reminder["content"] == "has a dentist appointment on Friday at 3pm" and reminder["due_ts"] == diya_time.iso_of_local(datetime(2026, 10, 16, 14, 0))


# --- Dreaming makes them ----------------------------------------------------------------------------------------------------

def test_the_scheduled_pass_makes_the_questions_after_putting_facts_in_their_lanes(tmp_path, capsys):
    config = make_config(tmp_path)
    store = Store(config.db_path)
    thread = store.create_thread()
    message = store.add_message(thread, "user", "I take sertraline every morning")
    import json

    (tmp_path / "pending.jsonl").write_text(json.dumps({"timestamp": "2026-10-11T00:00:00+00:00", "first_message_id": message, "last_message_id": message, "model": "m",
                                                       "facts": ["- takes sertraline every morning"]}) + "\n", encoding="utf-8")
    client = ByQuestionClient(privacy=["PRIVATE", "PRIVATE"])
    dreaming.Dreamer(config, client=client, store=store).remember_on_its_own()
    assert [item["kind"] for item in q.Questions(store).open()] == ["sensitive"]
    assert "1 new questions to put to you." in capsys.readouterr().out


def test_a_message_read_live_that_leaves_a_question_makes_it_at_once(tmp_path):
    config = make_config(tmp_path)
    store = Store(config.db_path)
    message = store.add_message(store.create_thread(), "user", "I take sertraline every morning")
    client = ByQuestionClient(extraction=["- takes sertraline every morning"], privacy=["PRIVATE", "PRIVATE"])
    dreaming.Dreamer(config, client=client, store=store).capture_message(message)
    assert [item["kind"] for item in q.Questions(store).open()] == ["sensitive"]


def test_with_automatic_memory_off_the_scheduled_pass_makes_no_questions(tmp_path):
    config = make_config(tmp_path, auto_memory=False)
    store = Store(config.db_path)
    waiting(Memory(store), "takes metformin")
    dreaming.Dreamer(config, client=ByQuestionClient(), store=store).remember_on_its_own()
    assert q.Questions(store)._rows("") == []


# --- the desktop notifier ---------------------------------------------------------------------------------------------------

class Screen:
    def __init__(self, failing=False):
        self.shown, self.failing = [], failing

    def __call__(self, title, body):
        if self.failing:
            raise diya_notify.NotifyError("the screen is not there")
        self.shown.append((title, body))


def questions_in(tmp_path, count=1, **changes):
    config = make_config(tmp_path, **changes)
    store = Store(config.db_path)
    memory = Memory(store)
    for n in range(count):
        waiting(memory, f"private thing number {n}", position=n)
    q.Questions(store).refill(memory, SUNDAY)
    return config, store


def test_the_notifier_says_only_that_there_is_a_question_once(tmp_path):
    config, store = questions_in(tmp_path)
    screen = Screen()
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY) == (1, 0)
    assert screen.shown == [("Diya", "Diya has a question for you.")]
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY + timedelta(hours=1)) == (0, 0) and len(screen.shown) == 1


def test_several_questions_are_one_notification_that_counts_them_and_names_none(tmp_path):
    config, store = questions_in(tmp_path, count=3)
    screen = Screen()
    diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY)
    assert screen.shown == [("Diya", "Diya has 2 questions for you.")] and "private thing" not in str(screen.shown)


def test_the_notifier_is_silent_in_the_quiet_hours_and_tells_when_they_end(tmp_path):
    config, store = questions_in(tmp_path)
    screen = Screen()
    assert diya_notify.tell_questions(store, screen, (22, 7), now=datetime(2026, 10, 11, 23, 0)) == (0, 0) and screen.shown == []
    assert diya_notify.tell_questions(store, screen, (22, 7), now=datetime(2026, 10, 12, 7, 0)) == (1, 0)


def test_a_notification_that_could_not_be_shown_is_tried_again_next_time(tmp_path):
    config, store = questions_in(tmp_path)
    assert diya_notify.tell_questions(store, Screen(failing=True), (22, 7), now=SUNDAY) == (0, 1)
    screen = Screen()
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY) == (1, 0) and len(screen.shown) == 1


def test_a_dry_run_says_what_it_would_tell_and_records_nothing(tmp_path):
    config, store = questions_in(tmp_path)
    said, screen = [], Screen()
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY, dry_run=True, say=said.append) == (0, 0)
    assert said == ["would tell: Diya | Diya has a question for you."] and screen.shown == []
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY) == (1, 0)


def test_a_question_that_was_ignored_and_is_waiting_is_not_told_about(tmp_path):
    config, store = questions_in(tmp_path)
    queue = q.Questions(store)
    queue.seen([1], SUNDAY)
    queue.refill(Memory(store), SUNDAY + timedelta(hours=25))  # ignored: it waits three days
    screen = Screen()
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY + timedelta(hours=26)) == (0, 0) and screen.shown == []
    assert diya_notify.tell_questions(store, screen, (22, 7), now=SUNDAY + timedelta(hours=25, days=3, minutes=1)) == (1, 0)  # when the three days are over


def test_the_command_tells_about_questions_only_with_automatic_memory_on(tmp_path):
    config, store = questions_in(tmp_path)
    screen, out = Screen(), io.StringIO()
    code = diya_notify.main([], config=config, out=out, notify=screen, now=SUNDAY)
    assert code == 0 and screen.shown == [("Diya", "Diya has a question for you.")] and "1 questions told" in out.getvalue()
    (tmp_path / "off").mkdir()
    config_off, _ = questions_in(tmp_path / "off")
    screen2 = Screen()
    diya_notify.main([], config=dataclasses.replace(config_off, auto_memory=False), out=io.StringIO(), notify=screen2, now=SUNDAY)
    assert screen2.shown == []


def test_the_log_for_a_told_question_holds_a_count_and_never_its_words(tmp_path):
    config, store = questions_in(tmp_path)
    diya_notify.main([], config=config, out=io.StringIO(), notify=Screen(), now=SUNDAY)
    log = open(config.notify_log_path, encoding="utf-8").read()
    assert "1 questions told, 0 failed" in log and "private thing" not in log


def test_a_failed_question_notification_makes_the_command_say_so(tmp_path):
    config, store = questions_in(tmp_path)
    assert diya_notify.main([], config=config, out=io.StringIO(), notify=Screen(failing=True), now=SUNDAY) == diya_notify.EXIT_SOME_FAILED


# --- the edges ---------------------------------------------------------------------------------------------------------------

def test_a_question_that_cannot_be_put_into_words_is_left_out_and_the_rest_are_still_listed(parts, monkeypatch):
    client, agent, _, _ = parts()
    memory = Memory(agent.store)
    waiting(memory, "takes metformin", position=0)
    waiting(memory, "has a private thing", position=1)
    real = q.Questions.describe

    def flaky(self, memory_, question):
        if question["id"] == 1:
            raise diya_memory.UnknownFact("its fact went between the list and the words")
        return real(self, memory_, question)

    import diya_memory

    monkeypatch.setattr(q.Questions, "describe", flaky)
    assert [item["id"] for item in client.get("/api/questions").json()["questions"]] == [2]


def test_the_notifier_counts_what_it_told(tmp_path):
    config, store = questions_in(tmp_path, count=3)
    assert diya_notify.tell_questions(store, Screen(), (22, 7), now=SUNDAY) == (2, 0)  # the pace made two of the three


def test_the_notifier_uses_the_quiet_hours_it_is_given_not_the_usual_ones(tmp_path):
    config, store = questions_in(tmp_path)
    night = datetime(2026, 10, 11, 23, 0)
    screen = Screen()
    assert diya_notify.tell_questions(store, screen, None, now=night) == (1, 0) and len(screen.shown) == 1  # no quiet hours: told at night
    (tmp_path / "two").mkdir()
    config2, store2 = questions_in(tmp_path / "two")
    assert diya_notify.tell_questions(store2, Screen(), (9, 17), now=SUNDAY + timedelta(hours=1)) == (0, 0)  # 10:00 is inside 09-17


def test_the_command_uses_the_setting_for_the_quiet_hours(tmp_path):
    config, store = questions_in(tmp_path, questions_quiet="off")
    screen = Screen()
    assert diya_notify.main([], config=config, out=io.StringIO(), notify=screen, now=datetime(2026, 10, 11, 23, 30)) == 0 and len(screen.shown) == 1
    (tmp_path / "quiet").mkdir()
    config2, _ = questions_in(tmp_path / "quiet", questions_quiet="09-17")
    screen2 = Screen()
    diya_notify.main([], config=config2, out=io.StringIO(), notify=screen2, now=SUNDAY + timedelta(hours=1))
    assert screen2.shown == []


def test_a_question_that_cannot_be_looked_at_is_said_and_makes_the_command_report_a_failure_without_undoing_the_reminders(tmp_path, monkeypatch):
    config, store = questions_in(tmp_path)
    monkeypatch.setattr(diya_notify, "tell_questions", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the table is locked")))
    out = io.StringIO()
    assert diya_notify.main([], config=config, out=out, notify=Screen(), now=SUNDAY) == diya_notify.EXIT_SOME_FAILED
    assert "could not look at the questions: the table is locked" in out.getvalue()
    assert "0 due, 0 told, 0 failed" in out.getvalue()  # the reminders were looked at first and are as they were
