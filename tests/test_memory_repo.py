"""Memory as an Agent Memory Repo (diya_memory_repo.py, `diya_review.py export-repo`; docs/MEMORY_REPO_DESIGN.md), added 2026-10-20 from the study of Devin's memory (docs/STUDY_DEVIN.md).

What this proves, with the real memory: the folder has the shape the standard describes (a short MEMORY.md with an Index of [[links]] that all point at files that exist, one note per named person, a note for passing
states and one for retired facts); every entry is one bullet on one line with its metadata at the end as `[key: value; key: value]`; the lasting facts about the owner go in MEMORY.md up to a limit and the rest in
a second note, so the entry point stays short; a name or a fact can never create a path, a link or a second line; waiting, turned-down and forgotten-for-good facts are absent; exporting changes nothing and never
overwrites; and the command line says what it wrote. It does not prove that another tool reads the folder: the standard is a convention, and no other tool was run against it.
"""
import dataclasses
import io
import os
import re
import sqlite3

import pytest

import diya_config
import diya_memory
import diya_memory_repo as repo
import diya_review
from diya_db import Store
from diya_memory import Memory

ENTRY = re.compile(r"^- (?P<text>.+?)(?: \[(?P<meta>[a-z-]+: [^\];]+(?:; [a-z-]+: [^\];]+)*)\])?$")


@pytest.fixture
def memory(tmp_path):
    return Memory(Store(str(tmp_path / "r.db")))


def sql(memory, query, args=()):
    with sqlite3.connect(memory.store.path) as conn:
        conn.execute(query, args)


def build_memory(memory):
    ids = {}
    ids["typed"] = memory.add_manual("Studies medicine.", "api")
    ids["own"] = memory.add_manual("Has a dog named Hog.", "api")
    sql(memory, "UPDATE fact_events SET actor = 'auto', event = 'accepted' WHERE fact_id = ?", (ids["own"],))
    sql(memory, "UPDATE facts SET flags = '[\"source_message:12\"]', source = 'dreaming' WHERE id = ?", (ids["own"],))
    ids["mom"] = memory.add_manual("Likes gardening.", "api")
    memory.set_person(ids["mom"], "Mom", "api")
    ids["gone"] = memory.add_manual("Takes the 7:40 bus.", "api")
    memory.decide(ids["gone"], "retire", "api")
    ids["passing"] = memory.add_manual("Is reading Dune for now.", "api")
    memory.reinforce(ids["passing"], 5, "auto")
    sql(memory, "INSERT INTO facts (text, text_key, status, source, flags, created_at) VALUES ('Waiting fact.', 'waiting fact.', 'candidate', 'dreaming', '[]', '2026-01-01T00:00:00+00:00')")
    sql(memory, "INSERT INTO facts (text, text_key, status, source, flags, created_at) VALUES ('Turned down fact.', 'turned down fact.', 'rejected', 'dreaming', '[]', '2026-01-01T00:00:00+00:00')")
    return ids


def test_the_folder_has_the_shape_the_standard_describes(memory):
    build_memory(memory)
    files = repo.build(memory)
    assert set(files) == {"MEMORY.md", "people/mom.md", "passing.md", "retired.md"}
    main = files["MEMORY.md"]
    assert main.startswith("# What Diya remembers about you") and "cognition.com/agent-memory-repo" in main
    assert "## About you" in main and "## Index" in main
    assert "- Studies medicine. [" in main and "- Has a dog named Hog. [" in main
    assert "Is reading Dune" not in main and "Takes the 7:40 bus" not in main and "Likes gardening" not in main  # each is in its own note, not in the entry point


def test_every_index_link_points_at_a_file_that_exists_and_every_file_is_linked(memory):
    build_memory(memory)
    files = repo.build(memory)
    linked = set(re.findall(r"\[\[([^\]]+)\]\]", files["MEMORY.md"]))
    assert linked == {"people/mom", "passing", "retired"}
    assert all(f"{target}.md" in files for target in linked)
    assert {path[:-3] for path in files if path != "MEMORY.md"} == linked


def test_every_entry_is_one_bullet_on_one_line_with_its_metadata_at_the_end(memory):
    build_memory(memory)
    for path, text in repo.build(memory).items():
        for line in text.splitlines():
            if line.startswith("- ") and not line.startswith("- [["):
                match = ENTRY.match(line)
                assert match, (path, line)
    own = next(line for line in repo.build(memory)["MEMORY.md"].splitlines() if "Hog" in line)
    assert "source: message 12" in own and "by: auto" in own and re.search(r"added: \d{4}-\d{2}-\d{2}", own)
    typed = next(line for line in repo.build(memory)["MEMORY.md"].splitlines() if "medicine" in line)
    assert "source: typed" in typed and "by: typed" in typed


def test_a_passing_state_says_when_it_fades_and_how_often_it_was_said_again(memory):
    build_memory(memory)
    line = next(l for l in repo.build(memory)["passing.md"].splitlines() if "Dune" in l)
    assert "said-again: 1" in line and re.search(r"fades: \d{4}-\d{2}-\d{2}", line)


