"""Decide what Diya proposed, from the command line (docs/ACTIONS_DESIGN.md, D8 and unit A3).

    python diya_actions_cli.py list [status]       what is waiting (the default), or any status, or all
    python diya_actions_cli.py show ID              one action: what it would do, where it came from, its history
    python diya_actions_cli.py approve ID [--yes]   approve exactly what is shown, then run it (asks first)
    python diya_actions_cli.py reject ID            turn a pending action down; it is never performed
    python diya_actions_cli.py resolve ID happened|did-not-happen [NOTE...]
                                                     record what you found for an action whose outcome is unknown
    python diya_actions_cli.py kinds                the kinds of action Diya can propose at all
    python diya_actions_cli.py check                check the store is consistent

The same rules as the Actions page (diya_actions.py's), by someone running a command on their own machine. `approve`
shows the action and asks before it does anything: what you approve is what was on the screen when you answered,
held to by the same hash the page uses, so an action changed in between is refused instead of run. `--yes` skips
the question, for a script; there is nothing here a model can call.

Everything read back from the database is printed through printable(): the arguments are the model's, and an
escape sequence in them must not be able to rewrite what the screen says.
"""
from __future__ import annotations

import argparse
import sys

import diya_actions
import diya_config
import diya_connector_tools
import diya_connectors
from diya_actions import STATUSES, ActionError, Actions
from diya_db import Store
from diya_memory import printable

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
SOURCE_CHARS = 300


def _shown(value):
    if value is None:
        return "(empty)"
    if value is True or value is False:
        return "yes" if value else "no"
    return printable(value)


def _line(action):
    line = f"{action['id']:>4}  {action['status']:<9}  {printable(action['summary'])}"
    if action["tainted"]:
        line += f"  [read first: {', '.join(printable(s) for s in action['taint_sources'])}]"
    return line


def _usage_line(actions):
    counts = actions.counts()
    parts = [f"{counts['pending']} waiting for you"]
    if counts["unknown"]:
        parts.append(f"{counts['unknown']} with an unknown outcome")
    parts.append(f"{sum(counts.values())} in all")
    return "Actions: " + ", ".join(parts) + "."


def _print_action(actions, action, out, *, source=None):
    kind = diya_actions.by_name(actions.kinds, action["kind"])
    print(f"Action {action['id']}: {action['status']}", file=out)
    print(f"  kind:     {printable(kind.label if kind else action['kind'])}", file=out)
    print(f"  would do: {printable(action['summary'])}", file=out)
    for name, value in action["args"].items():  # already in name order: stored in canonical form
        print(f"            {printable(name)}: {_shown(value)}", file=out)
    if action["tainted"]:
        print(f"  CAUTION:  Diya read from {', '.join(printable(s) for s in action['taint_sources'])} before proposing this. "
              "That text is not yours: check the details above are what you wanted.", file=out)
    if action["thread_id"] is not None:
        print(f"  chat:     thread {action['thread_id']}" + (f", message {action['message_id']}" if action["message_id"] is not None else ""), file=out)
    if source:
        print(f"  you said: {source}", file=out)
    print(f"  expires:  {printable(action['expires_at'])}", file=out)
    if action["decided_at"]:
        print(f"  decided:  {printable(action['decided_at'])}", file=out)
    if action["executed_at"]:
        print(f"  ran:      {printable(action['executed_at'])}", file=out)
    if action["result"] is not None:
        print(f"  result:   {printable(action['result'])}", file=out)


# ---- commands: each takes (actions, config, args, out, err, input_fn) and returns an exit code ----

def cmd_list(actions, config, args, out, err, input_fn):
    print(_usage_line(actions), file=out)
    found = actions.pending() if args.status == "pending" else actions.actions(None if args.status == "all" else args.status)
    if not found:
        if args.status == "pending":
            print("Nothing waiting for you.", file=out)
        elif args.status == "all":
            print("No actions yet.", file=out)
        else:
            print(f"No {args.status} actions.", file=out)
        return EXIT_OK
    for action in found:
        print(_line(action), file=out)
    return EXIT_OK


def cmd_show(actions, config, args, out, err, input_fn):
    action = actions.get(args.id)
    source = None
    if action["message_id"] is not None:
        messages = Store(config.db_path).get_messages_between(action["message_id"], action["message_id"])
        source = printable(messages[0]["content"], SOURCE_CHARS) if messages else None
    _print_action(actions, action, out, source=source)
    print("  history:", file=out)
    for event, actor, at, detail in actions.events(args.id):
        print(f"    {printable(at)}  {printable(actor):<6}  {printable(event)}" + (f"  {printable(detail, 200)}" if detail else ""), file=out)
    return EXIT_OK


