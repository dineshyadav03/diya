"""Does episodic recall find the right earlier message? (docs/EPISODIC_DESIGN.md), added 2026-10-20.

    python diya_episodic_bench.py                 needs Ollama and the embedding model: embeds the invented messages and questions of tests/labelled_episodic.py, in memory only
    python diya_episodic_bench.py --chat          also asks the CHAT model each question with and without the note, and checks the answer for the words it should hold (about 20 minutes on a CPU)

It touches no database and none of your data. It reports: how often the right message is the closest one (top 1) and among the closest three, the best score each answerable and each unrelated question
reaches, and how many of each would pass a threshold, so that THRESHOLD in diya_episodic.py can be seen to sit between them. With --chat, the answers of the model with and without the note.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import labelled_episodic as L  # noqa: E402

import diya_config  # noqa: E402
import diya_episodic  # noqa: E402
import diya_recall  # noqa: E402

# the words the right answer must contain (case-insensitive), one entry per question of L.ASKED
EXPECT = ["5th", "zed", "maya", "40", "legs", "8 pm", "14 november", "yamaha", "thursday", "21", "peanut", "income certificate", "february", "upper limb", "10:30", "goa", "rohan", "hour", "iris", "12th"]
THRESHOLDS = (0.45, 0.5, 0.55, 0.6, 0.65, 0.7)


def measure(embed, out=print):
    docs = [embed(m) for m in L.MESSAGES]
    asked = [(q, a, embed(q)) for q, a in L.ASKED]
    unrelated = [(q, embed(q)) for q in L.UNRELATED]
    top1 = top3 = 0
    good, bad = [], []
    for q, answer, vector in asked:
        ranked = sorted(range(len(docs)), key=lambda i: -diya_recall.cosine(vector, docs[i]))
        ok = answer if isinstance(answer, tuple) else (answer,)
        top1 += ranked[0] in ok
        top3 += any(i in ok for i in ranked[:3])
        good.append(diya_recall.cosine(vector, docs[ranked[0]]))
        if ranked[0] not in ok:
            out(f"  miss: {q!r} found {L.MESSAGES[ranked[0]][:60]!r} ({good[-1]:.2f})")
    for q, vector in unrelated:
        bad.append(max(diya_recall.cosine(vector, d) for d in docs))
    out(f"top 1: {top1}/{len(asked)}   top 3: {top3}/{len(asked)}")
    out(f"best score, answerable: lowest {min(good):.2f}, median {sorted(good)[len(good) // 2]:.2f}; unrelated: highest {max(bad):.2f}, median {sorted(bad)[len(bad) // 2]:.2f}")
    for t in THRESHOLDS:
        out(f"  threshold {t:.2f}: answerable found {sum(s >= t for s in good)}/{len(good)}, unrelated let through {sum(s >= t for s in bad)}/{len(bad)}" + ("   <- THRESHOLD" if t == diya_episodic.THRESHOLD else ""))
    return {"top1": top1, "top3": top3, "asked": len(asked), "answerable_min": min(good), "unrelated_max": max(bad)}


def ask_chat(client, model, question, note=None):
    system = "You are Diya, a personal assistant. Answer in one short sentence." + (("\n\n" + note) if note else "")
    reply = client.chat.completions.create(model=model, messages=[{"role": "system", "content": system}, {"role": "user", "content": question}])
    return (reply.choices[0].message.content or "").strip()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="diya_episodic_bench.py")
    parser.add_argument("--chat", action="store_true", help="also ask the chat model each question with and without the note")
    args = parser.parse_args(argv)
    config = diya_config.load_config()
    import diya

    agent = diya.Agent(config)
    started = time.time()
    result = measure(lambda text: [float(x) for x in agent.embed(text)])
    print(f"({time.time() - started:.0f}s for {len(L.MESSAGES) + len(L.ASKED) + len(L.UNRELATED)} embeddings with {config.embed_model})")
    if not args.chat:
        return 0 if result["top1"] == result["asked"] else 1
    docs = [[float(x) for x in agent.embed(m)] for m in L.MESSAGES]
    plain = grounded = 0
    for (question, answer), words in zip(L.ASKED, EXPECT):
        vector = [float(x) for x in agent.embed(question)]
        ranked = sorted(range(len(docs)), key=lambda i: -diya_recall.cosine(vector, docs[i]))
        found = [{"id": i, "text": L.MESSAGES[i], "at": "2026-10-01T10:00:00+00:00"} for i in ranked[:diya_episodic.TOP] if diya_recall.cosine(vector, docs[i]) >= diya_episodic.THRESHOLD]
        without = ask_chat(agent.client, config.model, question)
        with_note = ask_chat(agent.client, config.model, question, diya_episodic.note(found))
        plain += words.lower() in without.lower()
        grounded += words.lower() in with_note.lower()
        print(f"{question!r}: without -> {without[:70]!r} | with -> {with_note[:70]!r}")
    print(f"answers holding the right words: without the note {plain}/{len(L.ASKED)}, with it {grounded}/{len(L.ASKED)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
