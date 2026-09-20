import json
import os
import sys

import chromadb
import httpx
from ddgs import DDGS
from openai import OpenAI

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

sys.stdout.reconfigure(encoding="utf-8")

MODEL = "qwen2.5:3b"
NOTES_DIR = "sample_notes"

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def embed(text):
    return client.embeddings.create(model="nomic-embed-text", input=text).data[0].embedding


# ---- memory, built at startup (Milestone 3) ----
try:
    chroma = chromadb.Client()
    notes = chroma.create_collection("notes")
    for filename in os.listdir(NOTES_DIR):
        with open(os.path.join(NOTES_DIR, filename)) as f:
            text = f.read()
        notes.add(ids=[filename], embeddings=[embed(text)], documents=[text])
except Exception as exc:
    print(f"Couldn't start Diya: can't reach Ollama at {client.base_url} ({exc}).")
    print("Is Ollama running? Start it, then try again.")
    sys.exit(1)


# ---- Diya's default toolkit ----
def list_files(directory="."):
    return "\n".join(os.listdir(directory))


def search_notes(query):
    result = notes.query(query_embeddings=[embed(query)], n_results=1)
    return result["documents"][0][0]


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


def add_reminder(content, due_at=None):
    diya_db.add_reminder(content, due_at)
    return f"Reminder saved: {content}" + (f" (due {due_at})" if due_at else "")


def list_reminders():
    rows = diya_db.list_reminders()
    if not rows:
        return "No pending reminders."
    return "\n".join(
        f"#{rid}: {content}" + (f" (due {due_at})" if due_at else "")
        for rid, content, due_at, done in rows
    )


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

AVAILABLE_FUNCTIONS = {
    "list_files": list_files,
    "search_notes": search_notes,
    "get_weather": get_weather,
    "web_search": web_search,
    "add_reminder": add_reminder,
    "list_reminders": list_reminders,
}


MAX_TOOL_ROUNDS = 8  # matches Truffle's own documented default -- a safety cap, never expected in normal use


def with_profile(history):
    """Prepend Dreaming's output as a system message, if any exists -- shared by every
    entry point (terminal, web, evals) so this can't silently be missing from one of them
    again. Injected fresh each call, never saved into a thread's own persisted history --
    it should always reflect the latest profile, not a frozen snapshot."""
    if os.path.exists("user_profile.txt"):
        with open("user_profile.txt") as f:
            profile = f.read().strip()
        if profile:
            return [
                {"role": "system", "content": f"What you know about the user so far:\n{profile}"}
            ] + history
    return history


def ask(messages):
    """Returns (answer_text, tools_called) -- the tool list exists so evals can check routing."""
    tools_called = []
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
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
            retry_response = client.chat.completions.create(
                model=MODEL, messages=retry, tools=TOOLS
            )
            retry_content = retry_response.choices[0].message.content
            return retry_content or "I didn't get a clear answer -- try rephrasing.", tools_called

        messages.append(message)
        for call in message.tool_calls:
            tools_called.append(call.function.name)
            func = AVAILABLE_FUNCTIONS[call.function.name]
            args = json.loads(call.function.arguments)
            print(f"  [tool call] {call.function.name}({args})")
            try:
                result = func(**args)
            except Exception as exc:
                result = f"Error: {exc}"
                print(f"  [tool error] {result}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    return "I couldn't finish that after several tool calls -- something's likely stuck. Try rephrasing.", tools_called


def chat_loop(thread_id, history):
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

        diya_db.add_message(thread_id, "user", user_input)
        history.append({"role": "user", "content": user_input})

        try:
            answer, _ = ask(history)
        except Exception as exc:
            # Your message is already saved -- Ollama just isn't reachable right now.
            print(f"assistant> Couldn't reach the model ({exc}). Try again in a moment.")
            continue

        diya_db.add_message(thread_id, "assistant", answer)
        history.append({"role": "assistant", "content": answer})
        print(f"assistant> {answer}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print('  python diya.py <thread_id|new>              -- start a live chat (default)')
        print('  python diya.py <thread_id|new> "message"     -- send one message and exit (for scripts)')
        return

    thread_arg = sys.argv[1]
    message = sys.argv[2] if len(sys.argv) > 2 else None

    if thread_arg == "new":
        thread_id = diya_db.create_thread()
        print(f"[created thread {thread_id}]")
    else:
        thread_id = int(thread_arg)

    history = with_profile(diya_db.get_history(thread_id))

    if message is not None:
        # one-off mode: useful for scripts/scheduled tasks, not for talking to it yourself
        diya_db.add_message(thread_id, "user", message)
        history.append({"role": "user", "content": message})
        answer, _ = ask(history)
        diya_db.add_message(thread_id, "assistant", answer)
        print(f"assistant> {answer}")
        return

    chat_loop(thread_id, history)


if __name__ == "__main__":
    main()
