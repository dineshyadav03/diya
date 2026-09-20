from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",  # Ollama doesn't check this, but the library requires something here
)

response = client.chat.completions.create(
    model="llama3.2:3b",
    messages=[
        {"role": "user", "content": "In one sentence, what is a language model?"}
    ],
)

print(response.choices[0].message.content)
