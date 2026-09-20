import json
import os
import sys
import threading
import uuid

import httpx
from ddgs import DDGS
from openai import OpenAI

import diya_config
import diya_db

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
def list_files(directory="."):
    return "\n".join(os.listdir(directory))


NETWORK_TIMEOUT = 5.0  # seconds -- fail fast instead of hanging when there's no connection


# The geocoding API doesn't reliably treat old/colonial city names as aliases of the
# current official name -- "Bangalore" alone can return only the wrong country's match,
# with nothing to disambiguate against. Normalize well-known cases before querying.
CITY_ALIASES = {
    "bangalore": "Bengaluru",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
}


def get_weather(location):
    location = CITY_ALIASES.get(location.strip().lower(), location)
    try:
        geo = httpx.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 5},
            timeout=NETWORK_TIMEOUT,
        ).json()
        results = geo.get("results")
        if not results:
            return f"Couldn't find a location called '{location}'."

        # Prefer the most populous match -- avoids silently picking an obscure same-named place.
        best = max(results, key=lambda r: r.get("population", 0))

        weather = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": best["latitude"],
                "longitude": best["longitude"],
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
            timeout=NETWORK_TIMEOUT,
        ).json()["current"]
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
            "description": "List the files in a directory on this computer.",
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
            "list_files": list_files,
            "search_notes": self.search_notes,
            "get_weather": get_weather,
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
            with open(os.path.join(self.config.notes_dir, filename)) as f:
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
            with open(path) as f:
                profile = f.read().strip()
            if profile:
                return [
                    {"role": "system", "content": f"What you know about the user so far:\n{profile}"}
                ] + history
        return history

    def ask(self, messages):
        """Returns (answer_text, tools_called) -- the tool list exists so evals can check routing."""
        tools_called = []
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.chat.completions.create(
                model=self.config.model, messages=messages, tools=TOOLS
            )
            message = response.choices[0].message

            if not message.tool_calls:
                if message.content:
                    return message.content, tools_called
                # The model sometimes returns nothing at all when no tool applies -- a known small-
                # model quirk, not a real answer. One bounded retry, on a throwaway copy of the
                # messages so the real conversation history doesn't get polluted with a nudge.
                retry = messages + [
                    {"role": "user", "content": "Please answer directly, in one short sentence."}
                ]
                retry_response = self.client.chat.completions.create(
                    model=self.config.model, messages=retry, tools=TOOLS
                )
                retry_content = retry_response.choices[0].message.content
                return retry_content or "I didn't get a clear answer -- try rephrasing.", tools_called

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


# ---- Temporary: the old module-level API, for callers not yet moved to their own Agent
# (diya_web.py, diya_evals.py). Removed once they are. ----
_default_agent = None


def _agent():
    global _default_agent
    if _default_agent is None:
        _default_agent = Agent()
    return _default_agent


def ask(messages):
    return _agent().ask(messages)


def with_profile(history):
    return _agent().with_profile(history)


if __name__ == "__main__":
    main()