def cmd_approve(actions, config, args, out, err, input_fn):
    shown = actions.get(args.id)  # what is on the screen now; the approval is bound to exactly this
    _print_action(actions, shown, out)
    if shown["status"] != "pending":
        print(f"diya_actions_cli: action {shown['id']} is {shown['status']}; only a pending action can be approved", file=err)
        return EXIT_REFUSED
    if not args.yes:
        try:
            answer = input_fn("Approve this and run it now? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Not approved. Nothing was done.", file=out)
            return EXIT_REFUSED
    actions.approve(args.id, shown["args_hash"], "cli")
    done = actions.run(args.id)
    print(f"Action {done['id']}: {done['status']}." + (f" {printable(done['result'])}" if done["result"] else ""), file=out)
    return EXIT_OK if done["status"] == "succeeded" else EXIT_REFUSED


def cmd_reject(actions, config, args, out, err, input_fn):
    done = actions.reject(args.id, "cli")
    print(f"Action {done['id']}: {done['status']}. It will not be done.", file=out)
    return EXIT_OK


def cmd_resolve(actions, config, args, out, err, input_fn):
    note = " ".join(args.note).strip() or None
    done = actions.resolve(args.id, args.outcome == "happened", "cli", note=note)
    print(f"Action {done['id']}: {done['status']}. {printable(done['result'])}", file=out)
    return EXIT_OK


def cmd_kinds(actions, config, args, out, err, input_fn):
    if not actions.kinds:
        print("No kind of action is registered: Diya cannot propose any change to anything yet.", file=out)
        return EXIT_OK
    for kind in actions.kinds:
        if kind.tool is None:
            state = "cannot be proposed by the model"
        elif kind.connector is None or diya_connectors.is_connected(config, kind.connector):
            state = "can be proposed"
        else:
            state = f"needs {printable(kind.connector)} connected"
        print(f"{printable(kind.name):<24} {printable(kind.label)}: {state}", file=out)
    return EXIT_OK


def cmd_check(actions, config, args, out, err, input_fn):
    problems = actions.verify_integrity()
    if not problems:
        print("The action store is consistent.", file=out)
        return EXIT_OK
    for problem in problems:
        print(printable(problem), file=out)
    print(f"{len(problems)} problem{'' if len(problems) == 1 else 's'} found.", file=out)
    return EXIT_REFUSED


def build_parser():
    parser = argparse.ArgumentParser(prog="diya_actions_cli.py", description="Decide what Diya proposed.")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="what is waiting for you (default), or any status, or all")
    listing.add_argument("status", nargs="?", default="pending", choices=("all",) + STATUSES)
    listing.set_defaults(run=cmd_list)
    show = commands.add_parser("show", help="one action in full")
    show.add_argument("id", type=int)
    show.set_defaults(run=cmd_show)
    approve = commands.add_parser("approve", help="approve exactly what is shown, then run it")
    approve.add_argument("id", type=int)
    approve.add_argument("--yes", action="store_true", help="do not ask first")
    approve.set_defaults(run=cmd_approve)
    reject = commands.add_parser("reject", help="turn a pending action down")
    reject.add_argument("id", type=int)
    reject.set_defaults(run=cmd_reject)
    resolve = commands.add_parser("resolve", help="record what happened to an action whose outcome is unknown")
    resolve.add_argument("id", type=int)
    resolve.add_argument("outcome", choices=("happened", "did-not-happen"))
    resolve.add_argument("note", nargs="*")
    resolve.set_defaults(run=cmd_resolve)
    commands.add_parser("kinds", help="the kinds of action Diya can propose").set_defaults(run=cmd_kinds)
    commands.add_parser("check", help="check the store is consistent").set_defaults(run=cmd_check)
    return parser


def main(argv=None, config=None, out=None, err=None, kinds=None, input_fn=input):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:  # argparse has already said what was wrong; a --help is a success
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    try:
        config = config or diya_config.load_config()
    except diya_config.ConfigError as exc:
        print(f"diya_actions_cli: {exc}", file=err)
        return EXIT_USAGE
    actions = Actions(Store(config.db_path), config, diya_connector_tools.real_action_kinds() if kinds is None else tuple(kinds))
    try:
        return args.run(actions, config, args, out, err, input_fn)
    except ActionError as exc:
        print(f"diya_actions_cli: {printable(exc)}", file=err)
        return EXIT_REFUSED


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    sys.exit(main())
