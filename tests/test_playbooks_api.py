"""GET /api/playbooks (diya_playbooks_api.py; docs/PLAYBOOKS_DESIGN.md), added 2026-10-20.

What this proves: the route lists the playbooks that are used, with what each is for, how it starts and its steps, and the files that are not used with the reason; it says when the switch is off or the folder is
not there; everything from a file reaches the browser with hidden and control characters made visible; only GET exists; and nothing is written by it (the files are untouched). Access without the token is
tests/test_token.py's.
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_web
from fakes import FakeClient

LOCAL = "https://localhost"
GOOD = "---\nname: study-plan\ndescription: Use when I ask for a study plan or a revision schedule\ntriggers: [user, model]\nargument-hint: the subject\n---\nAsk which exam first.\n"


class Quiet:
    def transcribe(self, path):
        return ""


def client_for(tmp_path, **changes):
    config = dataclasses.replace(
        diya_config.load_config({}), db_path=str(tmp_path / "p.db"), dream_log_path=str(tmp_path / "log"), dream_state_path=str(tmp_path / "state.json"), dream_pending_path=str(tmp_path / "pending.jsonl"),
        profile_path=str(tmp_path / "profile.txt"), require_token=False, playbooks_dir=str(tmp_path / "playbooks"), **{"playbooks": True, **changes},
    )
    return TestClient(diya_web.create_app(config, diya.Agent(config, client=FakeClient()), Quiet()), base_url=LOCAL), config


def write(tmp_path, name, text):
    folder = tmp_path / "playbooks" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")


def test_it_lists_what_is_used_and_what_is_not_with_the_reason(tmp_path):
    write(tmp_path, "study-plan", GOOD)
    write(tmp_path, "broken", "nothing useful")
    client, _ = client_for(tmp_path)
    body = client.get("/api/playbooks").json()
    assert body["enabled"] is True and body["exists"] is True and body["folder"].endswith("playbooks")
    assert body["playbooks"] == [{"name": "study-plan", "description": "Use when I ask for a study plan or a revision schedule", "triggers": ["user", "model"], "hint": "the subject",
                                  "steps": "Ask which exam first.", "chars": len("Ask which exam first.")}]
    assert body["problems"] == [{"file": "broken/SKILL.md", "reason": "it must start with a --- block giving name, description and triggers"}]
    assert body["limits"] == {"playbooks": 30, "steps_chars": 1500}


def test_with_no_folder_or_the_switch_off_it_says_so(tmp_path):
    client, _ = client_for(tmp_path)
    body = client.get("/api/playbooks").json()
    assert body["exists"] is False and body["playbooks"] == [] and body["problems"] == []
    write(tmp_path, "study-plan", GOOD)
    off, _ = client_for(tmp_path, playbooks=False)
    body = off.get("/api/playbooks").json()
    assert body["enabled"] is False and body["playbooks"] == [] and body["exists"] is True


def test_what_comes_from_a_file_reaches_the_browser_made_safe(tmp_path):
    hostile = GOOD.replace("Ask which exam first.", "Ask" + chr(0x202E) + chr(27) + "[31m which exam" + chr(0x200B) + " first.")
    write(tmp_path, "study-plan", hostile)
    text = str(client_for(tmp_path)[0].get("/api/playbooks").json())
    assert chr(0x202E) not in text and chr(27) not in text and chr(0x200B) not in text


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_it_only_reads(tmp_path, method):
    client, _ = client_for(tmp_path)
    assert getattr(client, method)("/api/playbooks").status_code == 405


def test_asking_changes_nothing_on_disk(tmp_path):
    write(tmp_path, "study-plan", GOOD)
    before = {p: p.read_bytes() for p in (tmp_path / "playbooks").rglob("*") if p.is_file()}
    client, _ = client_for(tmp_path)
    client.get("/api/playbooks")
    assert {p: p.read_bytes() for p in (tmp_path / "playbooks").rglob("*") if p.is_file()} == before
