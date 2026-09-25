import fnmatch
import functools
import json
import os
import pathlib
import sys
import threading
import urllib.parse
import uuid

import httpx
from ddgs import DDGS
from openai import OpenAI

import diya_config
import diya_db
import diya_intent

WEATHER_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    95: "thunderstorm",
}


class OllamaUnavailable(RuntimeError):
    """Raised by Agent.warm_up() when the model server or the notes index can't be reached/built."""

    def __init__(self, base_url, cause):
        super().__init__(f"can't reach Ollama at {base_url} ({cause})")
        self.base_url = base_url
        self.cause = cause


# ---- Diya's default toolkit ----
# Tools that need no state live here as plain functions; the ones that need the
# model server (search_notes) or the database (reminders) are Agent methods.
def _is_secret_name(name):
    """True for anything list_files must never show, even from a directory it is allowed to list:
    dotfiles and dot-directories (.ssh, .git -- this alone already covers .env and .env.* too,
    since both start with "."), plus the two secret-shaped extensions .gitignore already treats as
    secrets everywhere else in this repo."""
    if name.startswith("."):
        return True
    return fnmatch.fnmatch(name, "*.pem") or fnmatch.fnmatch(name, "*.key")


def list_files(directory=".", roots=()):
    """List the files in `directory`, restricted to a configured set of allowed folders.

    `roots` is empty by default -- deny by default, not "look everywhere" -- so a direct call that
    forgets to pass it sees nothing, rather than the whole filesystem. Agent binds the real,
    configured roots (diya_config.resolved_files_roots) when it registers this as a tool.

    `directory` is resolved against each root in turn: os.path.join already leaves an *absolute*
    directory unchanged (so the same code handles both "a bare relative folder name under a root"
    and "an absolute path that happens to already be inside one"), and os.path.realpath -- not
    just normpath -- is what the containment check runs against, so a symlink inside a root that
    points outside it is caught the same way a plain ../ escape is (normpath resolves ".."
    textually; it has no idea a symlink exists). Secret-shaped entries are filtered out of the
    result even from a directory that is itself allowed.
    """
    for root in roots:
        real_root = os.path.realpath(root)
        candidate = os.path.realpath(os.path.join(root, directory))
        if pathlib.Path(candidate).is_relative_to(real_root):
            names = os.listdir(candidate)
            return "\n".join(name for name in names if not _is_secret_name(name))
    return f"Can't list '{directory}': outside the allowed folders."


NETWORK_TIMEOUT = 5.0  # seconds -- fail fast instead of hanging when there's no connection


class HostNotAllowed(RuntimeError):
    """_fetch refused a URL whose host isn't on the tool allowlist. No request was sent."""


def _request_host(url):
    """The host `url` points at, or None if it can't be read unambiguously. It is read by both
    urllib.parse (the check docs/STAGE1_DESIGN.md names) and httpx (the parser that will actually
    make the connection), and only accepted if the two agree: a URL the two would read
    differently (a leading space, a tab, no "//") is refused rather than trusted to one of them."""
    try:
        by_urllib = urllib.parse.urlsplit(url).hostname
        by_httpx = httpx.URL(url).host
    except (ValueError, httpx.InvalidURL):
        return None
    return by_urllib if by_urllib and by_urllib == by_httpx else None


def _fetch(url, params, timeout, allowed_hosts=diya_config.DEFAULT_TOOL_ALLOWED_HOSTS):
    """httpx.get, but only to a host on `allowed_hosts` -- checked before anything is sent.

    The allowlist is a positive list of external services: a loopback or private address, or the
    machine's own API, is refused like any other host that isn't on it. Redirects are not followed
    (httpx's default, which tests/test_tool_allowlist.py pins), so an allowed host can't hand the
    request on to one that isn't. `allowed_hosts` defaults to the two hosts get_weather uses, so a
    direct call with no allowlist still can't reach anywhere else.
    """
    host = _request_host(url)
    if host is None or host not in allowed_hosts:
        label = repr(host) if host else "that address"
        raise HostNotAllowed(f"{label} isn't an allowed destination for this tool")
    return httpx.get(url, params=params, timeout=timeout)


# The geocoding API doesn't reliably treat old/colonial city names as aliases of the
# current official name -- "Bangalore" alone can return only the wrong country's match,
# with nothing to disambiguate against. Normalize well-known cases before querying.
CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
}