def test_waiting_turned_down_and_forgotten_facts_are_not_in_it(memory):
    build_memory(memory)
    secret = memory.add_manual("Surprise party planned for Sam.", "api")
    memory.purge(secret, "api")
    everything = "\n".join(repo.build(memory).values())
    assert "Waiting fact" not in everything and "Turned down fact" not in everything and "Surprise party" not in everything
    assert diya_memory.PURGED_PLACEHOLDER not in everything


def test_the_entry_point_stays_short_and_the_rest_goes_to_a_second_note(tmp_path):
    memory = Memory(Store(str(tmp_path / "big.db")), store_limit=20000)  # (a memory may keep more than it tells once recall is on)
    for number in range(80):
        memory.add_manual(f"Owns umbrella number {number} for the rainy season of the year.", "api")
    files = repo.build(memory)
    entries = [l for l in files["MEMORY.md"].splitlines() if l.startswith("- Owns")]
    assert sum(len(l) for l in entries) <= repo.MAIN_CHARS and "about-you-more.md" in files and "[[about-you-more]]" in files["MEMORY.md"]
    more = [l for l in files["about-you-more.md"].splitlines() if l.startswith("- Owns")]
    assert len(entries) + len(more) == 80  # nothing is lost, only moved


def test_a_name_or_a_fact_can_never_make_a_path_a_link_or_a_second_line(memory):
    odd = memory.add_manual("Fact with [[a link]] inside.", "api")
    named = memory.add_manual("Knows the way.", "api")
    memory.set_person(named, "../../Evil Name", "api")
    files = repo.build(memory)
    assert all(".." not in path and "\\" not in path and (path == "MEMORY.md" or re.fullmatch(r"(people/)?[a-z0-9-]+\.md", path)) for path in files)
    assert "[[a link]]" not in "\n".join(files.values()) and "[ [a link] ]" in files["MEMORY.md"]
    assert odd and all(len(re.findall(r"^- ", text, re.M)) == len([l for l in text.splitlines() if l.startswith("- ")]) for text in files.values())


def test_two_names_that_make_the_same_file_name_get_different_files(memory):
    for name in ("Anne-Marie", "Anne Marie"):
        fact = memory.add_manual(f"Knows {name}.", "api")
        memory.set_person(fact, name, "api")
    files = repo.build(memory)
    assert sorted(path for path in files if path.startswith("people/")) == ["people/anne-marie-2.md", "people/anne-marie.md"]


def test_a_name_with_no_plain_letters_still_gets_a_file(memory):
    fact = memory.add_manual("Knows a friend.", "api")
    memory.set_person(fact, "小明", "api")
    assert "people/person.md" in repo.build(memory)


def test_nothing_changes_in_the_database_and_nothing_existing_is_overwritten(memory, tmp_path):
    build_memory(memory)
    before = [(f["id"], f["status"], memory.events(f["id"])) for f in memory.facts()]
    folder = tmp_path / "out"
    written = repo.export_repo(memory, str(folder))
    assert sorted(written) == ["MEMORY.md", "passing.md", "people/mom.md", "retired.md"] and (folder / "people" / "mom.md").is_file()
    assert before == [(f["id"], f["status"], memory.events(f["id"])) for f in memory.facts()]
    assert b"\r\n" not in (folder / "MEMORY.md").read_bytes()  # LF only
    with pytest.raises(repo.RepoError):
        repo.export_repo(memory, str(folder))  # now it is not empty
    (tmp_path / "a-file").write_text("x")
    with pytest.raises(repo.RepoError):
        repo.export_repo(memory, str(tmp_path / "a-file"))
    empty = tmp_path / "empty"
    empty.mkdir()
    assert repo.export_repo(memory, str(empty))  # an empty folder is fine


def test_an_empty_memory_makes_a_readable_entry_point(memory):
    files = repo.build(memory)
    assert list(files) == ["MEMORY.md"] and "_Nothing yet._" in files["MEMORY.md"] and "_Nothing else yet._" in files["MEMORY.md"]


@pytest.fixture
def config(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    return dataclasses.replace(diya_config.load_config(), db_path=str(data / "cli.db"), profile_path=str(data / "profile.txt"), dream_state_path=str(data / "state.json"),
                               dream_log_path=str(data / "dream.log"), dream_pending_path=str(data / "pending.jsonl"))


def review(config, *argv):
    out, err = io.StringIO(), io.StringIO()
    code = diya_review.main(list(argv), config=config, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_the_command_line_writes_a_new_folder_and_refuses_one_in_use(config, tmp_path):
    Memory(Store(config.db_path)).add_manual("Has a dog named Hog.", "cli")
    folder = tmp_path / "memory-repo"
    code, out, err = review(config, "export-repo", str(folder))
    assert code == 0 and "Wrote 1 file" in out and "MEMORY.md" in out and "the database is unchanged" in out
    assert "Has a dog named Hog." in (folder / "MEMORY.md").read_text(encoding="utf-8")
    code, out, err = review(config, "export-repo", str(folder))
    assert code == diya_review.EXIT_REFUSED and "not empty" in err
