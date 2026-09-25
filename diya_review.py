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
    python diya_review.py verify            check the store is consistent

Commands, not prompts, so it can be scripted and tested. No model and no network: the checks are plain
code. Nothing the model has not been told changes until you accept a fact -- and until the switch (unit 5)
even an accepted fact is not yet given to the model.

Everything read back from the database is printed through printable(): it is model output, or something
someone typed or pasted, and an escape sequence in it must not be able to rewrite what the screen says.
"""
from __future__ import annotations

import argparse
import sys

import diya_config
import diya_memory
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


def cmd_list(memory, config, args, out):
    facts = memory.facts(None if args.status == "all" else args.status)
    print(_usage_line(memory), file=out)
    if not facts:
        print(f"No {args.status} facts." if args.status != "all" else "No facts yet.", file=out)
        return EXIT_OK
    for fact in facts:
        print(f"{fact['id']:>4}  {fact['status']:<9}  {printable(fact['text'])}", file=out)
        if fact["flags"]:
            print(f"      flags: {', '.join(flag_short(f) for f in fact['flags'])}", file=out)
    return EXIT_OK


def cmd_show(memory, config, args, out):
    fact = memory.get(args.id)
    print(f"Fact {fact['id']}: {fact['status']} ({fact['source'].replace('_', ' ')})", file=out)
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


def cmd_import_profile(memory, config, args, out):
    result = diya_memory.import_legacy_profile(memory, config, actor="import")
    print(f"Imported {result.imported} facts from {printable(config.profile_path)}; {result.already} were imported before, "
          f"{result.duplicates} repeat another. The file was not changed.", file=out)
    if result.over_budget:
        print(f"That is {result.chars_used} characters, over the {diya_memory.MAX_PROFILE_CHARS} limit: nothing new can be "
              "accepted until some are retired.", file=out)
    print(_usage_line(memory), file=out)
    return EXIT_OK


def cmd_verify(memory, config, args, out):
    problems = memory.verify_integrity()
    if not problems:
        print("Memory is consistent.", file=out)
        return EXIT_OK
    for problem in problems:
        print(f"PROBLEM: {printable(problem)}", file=out)
    return EXIT_REFUSED


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
    commands.add_parser("verify", help="check the store is consistent").set_defaults(run=cmd_verify)
    return parser


def main(argv=None, config=None, out=None, err=None):
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
    memory = Memory(Store(config.db_path))
    try:
        return args.run(memory, config, args, out)
    except SourceUnreadable as exc:
        print(f"diya_review: {printable(exc)}", file=err)
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
