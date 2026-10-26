"""A scripted stand-in for the OpenAI-compatible client Ollama exposes -- no network, no model."""
import re
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
              tool_name="propose_add_task", asked=None, prepare=None, auto_ok=None):
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
    return ActionKind(name, "Add a task", connector, validate, render, execute, spec, asked, prepare, auto_ok)


def keyword_embedding(text):
    """Deterministic 4-d "embedding": which topic words the text mentions. Enough for the
    nearest-note lookup to be predictable without a real embedding model."""
    lowered = text.lower()
    return [float(w in lowered) for w in ("dentist", "guitar", "garden", "laptop")]


def stream_of(reply):
    """The chunks an OpenAI-style streaming call gives for a scripted reply: a text reply a word at a time; a tool call as its name first and its arguments in two pieces; and a last chunk
    with no choices at all, as a usage chunk is."""
    message = reply.choices[0].message

    def chunk(content=None, tool_calls=None):
        return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content, tool_calls=tool_calls))])

    chunks = [chunk(content=piece) for piece in re.findall(r"\S+\s*", message.content or "")]
    for index, call in enumerate(message.tool_calls or ()):
        arguments = call.function.arguments
        half = len(arguments) // 2
        chunks.append(chunk(tool_calls=[SimpleNamespace(index=index, id=call.id, function=SimpleNamespace(name=call.function.name, arguments=""))]))
        chunks.append(chunk(tool_calls=[SimpleNamespace(index=index, id=None, function=SimpleNamespace(name=None, arguments=arguments[:half]))]))
        chunks.append(chunk(tool_calls=[SimpleNamespace(index=index, id=None, function=SimpleNamespace(name=None, arguments=arguments[half:]))]))
    chunks.append(SimpleNamespace(choices=[]))
    return chunks


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
        reply = self.replies.pop(0)
        return iter(stream_of(reply)) if options.get("stream") else reply

    def _embed(self, model, input):
        if self._embed_error:
            raise self._embed_error
        self.embed_calls.append({"model": model, "input": input})
        return SimpleNamespace(data=[SimpleNamespace(embedding=keyword_embedding(input))])


class ByQuestionClient(FakeClient):
    """A scripted stand-in for the model that answers each KIND of question from its own list, whatever order they arrive in: the extraction prompt
    Dreaming and live capture send (`extraction`), "is this private?" (`privacy`, OK to every one unless a list is given), "does this replace a
    known fact?" (`replace`, NONE to every one) and everything else, an ordinary chat turn (`chat`, "Noted." to every one). A list that runs
    out is a model that cannot answer: the call raises, as an unreachable model does."""

    def __init__(self, extraction=(), privacy=None, replace=None, chat=None):
        super().__init__()
        self.lists = {
            "extraction": [text_reply(r) for r in extraction],
            "privacy": [text_reply("OK")] * 40 if privacy is None else [text_reply(r) for r in privacy],
            "replace": [text_reply("NONE")] * 40 if replace is None else [text_reply(r) for r in replace],
            "chat": [text_reply("Noted.")] * 40 if chat is None else [text_reply(r) for r in chat],
        }

    def kind_of(self, messages):
        first = messages[0]["content"] if messages and isinstance(messages[0].get("content"), str) else ""
        if first.startswith("You are a privacy filter"):
            return "privacy"
        if "Known facts:" in first and first.startswith("Below are facts already known"):
            return "replace"
        if first.startswith("Below are things a user said recently"):
            return "extraction"
        return "chat"

    def _create(self, model, messages, tools=None, **options):
        self.chat_calls.append({"model": model, "messages": list(messages), "tools": tools, "options": options, "kind": self.kind_of(messages)})
        return self.lists[self.kind_of(messages)].pop(0)

    def asked(self, kind):
        """The calls of one kind, in order."""
        return [call for call in self.chat_calls if call["kind"] == kind]
