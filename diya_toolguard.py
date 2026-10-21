"""Two safety nets for the tool loop: a nudge out of repeated identical tool calls, and a limit on how much of one tool result the model is given (added 2026-10-21).

The model is a 4B one on a 16,384-token window. Two failures follow from that and are cheap to prevent in code:
* **A loop.** It calls the same tool with the same arguments again and again without using what came back, until the eight-round cap ends the turn with "something's likely stuck". After the third and the fifth
  identical call in a row it is told, inside that tool's result, that it is repeating itself and to use what it has or do something else.
* **An oversized result.** One tool result (a long page, a long list) can fill the window. A result over THRESHOLD_CHARS is cut to its beginning and its end with a marker where the middle was, so the model
  still sees how it starts and how it ends, and the window is not eaten.

Both are from the design of DeepSeek's harness (MIT; harness/LICENSE; THIRD_PARTY_NOTICES.md): its repeat-tool reminder (thresholds 3, 5, 8, a gentle then a detailed reminder, arguments compared in a canonical
order) and its tool-result pruner (over 8,192 characters: the first 4,096, a marker, the last 1,024). Rewritten here in Python with Diya's own wording and numbers; nothing else of that harness is used.
Importing this module has no side effects.
"""
from __future__ import annotations

import json

THRESHOLD_CHARS = 8192  # a tool result longer than this is cut
HEAD_CHARS = 4096
TAIL_CHARS = 1024
MARKER = "\n\n[... the middle of this result was left out to keep it short ...]\n\n"
REPEAT_THRESHOLDS = (3, 5)  # the Nth identical call in a row is reminded (the turn is capped at 8 rounds)
ARGUMENT_CHARS = 300  # how much of the arguments the second reminder quotes


def prune(text):
    """`text` unchanged if it is short enough; otherwise its first HEAD_CHARS, the marker and its last TAIL_CHARS. Anything that is not text is returned as it is."""
    if not isinstance(text, str) or len(text) <= THRESHOLD_CHARS:
        return text
    return text[:HEAD_CHARS] + MARKER + text[-TAIL_CHARS:]


def _canonical(arguments):
    """The arguments as one text, the same for two calls that differ only in the order of the keys; the raw text if it is not JSON."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return arguments.strip()
    try:
        return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        return str(arguments)


class RepeatGuard:
    """Counts identical tool calls in a row within one turn and says when to remind the model. One per turn: `after(name, arguments)` is called after each call and returns a reminder to add to that call's
    result, or None."""

    def __init__(self, thresholds=REPEAT_THRESHOLDS):
        self.thresholds = tuple(thresholds)
        self._last = None
        self._count = 0

    def after(self, name, arguments):
        key = (str(name), _canonical(arguments))
        self._count = self._count + 1 if key == self._last else 1
        self._last = key
        if self._count not in self.thresholds:
            return None
        if self._count == self.thresholds[0]:
            return ("Note: you are repeating the exact same tool call with the same arguments. Read the result you already have before calling again; if the task is not done, "
                    "try something different, or answer with what you have.")
        shown = key[1] if len(key[1]) <= ARGUMENT_CHARS else key[1][:ARGUMENT_CHARS] + "..."
        return (f"Note: repeated tool call. Tool: {key[0]}. Calls in a row: {self._count}. Arguments: {shown}. These calls are not making progress. Do not call this tool with these exact "
                "arguments again: use the result you already have, do something different, or answer with what you have.")
