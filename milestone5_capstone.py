import json
import os
import sys

import chromadb
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8")  # model output can contain any Unicode character

MODEL = "qwen2.5:3b"
NOTES_DIR = "sample_notes"
CONTEXT_FILE = "proactive_context.txt"

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def embed(text):
    return client.embeddings.create(model="nomic-embed-text", input=text).data[0].embedding


# ---- Milestone 3: memory, built once at startup ----
chroma = chromadb.Client()
notes = chroma.create_collection("notes")
for filename in os.listdir(NOTES_DIR):
    with open(os.path.join(NOTES_DIR, filename)) as f:
        text = f.read()
    notes.add(ids=[filename], embeddings=[embed(text)], documents=[text])


# ---- Milestone 2: two real tools ----
def list_files(directory="."):
    return "\n".join(os.listdir(directory))


def search_notes(query):
    result = notes.query(query_embeddings=[embed(query)], n_results=1)
    return result["documents"][0][0]


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
]

AVAILABLE_FUNCTIONS = {"list_files": list_files, "search_notes": search_notes}


# ---- Milestone 4: proactive context ----
def load_latest_context():
    if not os.path.exists(CONTEXT_FILE):
        return None
    with open(CONTEXT_FILE) as f:
        lines = [line.strip() for line in f if line.strip()]
    return lines[-1] if lines else None


# ---- The capstone: one loop that lets the model call tools as many times as it needs ----
def ask(messages):
    while True:
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        message = response.choices[0].message

        if not message.tool_calls:
            return message.content

        messages.append(message)
        for call in message.tool_calls:
            func = AVAILABLE_FUNCTIONS[call.function.name]
            args = json.loads(call.function.arguments)
            print(f"  [tool call] {call.function.name}({args})")
            try:
                result = func(**args)
            except Exception as exc:
                # Never trust model-provided arguments -- hand the failure back to the model
                # instead of crashing, so it can see what went wrong and try again.
                result = f"Error: {exc}"
                print(f"  [tool error] {result}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})


def main():
    messages = []
    latest = load_latest_context()
    if latest:
        messages.append(
            {
                "role": "system",
                "content": (
                    f'You remember this about the user: "{latest}" '
                    "When you greet them, mention it naturally, in your own words."
                ),
            }
        )

    questions = [
        "Hey, what's up?",
        "What files are in this project?",
        "What did I say about my dentist?",
        "What's 9 times 7?",
    ]

    for question in questions:
        print(f"\nyou> {question}")
        messages.append({"role": "user", "content": question})
        answer = ask(messages)
        messages.append({"role": "assistant", "content": answer})
        print(f"assistant> {answer}")


if __name__ == "__main__":
    main()
