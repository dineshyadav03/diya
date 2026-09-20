import os

from openai import OpenAI

CONTEXT_FILE = "proactive_context.txt"

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

latest = None
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE) as f:
        lines = [line.strip() for line in f if line.strip()]
    if lines:
        latest = lines[-1]  # plain Python picks "most recent" -- no need to ask the model

messages = []
if latest:
    messages.append(
        {
            "role": "system",
            "content": (
                f'You remember this about the user: "{latest}" '
                "When you greet them, mention it naturally, in your own words -- "
                "don't just repeat the sentence verbatim."
            ),
        }
    )
messages.append({"role": "user", "content": "Hey, what's up?"})

response = client.chat.completions.create(model="qwen2.5:3b", messages=messages)
print(response.choices[0].message.content)
