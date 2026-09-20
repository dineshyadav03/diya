import os

import chromadb
from openai import OpenAI

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")


def embed(text):
    return client.embeddings.create(model="nomic-embed-text", input=text).data[0].embedding


# A fresh, empty vector store, kept only in memory for this demo run.
chroma = chromadb.Client()
collection = chroma.create_collection("notes")

# Step 1: embed every note once, ahead of time, and store it.
NOTES_DIR = "sample_notes"
for filename in os.listdir(NOTES_DIR):
    with open(os.path.join(NOTES_DIR, filename)) as f:
        text = f.read()
    collection.add(ids=[filename], embeddings=[embed(text)], documents=[text])
print(f"Embedded and stored {len(os.listdir(NOTES_DIR))} notes.\n")

# Deliberately paraphrased -- shares almost no words with the actual note.
question = "When's my tooth checkup?"

# Step 2 & 3: embed the question, ask the vector store what's closest to it.
results = collection.query(query_embeddings=[embed(question)], n_results=1)
retrieved_note = results["documents"][0][0]
print(f"[question]        {question}")
print(f"[note retrieved]  {retrieved_note.strip()}\n")

# Step 4 & 5: hand the retrieved note to the chat model as context, ask it to answer.
answer = client.chat.completions.create(
    model="qwen2.5:3b",
    messages=[
        {
            "role": "user",
            "content": (
                f'Using only this note, answer the question in one short sentence.\n'
                f'Note: "{retrieved_note.strip()}"\n'
                f"Question: {question}"
            ),
        }
    ],
)
print(f"[model's answer]  {answer.choices[0].message.content}")
