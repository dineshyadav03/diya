"""The routes behind the Knowledge page (docs/KNOWLEDGE_DESIGN.md, K1 step 2): diya_knowledge_api.py.

What this proves: the list says what is there and where the notes are read from, and says plainly when it is only the demo folder; building reads the notes and answers what it did; hiding and
unhiding change the list at once; a refusal is an HTTP error with a reason and changes nothing; a page of the person's own is never listed; only GET and POST exist; and what comes back is made
safe to show (a note with an escape sequence in it cannot rewrite what the page says).

Hidden characters are built with chr() so they stay visible in this file (tests/test_text_files.py).
"""
import dataclasses

import pytest
from fastapi.testclient import TestClient

import diya
import diya_config
import diya_knowledge
import diya_web
from fakes import FakeClient, text_reply

LOCAL = "https://localhost"
ESC = chr(27)
STORY = {
    "monday.md": "- Call Maya about the move to Lisbon.\nRocky has a vet checkup on Thursday. Maya's flight lands at 9.\nShould call the vet too.\n",
    "my notes/journal.txt": "Went for a long walk with Rocky by the river.\nMaya called in the evening; she says Lisbon is warm already.\nShould call back.\n",
}


@pytest.fixture
def config(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    return dataclasses.replace(
        diya_config.load_config(),
        db_path=str(tmp_path / "api.db"),
        profile_path=str(tmp_path / "profile.txt"),
        notes_dir=str(notes),
        knowledge_dir=str(tmp_path / "knowledge"),
        require_token=False,
    )


@pytest.fixture
def client(config):
    agent = diya.Agent(config, client=FakeClient([text_reply("ok")] * 5))
    return TestClient(diya_web.create_app(config, agent, object()), base_url=LOCAL)


def write_notes(config, files):
    import pathlib

    for name, text in files.items():
        path = pathlib.Path(config.notes_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")


def names(body):
    return [page["name"] for page in body["pages"]]


# --- the list ------------------------------------------------------------------------------------------------------------------


def test_before_anything_is_built_the_list_is_empty_and_says_where_the_notes_are(client, config):
    body = client.get("/api/knowledge").json()
    assert body == {"notes_folder": config.notes_dir, "demo": False, "built": False, "pages": [], "hidden": []}


def test_the_demo_folder_is_said_to_be_the_demo(config, tmp_path):
    demo = dataclasses.replace(config, notes_dir=str(tmp_path / "sample_notes"))
    agent = diya.Agent(demo, client=FakeClient([text_reply("ok")]))
    body = TestClient(diya_web.create_app(demo, agent, object()), base_url=LOCAL).get("/api/knowledge").json()
    assert body["demo"] is True


def test_building_reads_the_notes_and_answers_what_it_did_and_the_list(client, config):
    write_notes(config, STORY)
    body = client.post("/api/knowledge/build").json()
    assert body["report"] == {"notes": 2, "pages": 3, "written": 3, "unchanged": 0, "removed": 0, "left_out": [], "skipped_names": [], "refused_names": 0, "over_page_limit": 0}
    assert body["built"] is True and names(body) == ["Maya", "Lisbon", "Rocky"]
    maya = body["pages"][0]
    assert maya["stem"] == "Maya" and maya["notes"] == 2 and maya["omitted"] == 0
    assert {"text": "Call Maya about the move to Lisbon.", "source": "monday.md"} in maya["sentences"]
    assert {"text": "Maya called in the evening; she says Lisbon is warm already.", "source": "my notes/journal.txt"} in maya["sentences"]  # a path with a space in it
    assert maya["links"] == ["Lisbon"]
    assert client.get("/api/knowledge").json() == {k: v for k, v in body.items() if k != "report"}


def test_a_second_build_changes_nothing_and_says_so(client, config):
    write_notes(config, STORY)
    client.post("/api/knowledge/build")
    assert client.post("/api/knowledge/build").json()["report"] == {"notes": 2, "pages": 3, "written": 0, "unchanged": 3, "removed": 0, "left_out": [], "skipped_names": [], "refused_names": 0, "over_page_limit": 0}


def test_a_build_with_no_notes_folder_is_a_409_with_the_reason(client, config):
    import shutil

    shutil.rmtree(config.notes_dir)
    response = client.post("/api/knowledge/build")
    assert response.status_code == 409 and "does not exist" in response.json()["detail"]


def test_a_build_with_nothing_to_find_still_answers(client, config):
    write_notes(config, {"a.txt": "just some words here"})
    body = client.post("/api/knowledge/build").json()
    assert body["report"]["pages"] == 0 and body["pages"] == [] and body["built"] is True


# --- hiding --------------------------------------------------------------------------------------------------------------------


def test_hiding_removes_the_page_at_once_and_unhiding_lets_the_next_build_make_it(client, config):
    write_notes(config, STORY)
    client.post("/api/knowledge/build")
    hidden = client.post("/api/knowledge/hide", json={"name": "Maya"}).json()
    assert hidden["changed"] is True and "Maya" not in names(hidden) and hidden["hidden"] == ["Maya"]
    assert client.post("/api/knowledge/hide", json={"name": "maya"}).json()["changed"] is False
    assert "Maya" not in names(client.post("/api/knowledge/build").json())
    back = client.post("/api/knowledge/unhide", json={"name": "Maya"}).json()
    assert back["changed"] is True and back["hidden"] == []
    assert "Maya" in names(client.post("/api/knowledge/build").json())
    assert client.post("/api/knowledge/unhide", json={"name": "Maya"}).json()["changed"] is False


@pytest.mark.parametrize("name", ["", "a", "../x", "a/b", "[[x]]", "12345", "bad<name>"])
def test_a_name_that_cannot_have_a_page_is_a_422_and_changes_nothing(client, config, name):
    write_notes(config, STORY)
    client.post("/api/knowledge/build")
    before = client.get("/api/knowledge").json()
    response = client.post("/api/knowledge/hide", json={"name": name})
    assert response.status_code == 422 and "not a name" in response.json()["detail"]
    assert client.get("/api/knowledge").json() == before


def test_a_body_that_is_not_a_name_is_refused(client):
    assert client.post("/api/knowledge/hide", json={}).status_code == 422
    assert client.post("/api/knowledge/hide", json={"name": "x" * 201}).status_code == 422
    assert client.post("/api/knowledge/hide", json={"name": 5}).status_code == 422


# --- what is shown -------------------------------------------------------------------------------------------------------------


def test_a_file_of_the_persons_own_in_the_knowledge_folder_is_not_a_page(client, config):
    import pathlib

    write_notes(config, STORY)
    client.post("/api/knowledge/build")
    pathlib.Path(config.knowledge_dir, "My own page.md").write_text("# mine\n- written by hand — nowhere\n", encoding="utf-8")
    assert "My own page" not in [p["stem"] for p in client.get("/api/knowledge").json()["pages"]]


def test_escape_sequences_in_a_note_reach_the_browser_as_visible_escapes(client, config):
    write_notes(config, {"a.txt": f"Told Maya {ESC}[31mred text.", "b.txt": "Saw Maya again."})
    body = client.post("/api/knowledge/build").json()
    text = body["pages"][0]["sentences"][0]["text"] + body["pages"][0]["sentences"][1]["text"]
    assert ESC not in text and "u001b" in text


def test_a_long_page_says_how_many_more_there_are(client, config):
    write_notes(config, {"a.txt": "\n".join(f"Did thing number {n} with Maya." for n in range(60)), "b.txt": "Saw Maya again."})
    maya = client.post("/api/knowledge/build").json()["pages"][0]
    assert len(maya["sentences"]) == diya_knowledge.MAX_BULLETS and maya["omitted"] == 21


# --- who may ask, and what exists ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["put", "delete", "patch"])
def test_only_get_and_post_exist(client, method):
    for path in ("/api/knowledge", "/api/knowledge/build", "/api/knowledge/hide", "/api/knowledge/unhide"):
        assert getattr(client, method)(path).status_code in (404, 405)


def test_get_does_not_build_and_post_does_not_read_a_body_it_does_not_need(client, config):
    write_notes(config, STORY)
    client.get("/api/knowledge")
    assert client.get("/api/knowledge").json()["built"] is False
    assert client.post("/api/knowledge/build").status_code == 200


def test_the_routes_need_the_access_token_when_one_is_required(config, tmp_path):
    secured = dataclasses.replace(config, require_token=True)
    agent = diya.Agent(secured, client=FakeClient([text_reply("ok")]))
    client = TestClient(diya_web.create_app(secured, agent, object()), base_url=LOCAL)
    assert client.get("/api/knowledge").status_code == 401
    assert client.post("/api/knowledge/build").status_code == 401
    assert client.post("/api/knowledge/hide", json={"name": "Maya"}).status_code == 401
