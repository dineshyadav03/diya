"""A scripted stand-in for the OpenAI-compatible client Ollama exposes -- no network, no model."""
from types import SimpleNamespace


def text_reply(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
    )


def tool_reply(name, arguments="{}", call_id="call_1"):
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])


def tool_calls_reply(*calls):
    """One model message that makes several tool calls in a row: each call is (name, arguments_json)."""
    made = [
        SimpleNamespace(id=f"call_{n}", function=SimpleNamespace(name=name, arguments=arguments))
        for n, (name, arguments) in enumerate(calls, 1)
    ]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=made))])


def task_kind(*, connector=None, executed=None, reply="created task 1", raises=None, tool=True, name="add_task",
              tool_name="propose_add_task"):
    """A fake kind of action (docs/ACTIONS_DESIGN.md): "add a task", with a title and an optional due phrase. Its
    effect is only to append what it was given to `executed` (when a list is passed), so a test can say whether
    anything was ever performed. `tool=False` makes one the model cannot propose at all."""
    from diya_actions import ActionKind, InvalidArgs  # imported here: tests that never need it don't load it

    def validate(args):
        extra = sorted(set(args) - {"title", "due"})
        if extra:
            raise InvalidArgs(f"a task has no {', '.join(extra)}")
        if not isinstance(args.get("title"), str):
            raise InvalidArgs("a task needs a title")
        if len(args["title"]) > 100:
            raise InvalidArgs("a title is at most 100 characters")
        if "due" in args and not (args["due"] is None or isinstance(args["due"], str)):
            raise InvalidArgs("due must be words, like 'tomorrow'")

    def render(args):
        return f"Add the task {args['title']!r}" + (f", due {args['due']}" if args.get("due") else "")

    def execute(config, args):
        if executed is not None:
            executed.append(dict(args))
        if raises is not None:
            raise raises
        return reply

    spec = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": "Propose adding a task to the owner's to-do list. Only proposes: the owner approves it.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "due": {"type": "string"}},
                "required": ["title"],
            },
        },
    } if tool else None
    return ActionKind(name, "Add a task", connector, validate, render, execute, spec)


def keyword_embedding(text):
    """Deterministic 4-d "embedding": which topic words the text mentions. Enough for the
    nearest-note lookup to be predictable without a real embedding model."""
    lowered = text.lower()
    return [float(w in lowered) for w in ("dentist", "guitar", "garden", "laptop")]


class FakeClient:
    """Replays `replies` in order for chat completions and records every call made."""

    def __init__(self, replies=(), embed_error=None, chat_error=None):
        self.replies = list(replies)
        self.chat_calls = []
        self.embed_calls = []
        self._embed_error = embed_error
        self._chat_error = chat_error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _create(self, model, messages, tools=None, **options):
        if self._chat_error:
            raise self._chat_error
        self.chat_calls.append({"model": model, "messages": list(messages), "tools": tools, "options": options})
        return self.replies.pop(0)

    def _embed(self, model, input):
        if self._embed_error:
            raise self._embed_error
        self.embed_calls.append({"model": model, "input": input})
        return SimpleNamespace(data=[SimpleNamespace(embedding=keyword_embedding(input))])
