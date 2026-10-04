import fnmatch
import functools
import json
import os
import pathlib
import sys
import threading
import urllib.parse
import uuid
from datetime import datetime

import httpx
from ddgs import DDGS
from openai import OpenAI

import diya_actions
import diya_config
import diya_connector_tools
import diya_connectors
import diya_db
import diya_intent
import diya_memory
import diya_time

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
                        "description": (
                            "Optional: when, in the user's own words, unchanged (e.g. 'Friday 5pm', 'tomorrow at 9am', "
                            "'in 2 hours'). Omit if they gave no time. Never guess a time."
                        ),
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

MAX_REMINDER_CHARS = 300
# What add_reminder adds when the time the model passed is not the one the person said (see diya_time.disagreement).
REMINDER_TIME_HINT = (
    "Pass the time exactly as the user said it (their own words, nothing added or left out); if you are not sure what "
    "they meant, ask them when, then try again."
)
# What add_reminder answers the model when the person did not ask for a reminder (docs/PROACTIVITY_DESIGN.md, D9).
REMINDER_NOT_ASKED = (
    "Not saved: the user did not ask for a reminder. Answer what they asked and save nothing. If they did want one, "
    "they can say 'remind me to ...'."
)

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

    def __init__(self, config=None, client=None, store=None, clock=None, action_kinds=None):
        self.config = config or diya_config.load_config()
        self.store = store or diya_db.Store(self.config.db_path)
        # The approval gate (docs/ACTIONS_DESIGN.md): the kinds of write Diya may PROPOSE (each only while its connector
        # is connected, and each only ever run after the owner approves it). Tests hand in fakes, the way they hand in
        # a fake model client.
        self.actions = diya_actions.Actions(
            self.store, self.config,
            diya_connector_tools.real_action_kinds() if action_kinds is None else tuple(action_kinds),
        )
        self._client = client
        self._clock = clock or datetime.now  # a naive local datetime; a parameter so tests do not depend on today
        self._turn = threading.local()  # what the current ask() is answering, per thread
        self._notes = None
        self._notes_lock = threading.Lock()
        self._profile_import_checked = False
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
        # Connector tools (docs/CONNECTORS_DESIGN.md, unit C2) are always registered here -- each
        # checks its own connection fresh on every call -- but only offered to the model (self.tools)
        # when actually connected, so a disconnect takes effect on the very next turn.
        for _name, spec, func in diya_connector_tools.tool_specs(self.config):
            self._functions[spec["function"]["name"]] = func
        # A kind of action's tool (docs/ACTIONS_DESIGN.md, D1) only ever PROPOSES: the function registered for
        # it records a pending action and returns, and nothing is performed. A name that another tool already
        # has would let one shadow the other, so that refuses to start rather than guess.
        self._proposal_tools = set()
        taken = set(self._functions)
        for kind in self.actions.kinds:
            if kind.tool is None:
                continue
            if kind.tool_name in taken:
                raise ValueError(f"the tool name {kind.tool_name!r} (action kind {kind.name}) is already another tool's")
            taken.add(kind.tool_name)
            self._proposal_tools.add(kind.tool_name)
            self._functions[kind.tool_name] = functools.partial(self._propose, kind)

    @property
    def tools(self):
        """What the model is offered this turn: the fixed tools, plus a connector's tool only while
        it is actually connected (docs/CONNECTORS_DESIGN.md, D4), plus the proposal tool of each kind of
        action whose connector is connected (docs/ACTIONS_DESIGN.md, D2) -- computed fresh, not cached, so
        connecting or disconnecting takes effect on the next message, not at the next restart."""
        result = list(TOOLS)
        for name, spec, _func in diya_connector_tools.tool_specs(self.config):
            if diya_connectors.is_connected(self.config, name):
                result.append(spec)
        for kind in self.actions.kinds:
            if kind.tool is not None and (kind.connector is None or diya_connectors.is_connected(self.config, kind.connector)):
                result.append(kind.tool)
        return result

    def now(self):
        """The current local time, naive: the agent's clock (real unless a test gave it another)."""
        return self._clock()

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
        """Save a reminder. While a message is being answered (ask), only if that message asks for one
        (docs/PROACTIVITY_DESIGN.md, D9); the time is read here, in code, from the person's own words, and
        a time that cannot be read saves nothing and says so, so the model can ask (D2). What it returns is
        what the model relays to the person, so it says exactly what was saved and for when."""
        if getattr(self._turn, "active", False) and not diya_intent.is_reminder_request(self._turn.user_text):
            return REMINDER_NOT_ASKED
        if not isinstance(content, str) or not content.strip():
            return "Not saved: a reminder needs something to remind the user about."
        content = " ".join(content.split())
        if len(content) > MAX_REMINDER_CHARS:
            return f"Not saved: that reminder is over {MAX_REMINDER_CHARS} characters; shorten it and try again."
        in_turn = getattr(self._turn, "active", False)
        if due_at is None or (isinstance(due_at, str) and not due_at.strip()):
            problem = diya_time.disagreement("", self._turn.user_text) if in_turn else None
            if problem:
                return f"Not saved: {problem}. {REMINDER_TIME_HINT}"
            self.store.add_reminder(content)
            return f"Reminder saved: {content}. It has NO time, so it will not fire: tell the user that, and ask when they want it."
        if not isinstance(due_at, str):
            return "Not saved: the time must be given in words, like 'Friday 5pm' or 'in 2 hours'."
        words = due_at
        try:
            when = diya_time.parse_when(words, self._clock())
        except diya_time.NotUnderstood as exc:
            return (
                f"Not saved: I could not tell when {words[:60]!r} is ({exc.reason}). Ask the user for a day and a "
                "time, for example 'Friday 5pm' or 'in 2 hours', then try again."
            )
        # The model passes on the person's own words for when, and does not always: measured, it dropped a date, turned
        # "morning" into "8am" and invented times. A time the person did not say would fire at a time they never chose.
        problem = diya_time.disagreement(words, self._turn.user_text) if in_turn else None
        if problem:
            return f"Not saved: {problem}. {REMINDER_TIME_HINT}"
        self.store.add_reminder(content, " ".join(words.split()), when.iso())
        note = f" ({'; '.join(when.assumed)})" if when.assumed else ""
        return f"Reminder saved: {content}, for {when.describe()}{note}"

    def _propose(self, kind, /, **args):
        """The tool behind a kind of action (docs/ACTIONS_DESIGN.md, D1): it PROPOSES and does nothing else. The
        arguments are the model's, whitespace tidied; what is recorded beside them is the turn's own, never the
        model's: the owner's message it answers and the tools that ran earlier in the same turn (D6), which the
        Actions page shows. What comes back is a fixed sentence for the model (diya_actions.proposed_text or
        refused_text). `kind` is positional-only, so an argument the model names "kind" cannot collide with it."""
        in_turn = getattr(self._turn, "active", False)
        said = self._turn.user_text if in_turn else None
        # While a message is being answered, a kind that says how to tell can refuse a proposal the message did not ask
        # for, and take out of one what the message does not support (ActionKind.asked and .prepare; measured in
        # docs/ACTIONS_DESIGN.md, section 6). A call made outside a turn is not judged by an old message.
        if in_turn and kind.asked is not None and not kind.asked(said):
            return diya_actions.NOT_ASKED_TEXT
        args = diya_actions.normalise_args(args)
        notes = []
        if in_turn and kind.prepare is not None:
            args, notes = kind.prepare(args, said)
        try:
            action = self.actions.propose(
                kind.name,
                args,
                thread_id=self._turn.thread_id if in_turn else None,
                message_id=self._turn.message_id if in_turn else None,
                taint_sources=list(self._turn.reads) if in_turn else (),
            )
        except diya_actions.ActionError as exc:
            return diya_actions.refused_text(exc)
        return diya_actions.proposed_text(action, notes)

    def list_reminders(self):
        rows = self.store.reminders("pending")
        if not rows:
            return "No pending reminders."
        lines = []
        for row in rows:
            if row["due_ts"]:
                when = f" (due {diya_time.describe_local(diya_time.local_from_iso(row['due_ts']))})"
            elif row["due_at"]:
                when = f" (no time set; asked as {row['due_at']!r})"
            else:
                when = ""
            lines.append(f"#{row['id']}: {row['content']}{when}")
        return "\n".join(lines)

    def ensure_profile_imported(self):
        """Give the old `user_profile.txt` a home in reviewed memory, once. Before memory was reviewed
        the model was told that file's text on every turn; now it is told the ACCEPTED facts, so the
        file's lines have to be facts too or the model would silently lose everything it knew.

        Only if nothing has ever been imported (a fact someone retired is not brought back by a later
        call), and only if the file exists. The file is never changed, and after this it is never read
        again: what the model knows is changed with `python diya_review.py`, not by editing the file.
        Returns the ImportResult if this call imported anything, else None."""
        memory = diya_memory.Memory(self.store)
        if memory.has_legacy_import() or not os.path.exists(self.config.profile_path):
            return None
        result = diya_memory.import_legacy_profile(memory, self.config)
        return result if result.imported else None

    def with_profile(self, history):
        """Prepend what the model knows about the user -- the ACCEPTED facts of reviewed memory, never a
        candidate, a rejected or a retired one -- as a system message, if there are any. Shared by every
        entry point (terminal, web) so this can't silently be missing from one of them. Injected fresh
        each call, never saved into a thread's own persisted history: it should always reflect the
        current memory, not a frozen snapshot. Self facts are one plain list; a fact tagged to a named
        person sits in its own labelled block instead (docs/PERSON_MEMORY_DESIGN.md, M4).

        The first call also makes sure the old profile file has been imported (ensure_profile_imported),
        so no entry point can start without the facts the model used to be given."""
        if not self._profile_import_checked:
            self.ensure_profile_imported()
            self._profile_import_checked = True
        profile = diya_memory.Memory(self.store).render_for_model()
        if profile:
            return [{"role": "system", "content": f"What you know about the user so far:\n{profile}"}] + history
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

    def ask(self, messages, *, thread_id=None, message_id=None):
        """Returns (answer_text, tools_called) -- the tool list exists so evals can check routing.

        While it runs, add_reminder knows what the person just said (see there), and a proposed action
        (docs/ACTIONS_DESIGN.md) knows which chat and which of the owner's messages it came from and which tools
        ran before it (`thread_id`, `message_id`, the tools run so far); when it is over all of that is
        forgotten, so a later direct call is not judged by an old message.
        """
        self._turn.user_text = _last_user_text(messages)
        self._turn.thread_id = thread_id
        self._turn.message_id = message_id
        self._turn.reads = []
        self._turn.active = True
        try:
            return self._ask(messages)
        finally:
            self._turn.active = False
            self._turn.user_text = None
            self._turn.thread_id = None
            self._turn.message_id = None
            self._turn.reads = []

    def _ask(self, messages):
        """The tool-calling loop behind ask().

        A clear fact-share ("my flight is on Friday at 6") is not a request: the model is called
        without tools (so it cannot save a reminder or search the web on its own initiative) and
        its reply is kept to one sentence. Everything else -- questions, requests, chat -- gets
        the full toolkit and a normal answer."""
        tools_called = []
        fact_share = diya_intent.is_fact_share(_last_user_text(messages))
        tools = None if fact_share else self.tools
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
                if call.function.name not in self._proposal_tools and call.function.name != "list_reminders":
                    # What a proposal later in this turn will say it came after (docs/ACTIONS_DESIGN.md, D6): every
                    # tool that ran, whatever it returned -- but not another proposal, and not the owner's own list
                    # of reminders. Recorded before it runs, so a tool that fails is still listed.
                    self._turn.reads.append(call.function.name)
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


