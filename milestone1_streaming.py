from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

stream = client.chat.completions.create(
    model="llama3.2:3b",
    messages=[
        {"role": "user", "content": "In one sentence, what is a language model?"}
    ],
    stream=True,
)

for chunk in stream:
    piece = chunk.choices[0].delta.content
    if piece:
        print(piece, end="", flush=True)

print()
