"""Memory as a Markdown copy (diya_markdown.py, Memory.restore_exported, `diya_review.py export-markdown / restore-markdown`; docs/MARKDOWN_MEMORY_DESIGN.md), task DIYA-033, added 2026-10-18.

What this proves, with the real memory and a real second database: the copy is plain Markdown grouped by who a fact is about, with the in-use facts and the retired ones, and it leaves out what is not
the owner's to have kept (facts still waiting, facts turned down, facts forgotten for good); exporting changes nothing; restoring the copy into an empty memory gives back the same words, people, statuses,
first-taken-in dates and 'kept' marks, with an intact trail; who had taken each fact in is recorded as history and never as the owner's own act, and the number of the message it was read from is not turned
into a live link; a restore can be run again and never changes or removes what is there; a file that is not an export, or has damaged lines, is refused or skipped line by line and never guessed at;
a file cannot claim a date in the future; and the command line writes a file only if there is none.
It does not prove the file suits every editor or that a person's hand edits are all caught: whatever does not parse is reported and skipped.
"""
import dataclasses
import io
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import diya_config
import diya_markdown as md
import diya_memory
import diya_provenance as prov
import diya_review
from diya_db import Store
from diya_memory import InvalidFact, Memory


@pytest.fixture
def pair(tmp_path):
    return Memory(Store(str(tmp_path / "a.db"))), Memory(Store(str(tmp_path / "b.db")))


def sql(memory, query, args=()):
    with sqlite3.connect(memory.store.path) as conn:
        conn.execute(query, args)


def build(a):
    """A memory with each kind of fact: typed, taken on Diya's own, about someone else, retired, kept, said again, waiting, turned down."""
    typed = a.add_manual("Studies medicine.", "api")
    own = a.add_manual("Has a dog named Hog.", "api")
    sql(a, "UPDATE fact_events SET actor = 'auto', event = 'accepted' WHERE fact_id = ?", (own,))  # as if the memory rules had taken it in
    mom = a.add_manual("Likes gardening.", "api")
    a.set_person(mom, "Mom", "api")
    gone = a.add_manual("Takes the 7:40 bus.", "api")
    a.decide(gone, "retire", "api")
    kept = a.add_manual("Is reading Dune for now.", "api")
    a.keep(kept, "api")
    again = a.add_manual("Has a sore knee right now.", "api")
    a.reinforce(again, 5, "auto")
    sql(a, "INSERT INTO facts (text, text_key, status, source, flags, created_at) VALUES ('Waiting fact.', 'waiting fact.', 'candidate', 'dreaming', '[]', '2026-01-01T00:00:00+00:00')")
    sql(a, "INSERT INTO facts (text, text_key, status, source, flags, created_at) VALUES ('Turned down fact.', 'turned down fact.', 'rejected', 'dreaming', '[]', '2026-01-01T00:00:00+00:00')")
    return {"typed": typed, "own": own, "mom": mom, "gone": gone, "kept": kept, "again": again}


def shape(memory):
    return sorted((f["text"], f["person"], f["status"]) for f in memory.facts() if f["status"] in ("accepted", "retired"))


def test_the_copy_is_grouped_by_person_and_holds_in_use_and_retired_facts_only(pair):
    a, _ = pair
    build(a)
    text = md.export_markdown(a)
    assert text.startswith("# What Diya remembers about you\n<!-- diya-memory-markdown 1 · exported ")
    assert "## About you" in text and "## About Mom" in text and "## No longer used (retired)" in text
    assert "- Studies medicine. <!-- diya " in text and "- Takes the 7:40 bus. <!-- diya " in text
    assert "Waiting fact." not in text and "Turned down fact." not in text
    assert text.index("## About you") < text.index("## About Mom") < text.index("## No longer used")


def test_a_fact_forgotten_for_good_is_not_in_the_copy(pair):
    a, _ = pair
    fact = a.add_manual("Secret plan about the surprise.", "api")
    a.purge(fact, "api")
    assert "Secret plan" not in md.export_markdown(a) and diya_memory.PURGED_PLACEHOLDER not in md.export_markdown(a)


def test_exporting_changes_nothing(pair):
    a, _ = pair
    build(a)
    before = (shape(a), [a.events(f["id"]) for f in a.facts()])
    md.export_markdown(a)
    assert (shape(a), [a.events(f["id"]) for f in a.facts()]) == before


def test_the_round_trip_gives_back_the_words_people_statuses_dates_and_kept_marks(pair):
    a, b = pair
    build(a)
    restored, already, problems = md.restore_markdown(b, md.export_markdown(a))
    assert (restored, already, problems) == (6, 0, [])
    assert shape(b) == shape(a)
    by_text_a = {f["text"]: f for f in a.facts()}
    for fact in b.facts():
        assert fact["created_at"] == by_text_a[fact["text"]]["created_at"]  # the date it was first taken in is kept
    assert b.is_kept(next(f["id"] for f in b.facts() if f["text"] == "Is reading Dune for now."))
    assert not b.is_kept(next(f["id"] for f in b.facts() if f["text"] == "Has a sore knee right now."))
    assert b.verify_integrity() == []  # replaying every trail lands on the status shown