def memory_startup_lines(agent):
    """What to tell the person about Diya's memory when it starts (the terminal chat and the web server
    both print these): that the old profile file was taken in, if it was; how much the model is being
    told; whether facts are waiting for review; and whether the old file has lines that are in no fact
    (that file is no longer read). Imports the old profile if that has not happened yet."""
    memory = diya_memory.Memory(agent.store)
    lines = []
    try:
        imported = agent.ensure_profile_imported()
    except diya_memory.SourceUnreadable as exc:
        imported = None
        lines.append(f"Memory: could not take in the old profile: {exc}")
    if imported is not None:
        lines.append(
            f"Memory: took {imported.imported} lines of {agent.config.profile_path} in as accepted facts. That file "
            "was not changed and is not read any more: change what Diya knows with `python diya_review.py`."
        )
    counts = memory.counts()
    used = len(memory.render())
    lines.append(
        f"Memory: {counts['accepted']} accepted facts ({used} of {diya_memory.MAX_PROFILE_CHARS} characters) are "
        f"given to the model; {counts['candidate']} candidates wait for review (`python diya_review.py list`)."
    )
    stray = diya_memory.profile_lines_not_in_memory(memory, agent.config)
    if stray:
        lines.append(
            f"Memory: {stray} lines in {agent.config.profile_path} are in no fact, and that file is not read any "
            "more. `python diya_review.py import-profile` takes them in."
        )
    return lines


