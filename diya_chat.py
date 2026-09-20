import sys

from openai import OpenAI

import diya_db

sys.stdout.reconfigure(encoding="utf-8")

MODEL = "qwen2.5:3b"
client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def main():
    if len(sys.argv) < 2:
        print('Usage: python diya_chat.py <thread_id|new> ["your message"]')
        return

    thread_arg = sys.argv[1]
    message = sys.argv[2] if len(sys.argv) > 2 else None

    if thread_arg == "new":
        thread_id = diya_db.create_thread()
        print(f"[created thread {thread_id}]")
    else:
        thread_id = int(thread_arg)

    history = diya_db.get_history(thread_id)

    if message is None:
        print(f"[thread {thread_id} history -- {len(history)} messages]")
        for m in history:
            print(f"{m['role']}> {m['content']}")
        return

    diya_db.add_message(thread_id, "user", message)
    history.append({"role": "user", "content": message})

    response = client.chat.completions.create(model=MODEL, messages=history)
    answer = response.choices[0].message.content

    diya_db.add_message(thread_id, "assistant", answer)
    print(f"assistant> {answer}")


if __name__ == "__main__":
    main()
