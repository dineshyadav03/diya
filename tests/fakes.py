"""A scripted stand-in for the OpenAI-compatible client Ollama exposes -- no network, no model."""
from types import SimpleNamespace


def text_reply(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
    )


def tool_reply(name, arguments="{}", call_id="call_1"):
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]))])


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

    def _create(self, model, messages, tools=None):
        if self._chat_error:
            raise self._chat_error
        self.chat_calls.append({"model": model, "messages": list(messages), "tools": tools})
        return self.replies.pop(0)

    def _embed(self, model, input):
        if self._embed_error:
            raise self._embed_error
        self.embed_calls.append({"model": model, "input": input})
        return SimpleNamespace(data=[SimpleNamespace(embedding=keyword_embedding(input))])