def get_weather(location, allowed_hosts=diya_config.DEFAULT_TOOL_ALLOWED_HOSTS):
    location = CITY_ALIASES.get(location.strip().lower(), location)
    try:
        geo = _fetch(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": location, "count": 5},
            NETWORK_TIMEOUT,
            allowed_hosts,
        ).json()
        results = geo.get("results")
        if not results:
            return f"Couldn't find a location called '{location}'."

        # Prefer the most populous match -- avoids silently picking an obscure same-named place.
        best = max(results, key=lambda r: r.get("population", 0))

        weather = _fetch(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": best["latitude"],
                "longitude": best["longitude"],
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            NETWORK_TIMEOUT,
            allowed_hosts,
        ).json()["current"]
    except HostNotAllowed as exc:
        return f"Weather lookup blocked: {exc}."
    except httpx.TimeoutException:
        return "Couldn't reach the weather service -- no internet connection right now."
    except httpx.HTTPError as exc:
        return f"Weather lookup failed: {exc}"

    condition = WEATHER_CODES.get(weather["weather_code"], f"code {weather['weather_code']}")
    place = ", ".join(p for p in [best["name"], best.get("admin1"), best["country"]] if p)
    return (
        f"{place}: {weather['temperature_2m']}°C, {condition}, "
        f"wind {weather['wind_speed_10m']} km/h"
    )


