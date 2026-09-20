import json
import os
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def list_files(directory="."):
    """The real, boring Python function that actually does the work."""
    return "\n".join(os.listdir(directory))


# Describing that function to the model, in a shape it's trained to understand.
tools = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files in a directory on this computer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The folder path to list files in.",
                    }
                },
                "required": ["directory"],
            },
        },
    }
]

messages = [
    {"role": "user", "content": "What files are in my project folder? Use '.' as the directory."}
]

response = client.chat.completions.create(
    model="qwen2.5:3b",
    messages=messages,
    tools=tools,
)

message = response.choices[0].message

if message.tool_calls:
    call = message.tool_calls[0]
    args = json.loads(call.function.arguments)
    print(f"[model requested] {call.function.name}({args})")

    result = list_files(**args)
    print(f"[we actually ran it, got back]\n{result}\n")

    # Hand the tool's result back to the model so it can answer in plain English.
    messages.append(message)
    messages.append({
        "role": "tool",
        "tool_call_id": call.id,
        "content": result,
    })

    final = client.chat.completions.create(model="qwen2.5:3b", messages=messages)
    print("[model's final answer]")
    print(final.choices[0].message.content)
else:
    print("[model answered directly, no tool needed]")
    print(message.content)