def test_who_took_each_fact_in_is_history_and_never_the_owners_own_act(pair):
    a, b = pair
    build(a)
    md.restore_markdown(b, md.export_markdown(a))
    dog = next(f for f in b.facts() if f["text"] == "Has a dog named Hog.")
    event, actor, at, detail = b.events(dog["id"])[0]
    assert (event, actor) == ("imported", "import") and '"originally": "auto"' in detail and '"from": "markdown export"' in detail
    typed = next(f for f in b.facts() if f["text"] == "Studies medicine.")
    assert '"originally": "typed"' in b.events(typed["id"])[0][3]


def test_the_message_it_was_read_from_is_not_turned_into_a_live_link(pair):
    a, b = pair
    fact = a.add_manual("Has a dog named Hog.", "api")
    sql(a, "UPDATE facts SET flags = '[\"source_message:7\"]' WHERE id = ?", (fact,))
    assert '"message":7' in md.export_markdown(a)  # the reference travels in the file...
    md.restore_markdown(b, md.export_markdown(a))
    restored = b.facts()[0]
    assert diya_memory.source_message_id(restored) is None and not any(f.startswith("source_message") for f in restored["flags"])  # ...but is not a link in another database
    assert '"message": 7' in b.events(restored["id"])[0][3]  # it stays in the trail as a number


def test_provenance_says_a_restored_fact_was_restored_and_quotes_no_message(pair):
    a, b = pair
    a.add_manual("Has a dog named Hog.", "api")
    md.restore_markdown(b, md.export_markdown(a))
    fact = b.facts()[0]
    text = prov.describe(b, b.store, fact)
    assert "restored from a Markdown copy" in text and "You told me" not in text and "You accepted it" not in text


def test_a_restore_can_be_run_again_and_never_changes_what_is_there(pair):
    a, b = pair
    build(a)
    text = md.export_markdown(a)
    md.restore_markdown(b, text)
    snapshot = [(f["id"], f["text"], f["status"], b.events(f["id"])) for f in b.facts()]
    assert md.restore_markdown(b, text) == (0, 6, [])
    assert snapshot == [(f["id"], f["text"], f["status"], b.events(f["id"])) for f in b.facts()]


def test_what_is_already_there_is_left_alone_and_only_the_missing_comes_in(pair):
    a, b = pair
    build(a)
    mine = b.add_manual("Studies medicine.", "api")  # already here, on its own terms
    b.decide(mine, "retire", "api")  # ...and retired
    restored, already, _ = md.restore_markdown(b, md.export_markdown(a))
    assert restored == 5 and already == 1  # a fact retired here is not brought back by a file
    assert b.get(mine)["status"] == "retired"


def test_a_retired_fact_does_not_come_back_as_a_second_copy_of_an_accepted_one(pair):
    a, b = pair
    b.add_manual("Takes the 7:40 bus.", "api")
    gone = a.add_manual("Takes the 7:40 bus.", "api")
    a.decide(gone, "retire", "api")
    assert md.restore_markdown(b, md.export_markdown(a)) == (0, 1, [])


def test_what_was_kept_does_not_fade_and_a_restored_passing_fact_is_on_a_fresh_clock(pair):
    a, b = pair
    build(a)
    sql(a, "UPDATE facts SET created_at = '2026-01-01T00:00:00+00:00' WHERE text LIKE '%right now%'")  # long ago
    md.restore_markdown(b, md.export_markdown(a))
    knee = next(f["id"] for f in b.facts() if "right now" in f["text"])
    assert knee in b.fading() and b.fading()[knee] > datetime.now(timezone.utc)  # taken into this memory just now: not retired on the first Dreaming pass
    assert b.fade_due() == []
    dune = next(f["id"] for f in b.facts() if "Dune" in f["text"])
    assert dune not in b.fading()


@pytest.mark.parametrize("text", ["", "# just some notes\n- Has a dog.\n", "<!-- another-format 1 -->", None, 5])
def test_a_file_that_is_not_an_export_is_refused_and_nothing_is_written(pair, text):
    _, b = pair
    with pytest.raises(InvalidFact):
        md.restore_markdown(b, text)
    assert b.facts() == []


