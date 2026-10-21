"""Review what Dreaming has staged, from the command line (docs/STAGE2_DESIGN.md, D6 and unit 4).

    python diya_review.py ingest            copy newly staged facts in as candidates, and run the checks
    python diya_review.py list [status]     candidates (the default), or accepted / rejected / retired / all
    python diya_review.py show ID           one fact: its flags, the messages it came from, its history
    python diya_review.py accept ID         a candidate becomes something the model is told
    python diya_review.py reject ID         ...or is turned down (reopen ID undoes that)
    python diya_review.py retire ID         an accepted fact stops being told (restore ID undoes that)
    python diya_review.py edit ID TEXT...   reword a candidate before deciding on it
    python diya_review.py add TEXT...       a fact you type yourself: it goes in already accepted
    python diya_review.py export            the accepted facts, as the old user_profile.txt held them
    python diya_review.py import-profile    take the old user_profile.txt in (the file is never changed)
    python diya_review.py export-markdown [PATH]   a Markdown copy of memory (docs/MARKDOWN_MEMORY_DESIGN.md)
    python diya_review.py restore-markdown PATH    bring back what a Markdown copy holds and memory does not
    python diya_review.py export-repo FOLDER       memory as an Agent Memory Repo: MEMORY.md + one note per person (docs/MEMORY_REPO_DESIGN.md)
    python diya_review.py as-of DAY...      what was remembered at the end of a past day, and what changed since (docs/TIME_DESIGN.md)
    python diya_review.py verify            check the store is consistent
    python diya_review.py judge [ID...]     ask the local model for a second opinion on candidates (advisory)
    python diya_review.py merge FROM [INTO] move every fact about FROM onto INTO (default: you)

Commands, not prompts, so it can be scripted and tested. Only `judge` uses the model, and only when you run
it: everything else is plain code and touches no network. The model is told a fact only once you accept it.
`judge` records its answer as a flag beside the fact; it never accepts, rejects or edits anything.

Accepted facts are listed grouped by who they are about (docs/PERSON_MEMORY_DESIGN.md, unit M3): "You" first,
then each named person alphabetically. Every other listing stays one flat list in id order, with a fact's
person shown in brackets when it has one, since a reviewer deciding a candidate needs to see who it names.

Everything read back from the database is printed through printable(): it is model output, or something
someone typed or pasted, and an escape sequence in it must not be able to rewrite what the screen says.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import diya_config
import diya_memory
import diya_verifier
from diya_db import Store
from diya_memory import STATUSES, FactError, Memory, SourceUnreadable, flag_long, flag_short, normalise_fact, printable

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
SOURCE_CHARS = 300  # how much of a source message is shown


def _usage_line(memory):
    counts = memory.counts()
    used = len(memory.render())
    names = {"candidate": "candidates", "accepted": "accepted", "rejected": "rejected", "retired": "retired"}
    parts = ", ".join(f"{counts[s]} {names[s]}" for s in STATUSES)
    return f"Memory: {used} of {diya_memory.MAX_PROFILE_CHARS} characters used. {parts}."


def _refresh(memory):
    """The checks depend on the other facts, so they are re-run after anything that changes one."""
    memory.run_checks("cli")


# ---- commands: each takes (memory, config, args, out) and returns an exit code ----

def cmd_ingest(memory, config, args, out):
    report = diya_memory.ingest_queue(memory, config, actor="cli")
    checked, changed = memory.run_checks("cli")
    print(f"Read {report.records} staged records: {report.new} new candidates, {report.already} already known, "
          f"{report.skipped} lines with nothing to keep" + (f", {report.bad_records} records with no fact list" if report.bad_records else "") + ".", file=out)
    print(f"Checked {checked} candidates; {changed} changed.", file=out)
    print(_usage_line(memory), file=out)
    return EXIT_OK


def _fact_line(fact, *, show_person, indent=""):
    line = f"{indent}{fact['id']:>4}  {fact['status']:<9}  {printable(fact['text'])}"
    if show_person and fact["person"] is not None:
        line += f"  [{printable(fact['person'])}]"
    return line


def _print_fact(fact, out, *, show_person, indent=""):
    print(_fact_line(fact, show_person=show_person, indent=indent), file=out)
    if fact["flags"]:
        print(f"{indent}      flags: {', '.join(flag_short(f) for f in fact['flags'])}", file=out)


def _print_grouped_by_person(facts, out):
    """Accepted facts only (docs/PERSON_MEMORY_DESIGN.md, D5): "You" first, then each named person
    Dreaming or a reviewer has tagged, alphabetically. The heading already says who, so the bracket
    tag `_print_fact` would otherwise add is left off here -- it would just repeat the heading."""
    by_person = {}
    for fact in facts:
        by_person.setdefault(fact["person"], []).append(fact)
    for name in [None] + sorted((n for n in by_person if n is not None), key=str.casefold):
        group = by_person.get(name)
        if not group:
            continue
        label = "You" if name is None else printable(name)
        print(f"{label} ({len(group)}):", file=out)
        for fact in group:
            _print_fact(fact, out, show_person=False, indent="  ")


def cmd_list(memory, config, args, out):
    facts = memory.facts(None if args.status == "all" else args.status)
    print(_usage_line(memory), file=out)
    if not facts:
        print(f"No {args.status} facts." if args.status != "all" else "No facts yet.", file=out)
        return EXIT_OK
    if args.status == "accepted":
        _print_grouped_by_person(facts, out)
    else:
        for fact in facts:
            _print_fact(fact, out, show_person=True)
    return EXIT_OK


def cmd_show(memory, config, args, out):
    fact = memory.get(args.id)
    print(f"Fact {fact['id']}: {fact['status']} ({fact['source'].replace('_', ' ')})", file=out)
    if fact["person"] is not None:
        print(f"  about:   {printable(fact['person'])}", file=out)
    print(f"  text:    {printable(fact['text'])}", file=out)
    if fact["raw"] is not None:
        print(f"  staged:  {printable(fact['raw'], 300)}", file=out)
    if fact["model"] is not None:
        print(f"  by:      {printable(fact['model'])}, staged {printable(fact['extracted_at'])}", file=out)
    for flag in fact["flags"]:
        print(f"  flag:    {flag_long(memory, flag)}", file=out)
    if fact["batch_first"] is not None:
        shown = [m for m in memory.store.get_messages_between(fact["batch_first"], fact["batch_last"]) if m["role"] == "user"]
        print(f"  extracted from your messages {fact['batch_first']} to {fact['batch_last']} (the ones the model was shown):", file=out)
        if not shown:
            print("    (none of them are in the database any more)", file=out)
        for message in shown:
            print(f"    [{message['id']}] (chat {message['thread_id']}) {printable(message['content'], SOURCE_CHARS)}", file=out)
    print("  history:", file=out)
    for event, actor, at, detail in memory.events(fact["id"]):
        print(f"    {printable(at)}  {printable(event)} by {printable(actor)}" + (f"  {printable(detail, 200)}" if detail else ""), file=out)
    return EXIT_OK


_DECISIONS = {"accept": "accepted", "reject": "rejected", "reopen": "reopened", "retire": "retired", "restore": "restored"}


def cmd_decide(memory, config, args, out):
    memory.decide(args.id, args.command, "cli")
    _refresh(memory)
    print(f"Fact {args.id} {_DECISIONS[args.command]}. " + _usage_line(memory), file=out)
    return EXIT_OK


def _typed(words):
    fact = normalise_fact(" ".join(words))
    if fact is None:
        raise FactError("there is nothing left of that text once it is cleaned up")
    return fact.text


def cmd_edit(memory, config, args, out):
    memory.edit(args.id, _typed(args.text), "cli")
    _refresh(memory)
    print(f"Fact {args.id} reworded.", file=out)
    return EXIT_OK


def cmd_add(memory, config, args, out):
    fact_id = memory.add_manual(_typed(args.text), "cli")
    _refresh(memory)
    print(f"Added as fact {fact_id}, already accepted. " + _usage_line(memory), file=out)
    return EXIT_OK


def cmd_export(memory, config, args, out):
    text = memory.render()
    if text:
        print(text, file=out)
    return EXIT_OK


def cmd_as_of(memory, config, args, out):
    import diya_provenance
    import diya_when

    day = diya_when.past_day(" ".join(args.day), datetime.now().astimezone().date())
    if day is None:
        print("as-of: say a day that has already come: 2026-10-12, 12 Oct, yesterday, last Friday, last week", file=out)
        return EXIT_USAGE
    print(diya_provenance.as_of_answer(memory, day, ""), file=out)
    return EXIT_OK


def cmd_export_markdown(memory, config, args, out):
    """The Markdown copy of memory (diya_markdown.py): to a file when a path is given (never over an existing file without --force), else to the screen."""
    import diya_markdown

    text = diya_markdown.export_markdown(memory)
    if not args.path:
        out.write(text)
        return EXIT_OK
    import os

    if os.path.exists(args.path) and not args.force:
        raise FactError(f"{args.path} already exists; nothing was written (--force replaces it)")
    with open(args.path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print(f"Wrote {printable(args.path)}: {text.count(chr(10))} lines. It is a copy; the database is unchanged.", file=out)
    return EXIT_OK


def cmd_export_repo(memory, config, args, out):
    """Memory as an Agent Memory Repo (diya_memory_repo.py): a new folder of Markdown notes with a short MEMORY.md. A copy for reading; nothing in the database changes."""
    import diya_memory_repo

    try:
        written = diya_memory_repo.export_repo(memory, args.folder)
    except diya_memory_repo.RepoError as exc:
        raise FactError(str(exc)) from exc
    print(f"Wrote {len(written)} file{'' if len(written) == 1 else 's'} to {printable(args.folder)}: {', '.join(written)}. It is a copy; the database is unchanged.", file=out)
    return EXIT_OK


def cmd_restore_markdown(memory, config, args, out):
    """Bring back facts from a Markdown copy: only what is not already there; nothing existing is changed."""
    import diya_markdown

    try:
        with open(args.path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise SourceUnreadable(f"could not read {args.path} ({exc})") from exc
    restored, already, problems = diya_markdown.restore_markdown(memory, text)
    print(f"Restored {restored} fact{'' if restored == 1 else 's'}; {already} {'was' if already == 1 else 'were'} already here. Nothing that was here was changed.", file=out)
    for problem in problems[:20]:
        print(f"  {printable(problem, 120)}", file=out)
    if len(problems) > 20:
        print(f"  ... and {len(problems) - 20} more lines could not be read", file=out)
    print(_usage_line(memory), file=out)
    return EXIT_OK


def cmd_import_profile(memory, config, args, out):
    result = diya_memory.import_legacy_profile(memory, config, actor="import")
    print(f"Imported {result.imported} facts from {printable(config.profile_path)}; {result.already} were imported before, "
          f"{result.duplicates} repeat another. The file was not changed.", file=out)
    if result.over_budget:
        print(f"That is {result.chars_used} characters, over the {diya_memory.MAX_PROFILE_CHARS} limit: nothing new can be "
              "accepted until some are retired.", file=out)
    print(_usage_line(memory), file=out)
    return EXIT_OK


def cmd_merge(memory, config, args, out):
    """Move every fact currently about FROM onto INTO (docs/PERSON_MEMORY_DESIGN.md, D3): a person-level
    action, not automatic, and FROM's own row is never deleted -- a name left with 0 facts is the record
    that a merge happened. INTO left off means "you": the same as passing "self"."""
    moved = memory.merge_people(args.from_name, args.into_name, "cli")
    target = "you" if args.into_name is None else printable(args.into_name)
    print(f"Moved {moved} fact{'' if moved == 1 else 's'} from {printable(args.from_name)} to {target}.", file=out)
    return EXIT_OK


def cmd_verify(memory, config, args, out):
    problems = memory.verify_integrity()
    if not problems:
        print("Memory is consistent.", file=out)
        return EXIT_OK
    for problem in problems:
        print(f"PROBLEM: {printable(problem)}", file=out)
    return EXIT_REFUSED


def cmd_judge(memory, config, args, out):
    """Ask the local model whether the messages a candidate came from support it. `args.client` is the model
    client (main() passes one in tests; otherwise it is made here, so nothing else needs the openai package)."""
    client = args.client
    if client is None:
        from openai import OpenAI

        client = OpenAI(base_url=config.ollama_url, api_key="ollama", timeout=120)
    asked = diya_verifier.judge(memory, client, config.model, ids=args.ids or None, again=args.again, actor="cli")
    for fact_id, verdict in asked:
        print(f"Fact {fact_id}: {verdict}  {printable(memory.get(fact_id)['text'], 100)}", file=out)
    print(f"Asked about {len(asked)} fact{'' if len(asked) == 1 else 's'}. This is a second opinion from the same small model: "
          "it can be wrong, and it never changes anything by itself.", file=out)
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(prog="diya_review.py", description="Review the facts Dreaming has staged.")
    commands = parser.add_subparsers(dest="command", metavar="command", required=True)
    commands.add_parser("ingest", help="copy newly staged facts in as candidates, and run the checks").set_defaults(run=cmd_ingest)
    listing = commands.add_parser("list", help="list facts (candidates unless you say otherwise)")
    listing.add_argument("status", nargs="?", default="candidate", choices=STATUSES + ("all",))
    listing.set_defaults(run=cmd_list)
    show = commands.add_parser("show", help="one fact, with the messages it came from")
    show.add_argument("id", type=int)
    show.set_defaults(run=cmd_show)
    for name, text in (("accept", "a candidate becomes something the model is told"), ("reject", "turn a candidate down"),
                       ("reopen", "put a rejected fact back as a candidate"), ("retire", "an accepted fact stops being told"),
                       ("restore", "bring a retired fact back")):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("id", type=int)
        sub.set_defaults(run=cmd_decide)
    edit = commands.add_parser("edit", help="reword a candidate")
    edit.add_argument("id", type=int)
    edit.add_argument("text", nargs="+")
    edit.set_defaults(run=cmd_edit)
    add = commands.add_parser("add", help="a fact you type yourself (goes in already accepted)")
    add.add_argument("text", nargs="+")
    add.set_defaults(run=cmd_add)
    commands.add_parser("export", help="the accepted facts, in the old user_profile.txt format").set_defaults(run=cmd_export)
    commands.add_parser("import-profile", help="take the old user_profile.txt in; the file is never changed").set_defaults(run=cmd_import_profile)
    export_md = commands.add_parser("export-markdown", help="a Markdown copy of memory to read or keep in Git (a copy: the database stays the truth)")
    export_md.add_argument("path", nargs="?", default=None, help="a file to write (default: the screen)")
    export_md.add_argument("--force", action="store_true", help="replace the file if it exists")
    export_md.set_defaults(run=cmd_export_markdown)
    export_repo = commands.add_parser("export-repo", help="memory as an Agent Memory Repo: a new folder of Markdown notes (MEMORY.md + one note per person) to read or keep in Git")
    export_repo.add_argument("folder", help="a folder that does not exist yet (or is empty)")
    export_repo.set_defaults(run=cmd_export_repo)
    restore_md = commands.add_parser("restore-markdown", help="bring back facts from a Markdown copy; only what is not here already, nothing is changed")
    restore_md.add_argument("path")
    restore_md.set_defaults(run=cmd_restore_markdown)
    as_of = commands.add_parser("as-of", help="what was remembered at the end of a past day, and what has changed since (replayed from the history, no model)")
    as_of.add_argument("day", nargs="+", help="a past day: 2026-10-12, 12 Oct, yesterday, last Friday, last week")
    as_of.set_defaults(run=cmd_as_of)
    commands.add_parser("verify", help="check the store is consistent").set_defaults(run=cmd_verify)
    judge = commands.add_parser("judge", help="ask the local model for a second opinion on candidates (advisory only)")
    judge.add_argument("ids", nargs="*", type=int, help="only these candidates (default: all of them)")
    judge.add_argument("--again", action="store_true", help="ask again about a candidate that already has an answer")
    judge.set_defaults(run=cmd_judge)
    merge = commands.add_parser("merge", help="move every fact about one name onto another (or onto you)")
    merge.add_argument("from_name", metavar="FROM")
    merge.add_argument("into_name", metavar="INTO", nargs="?", default=None)
    merge.set_defaults(run=cmd_merge)
    return parser


def main(argv=None, config=None, out=None, err=None, client=None):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse has already said what was wrong; a --help is a success
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        config = config or diya_config.load_config()
    except diya_config.ConfigError as exc:
        print(f"diya_review: {exc}", file=err)
        return EXIT_USAGE
    import diya_backup

    if not diya_backup.guard_migration(config, say=lambda line: print(f"diya_review: {line}", file=err)):
        return EXIT_USAGE
    memory = diya_memory.open_memory(Store(config.db_path), config)
    args.client = client
    try:
        return args.run(memory, config, args, out)
    except SourceUnreadable as exc:
        print(f"diya_review: {printable(exc)}", file=err)
        return EXIT_USAGE
    except diya_verifier.ModelUnavailable as exc:
        kept = len(exc.asked)
        print(f"diya_review: could not reach the model ({printable(exc, 200)}). "
              f"{kept} answer{'' if kept == 1 else 's'} obtained before that {'was' if kept == 1 else 'were'} kept; nothing else changed.", file=err)
        return EXIT_USAGE
    except FactError as exc:
        print(f"diya_review: {printable(exc)}", file=err)
        return EXIT_REFUSED


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # A Windows console is not UTF-8 by default, and would turn every line break into CRLF: an
            # `export > profile.txt` must be LF-only, like every text file this project writes.
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.exit(main())