def actions_startup_lines(agent):
    """What to tell the person about the approval gate when Diya starts (the terminal chat and the web server
    both print these, docs/ACTIONS_DESIGN.md): any action that was still running when Diya last stopped is moved
    to `unknown` first (it is never run again, D4), then how many are waiting for the owner or need a look.
    Nothing is said when there is nothing to say, which is the usual case."""
    cut_off = agent.actions.reconcile()
    counts = agent.actions.counts()
    lines = []
    if cut_off:
        lines.append(
            f"Actions: {cut_off} action{' was' if cut_off == 1 else 's were'} still running when Diya last stopped, so "
            "what happened is not known. It will not be run again: check the service, then record what you found "
            "(Actions page, or `python diya_actions_cli.py`)."
        )
    if counts["pending"]:
        lines.append(f"Actions: {counts['pending']} waiting for your approval (Actions page, or `python diya_actions_cli.py list`).")
    if counts["unknown"] and not cut_off:
        lines.append(
            f"Actions: {counts['unknown']} with an unknown outcome still {'needs' if counts['unknown'] == 1 else 'need'} "
            "you to record what happened."
        )
    return lines


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

        message_id = agent.store.add_message(thread_id, "user", user_input)
        history.append({"role": "user", "content": user_input})

        try:
            answer, _ = agent.ask(history, thread_id=thread_id, message_id=message_id)
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
        message_id = agent.store.add_message(thread_id, "user", message)
        history.append({"role": "user", "content": message})
        answer, _ = agent.ask(history, thread_id=thread_id, message_id=message_id)
        agent.store.add_message(thread_id, "assistant", answer)
        print(f"assistant> {answer}")
        return

    for line in memory_startup_lines(agent) + actions_startup_lines(agent):  # only in the live chat: a one-off run's output is for scripts
        print(f"[{line}]")
    chat_loop(agent, thread_id, history)


if __name__ == "__main__":
    main()