# Known gap, on purpose: web_search is NOT covered by the tool allowlist. ddgs makes its own
# requests through primp (a Rust HTTP client this code neither imports nor can wrap), so there is
# nowhere here to check a destination, and "reach the open web on request" has no short list of
# hosts to allow anyway. docs/STAGE1_DESIGN.md section 4 records the options; tests/
# test_tool_allowlist.py pins the fact, so replacing ddgs is a deliberate, visible change.
def web_search(query):
    try:
        results = DDGS(timeout=NETWORK_TIMEOUT).text(query, max_results=3)
    except Exception:
        return "Couldn't reach the search engine -- no internet connection right now."
    if not results:
        return "No results found."
    return "\n".join(f"{r['title']}: {r['body']} ({r['href']})" for r in results)


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List the files in a directory you're allowed to see (a configured folder, not "
                "the user's whole computer)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "Folder path to list."}
                },
                "required": ["directory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": (
                "Search the user's personal notes and return the most relevant one. Use this "
                "whenever the user asks about something they previously wrote down, mentioned, or "
                "noted -- appointments, plans, tasks, or anything personal you wouldn't otherwise "
                "know. Do not say you lack access to their notes; call this tool instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search the notes for."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current real weather for a place. Always use this for weather questions -- never use web_search for weather.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name, e.g. 'Bengaluru' or 'London'."}
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the live web for current information -- news, facts, prices, anything "
                "up-to-date or real-world that you wouldn't already know. Do not use this for "
                "weather -- use get_weather instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to search for."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_reminder",
            "description": (
                "Save a reminder for the user, to be recalled later. Only use this when the user "
                "explicitly asks to be reminded of something or to remember a task -- for example "
                "'remind me to...' or 'don't let me forget...'. Do NOT use this just because you "
                "stated a fact or answered a question -- answering a math problem or a factual "
                "question is not a reason to save a reminder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "What to remind the user about."},
                    "due_at": {
                        "type": "string",
                        "description": "Optional due date/time in plain words (e.g. 'Friday 5pm'). Omit if not given.",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": (
                "List the user's current pending reminders. Use whenever the user asks what "
                "they need to do or what they're supposed to remember."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


MAX_TOOL_ROUNDS = 8  # matches Truffle's own documented default -- a safety cap, never expected in normal use

# What the model is told when the user is just sharing a fact (see diya_intent.is_fact_share).
# Left to itself, a small model turns "my flight is on Friday at 6" into paragraphs of advice and
# reaches for tools nobody asked for: it saved a reminder or ran a web search in 27 of 30
# measured runs, and claimed "I've set a reminder for your flight". The user's message is already
# stored in the thread and Dreaming stages facts for review, so there is nothing to store or look up.
#
# These instructions are sent ONLY on those turns. Sent on every turn they measurably halved the
# length of ordinary answers (median ~100 -> ~50 words), and ordinary answers must stay exactly
# as they were: on every other turn the request to the model is unchanged.
FACT_SHARE_PROMPT = (
    "The user is telling you something -- an appointment, a plan, a detail about their life -- and "
    "is asking for nothing. Reply with ONE short sentence: start with a brief acknowledgement (such "
    "as Got it, Noted, or Thanks) and then repeat the key detail, speaking to the user as \"you\" "
    "and \"your\" (never \"my\"). Do not add advice, tips, plans or extra information, do not ask "
    "follow-up questions, and do not use any tool. Their message is saved automatically; you never "
    "need to store it yourself."
)

# Added to the last user message (for the model only, never saved) on a clear fact-share: the
# instruction closest to the reply is the one a small model follows most reliably.
FACT_SHARE_HINT = (
    "(The user is telling you something, not asking. Reply with one short sentence: a brief "
    "acknowledgement such as Got it or Noted, then the key detail, addressed to the user as "
    "\"you\" or \"your\". No advice, no extra "
    "information, no questions.)"
)


def _last_user_text(messages):
    """The text of the newest user message in a conversation (tool messages can follow it)."""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            return m.get("content")
    return None


class Agent:
    """Diya's brain: the model client, the notes index, the toolkit and the tool-calling loop.

    Everything expensive is lazy -- constructing an Agent connects to nothing. The model
    client is created on first use and the notes index is built on the first search (or by
    warm_up(), which the entry points call at startup so a missing Ollama is caught
    immediately rather than on the first question).
    """

    def __init__(self, config=None, client=None, store=None):
        self.config = config or diya_config.load_config()
        self.store = store or diya_db.Store(self.config.db_path)
        self._client = client
        self._notes = None
        self._notes_lock = threading.Lock()
        self._functions = {
            "list_files": functools.partial(
                list_files, roots=diya_config.resolved_files_roots(self.config)
            ),
            "search_notes": self.search_notes,
            "get_weather": functools.partial(
                get_weather, allowed_hosts=self.config.tool_allowed_hosts
            ),
            "web_search": web_search,
            "add_reminder": self.add_reminder,
            "list_reminders": self.list_reminders,
        }

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAI(base_url=self.config.ollama_url, api_key="ollama")
        return self._client

    def embed(self, text):
        return self.client.embeddings.create(model=self.config.embed_model, input=text).data[0].embedding

    # ---- memory (Milestone 3): an in-memory index of the notes folder ----
    @property
    def notes(self):
        with self._notes_lock:
            if self._notes is None:
                self._notes = self._build_notes()
            return self._notes

    def _build_notes(self):
        import chromadb  # heavy; only needed once notes are actually searched

        # A unique name per Agent: Chroma's in-memory client is shared across a process, so a
        # fixed name would collide as soon as a second Agent (tests, evals) builds its own.
        notes = chromadb.Client().create_collection(f"notes-{uuid.uuid4().hex[:12]}")
        for filename in os.listdir(self.config.notes_dir):
            # UTF-8 explicitly, not the platform default (cp1252 on Windows), which turned any
            # non-ASCII note into mojibake; 'replace' so one stray byte can't stop startup.
            with open(os.path.join(self.config.notes_dir, filename), encoding="utf-8", errors="replace") as f:
                text = f.read()
            notes.add(ids=[filename], embeddings=[self.embed(text)], documents=[text])
        return notes

    def warm_up(self):
        """Build the notes index now. This is what used to happen at import time; it needs
        Ollama for the embeddings, so it doubles as the "is Ollama reachable?" check."""
        try:
            self.notes
        except Exception as exc:
            base_url = getattr(self.client, "base_url", self.config.ollama_url)
            raise OllamaUnavailable(base_url, exc) from exc

    # ---- the tools that need state ----
    def search_notes(self, query):
        result = self.notes.query(query_embeddings=[self.embed(query)], n_results=1)
        return result["documents"][0][0]

    def add_reminder(self, content, due_at=None):
        self.store.add_reminder(content, due_at)
        return f"Reminder saved: {content}" + (f" (due {due_at})" if due_at else "")

    def list_reminders(self):
        rows = self.store.list_reminders()
        if not rows:
            return "No pending reminders."
        return "\n".join(
            f"#{rid}: {content}" + (f" (due {due_at})" if due_at else "")
            for rid, content, due_at, done in rows
        )

    def with_profile(self, history):
        """Prepend Dreaming's output as a system message, if any exists -- shared by every
        entry point (terminal, web, evals) so this can't silently be missing from one of them
        again. Injected fresh each call, never saved into a thread's own persisted history --
        it should always reflect the latest profile, not a frozen snapshot."""
        path = self.config.profile_path
        if os.path.exists(path):
            # The profile is UTF-8 with LF line endings (that is how Dreaming's `direct` mode writes
            # it; nothing else writes it yet). It used to be read with the platform default codec
            # (cp1252 on Windows), so any non-ASCII fact came back as mojibake. A universal-newline
            # read also copes with a legacy CRLF profile; 'replace' so a stray byte can't take
            # chat down.
            with open(path, encoding="utf-8", errors="replace") as f:
                profile = f.read().strip()
            if profile:
                return [
                    {"role": "system", "content": f"What you know about the user so far:\n{profile}"}
                ] + history
        return history

    def _model_messages(self, messages, fact_share):
        """The conversation as the model sees it (the caller's list is left alone).

        Ordinary turns are passed through untouched. On a fact-share the fact-share instructions
        go first -- merged with the profile system message when there is one, so the model still
        gets a single system message -- and a reminder is added to the last user message to keep
        the reply to one sentence."""
        out = list(messages)
        if not fact_share:
            return out
        first = out[0] if out else None
        if isinstance(first, dict) and first.get("role") == "system":
            out[0] = {"role": "system", "content": FACT_SHARE_PROMPT + "\n\n" + first["content"]}
        else:
            out.insert(0, {"role": "system", "content": FACT_SHARE_PROMPT})
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if isinstance(m, dict) and m.get("role") == "user":
                out[i] = {**m, "content": f"{m['content']}\n\n{FACT_SHARE_HINT}"}
                break
        return out

    def _complete(self, messages, fact_share, tools):
        kwargs = {"model": self.config.model, "messages": self._model_messages(messages, fact_share)}
        if tools:
            kwargs["tools"] = tools
        return self.client.chat.completions.create(**kwargs)

    @staticmethod
    def _final(content, fact_share):
        """On a fact-share the prompt and the missing tools should already have produced one short
        sentence; this is the backstop if the model elaborates anyway."""
        return diya_intent.shorten_ack(content) if fact_share else content

    def ask(self, messages):
        """Returns (answer_text, tools_called) -- the tool list exists so evals can check routing.

        A clear fact-share ("my flight is on Friday at 6") is not a request: the model is called
        without tools (so it cannot save a reminder or search the web on its own initiative) and
        its reply is kept to one sentence. Everything else -- questions, requests, chat -- gets
        the full toolkit and a normal answer."""
        tools_called = []
        fact_share = diya_intent.is_fact_share(_last_user_text(messages))
        tools = None if fact_share else TOOLS
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._complete(messages, fact_share, tools)
            message = response.choices[0].message

            if not message.tool_calls:
                if message.content:
                    return self._final(message.content, fact_share), tools_called
                # The model sometimes returns nothing at all when no tool applies -- a known small-
                # model quirk, not a real answer. One bounded retry, on a throwaway copy of the
                # messages so the real conversation history doesn't get polluted with a nudge.
                retry = messages + [
                    {"role": "user", "content": "Please answer directly, in one short sentence."}
                ]
                retry_response = self._complete(retry, fact_share, tools)
                retry_content = retry_response.choices[0].message.content
                return self._final(retry_content or "I didn't get a clear answer -- try rephrasing.", fact_share), tools_called

            messages.append(message)
            for call in message.tool_calls:
                tools_called.append(call.function.name)
                func = self._functions[call.function.name]
                args = json.loads(call.function.arguments)
                print(f"  [tool call] {call.function.name}({args})")
                try:
                    result = func(**args)
                except Exception as exc:
                    result = f"Error: {exc}"
                    print(f"  [tool error] {result}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        return "I couldn't finish that after several tool calls -- something's likely stuck. Try rephrasing.", tools_called


# ---- entry-point helpers (the programs that own the console call these, not import) ----
def configure_console():
    """Let print() emit non-ASCII on a Windows console. This used to run as a side effect of
    importing this module; it is now an explicit step for the CLI, web server and evals."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def warm_up_or_exit(agent):
    """Fail fast with a clear message if Ollama isn't reachable, exactly as importing used to."""
    try:
        agent.warm_up()
    except OllamaUnavailable as exc:
        print(f"Couldn't start Diya: {exc}.")
        print("Is Ollama running? Start it, then try again.")
        sys.exit(1)


def chat_loop(agent, thread_id, history):
    print(f"[Diya -- thread {thread_id}. Type 'exit' (or Ctrl+C) to stop.]")
    for m in history:
        print(f"{m['role']}> {m['content']}")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        agent.store.add_message(thread_id, "user", user_input)
        history.append({"role": "user", "content": user_input})

        try:
            answer, _ = agent.ask(history)
        except Exception as exc:
            # Your message is already saved -- Ollama just isn't reachable right now.
            print(f"assistant> Couldn't reach the model ({exc}). Try again in a moment.")
            continue

        agent.store.add_message(thread_id, "assistant", answer)
        history.append({"role": "assistant", "content": answer})
        print(f"assistant> {answer}")


def main():
    configure_console()
    if len(sys.argv) < 2:
        print("Usage:")
        print('  python diya.py <thread_id|new>              -- start a live chat (default)')
        print('  python diya.py <thread_id|new> "message"     -- send one message and exit (for scripts)')
        return

    agent = Agent()
    warm_up_or_exit(agent)

    thread_arg = sys.argv[1]
    message = sys.argv[2] if len(sys.argv) > 2 else None

    if thread_arg == "new":
        thread_id = agent.store.create_thread()
        print(f"[created thread {thread_id}]")
    else:
        thread_id = int(thread_arg)

    history = agent.with_profile(agent.store.get_history(thread_id))

    if message is not None:
        # one-off mode: useful for scripts/scheduled tasks, not for talking to it yourself
        agent.store.add_message(thread_id, "user", message)
        history.append({"role": "user", "content": message})
        answer, _ = agent.ask(history)
        agent.store.add_message(thread_id, "assistant", answer)
        print(f"assistant> {answer}")
        return

    chat_loop(agent, thread_id, history)


if __name__ == "__main__":
    main()