def test_damaged_lines_are_reported_and_skipped_one_by_one(pair):
    a, b = pair
    a.add_manual("Has a dog named Hog.", "api")
    good = md.export_markdown(a)
    bad = good + (
        "- No record here\n"
        "- Broken record <!-- diya {not json} -->\n"
        '- Wrong status <!-- diya {"status":"rejected","person":null} -->\n'
        '- Untidy   spaces <!-- diya {"status":"accepted","person":null} -->\n'
        '- Bad person <!-- diya {"status":"accepted","person":"' + "x" * 80 + '"} -->\n'
        '- Fine one <!-- diya {"status":"accepted","person":null,"created":"2026-02-03T04:05:06+00:00","by":"nonsense","said":-4,"message":true} -->\n'
    )
    restored, already, problems = md.restore_markdown(b, bad)
    assert restored == 2 and already == 0 and len(problems) == 5 and all(p.startswith("line ") for p in problems)
    fine = next(f for f in b.facts() if f["text"] == "Fine one")
    detail = b.events(fine["id"])[0][3]
    assert '"originally": "you"' in detail and '"said_again": 0' in detail and '"message": null' in detail  # nonsense values become harmless ones


def test_a_date_in_the_future_is_not_believed_and_a_date_without_a_zone_is_taken_as_utc(pair):
    _, b = pair
    future = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
    text = (
        "<!-- diya-memory-markdown 1 · exported now -->\n"
        f'- From the future <!-- diya {{"status":"accepted","person":null,"created":"{future}"}} -->\n'
        '- No zone <!-- diya {"status":"accepted","person":null,"created":"2026-03-04T05:06:07"} -->\n'
        '- Garbage date <!-- diya {"status":"accepted","person":null,"created":"yesterday-ish"} -->\n'
    )
    assert md.restore_markdown(b, text)[0] == 3
    made = {f["text"]: f["created_at"] for f in b.facts()}
    now = datetime.now(timezone.utc)
    assert datetime.fromisoformat(made["From the future"]) <= now and datetime.fromisoformat(made["Garbage date"]) <= now
    assert made["No zone"] == "2026-03-04T05:06:07+00:00"


def test_a_fact_whose_words_look_like_the_file_format_still_round_trips(pair):
    a, b = pair
    odd = "Wrote <!-- diya {\"status\":\"retired\"} --> in a note and uses --> arrows."
    a.add_manual(odd, "api")
    text = md.export_markdown(a)
    assert md.restore_markdown(b, text) == (1, 0, [])
    assert b.facts()[0]["text"] == odd and b.facts()[0]["status"] == "accepted"


def test_a_name_or_flag_with_angle_brackets_cannot_close_the_comment():
    meta = md._json({"person": "A --> B <!-- C", "flags": ["x-->y"]})
    assert "-->" not in meta and "<" not in meta and ">" not in meta


def test_a_restore_of_far_too_many_facts_is_refused(pair):
    _, b = pair
    line = '- Fact {n} <!-- diya {{"status":"accepted","person":null}} -->\n'
    text = "<!-- diya-memory-markdown 1 · exported now -->\n" + "".join(line.format(n=f"number {i}") for i in range(md.MAX_ITEMS + 1))
    with pytest.raises(InvalidFact):
        md.restore_markdown(b, text)
    assert b.facts() == []


# ---- the command line --------------------------------------------------------------------------------------------------


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


def test_the_command_line_writes_a_file_once_and_restores_from_it(config, tmp_path):
    Memory(Store(config.db_path)).add_manual("Has a dog named Hog.", "cli")
    target = tmp_path / "memory.md"
    code, out, err = review(config, "export-markdown", str(target))
    assert code == 0 and "It is a copy; the database is unchanged." in out and target.read_text(encoding="utf-8").startswith("# What Diya remembers")
    assert b"\r\n" not in target.read_bytes()  # LF only, like every text file this project writes
    code, out, err = review(config, "export-markdown", str(target))
    assert code == diya_review.EXIT_REFUSED and "already exists" in err
    assert review(config, "export-markdown", str(target), "--force")[0] == 0
    other = dataclasses.replace(config, db_path=str(tmp_path / "other.db"))
    code, out, err = review(other, "restore-markdown", str(target))
    assert code == 0 and "Restored 1 fact; 0 were already here." in out
    code, out, err = review(other, "restore-markdown", str(target))
    assert code == 0 and "Restored 0 facts; 1 was already here." in out


def test_the_command_line_says_so_when_the_file_cannot_be_read_or_is_not_an_export(config, tmp_path):
    code, out, err = review(config, "restore-markdown", str(tmp_path / "missing.md"))
    assert code == diya_review.EXIT_USAGE and "could not read" in err
    plain = tmp_path / "notes.md"
    plain.write_text("- Has a dog.\n", encoding="utf-8")
    code, out, err = review(config, "restore-markdown", str(plain))
    assert code == diya_review.EXIT_REFUSED and "not a Diya memory export" in err
    assert Memory(Store(config.db_path)).facts() == []


def test_the_command_line_can_show_the_copy_on_the_screen(config):
    Memory(Store(config.db_path)).add_manual("Has a dog named Hog.", "cli")
    code, out, err = review(config, "export-markdown")
    assert code == 0 and "- Has a dog named Hog. <!-- diya " in out
