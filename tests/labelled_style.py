"""The messages of the reply-style benchmark (diya_style_bench.py; docs/STYLE_BENCH.md), written 2026-10-26 when the owner asked for replies "short like Hark".

Ordinary things a student asks: a fact, a tip, an explanation, a little chat, the weather. None needs a tool except the weather (the benchmark gives that tool a fixed answer). The model is given the made-up profile below as
what it "knows about the user", and none of these messages is about any of it, so a reply that brings it up is volunteering something nobody asked for.

`split` is "dev" (messages that may be looked at and tuned on) or "held-out" (written before any change to the reply style, and never tuned on: if a change is made because of one of them, it moves to "dev" and a new one is
written). `kind` sets how long a good reply may be (`max_words`): a fact is a line, an explanation is a short paragraph. `allowed_facts` names a profile word that the message makes relevant (a hobby question may
mention the guitar), so that mentioning it is not volunteering.
"""
PROFILE_LINES = [
    "Has a golden retriever named Rocky",
    "Plays the guitar",
    "Is studying AI at college",
    "Lives in Nellore",
    "Is allergic to peanuts",
]
# the words that show a profile fact was mentioned (lower case)
PROFILE_WORDS = {"rocky": "the dog", "retriever": "the dog", "guitar": "the guitar", "nellore": "where they live", "peanut": "the allergy", "studying ai": "their studies", "your studies": "their studies", "your course": "their studies"}

CASES = [
    {"id": "d01", "split": "dev", "kind": "chat", "prompt": "how are you doing today", "max_words": 40},
    {"id": "d02", "split": "dev", "kind": "advice", "prompt": "give me a tip to focus while studying", "max_words": 70},
    {"id": "d03", "split": "dev", "kind": "fact", "prompt": "what is the capital of australia", "max_words": 25},
    {"id": "d04", "split": "dev", "kind": "advice", "prompt": "is python or java better for a beginner", "max_words": 80},
    {"id": "d05", "split": "dev", "kind": "explain", "prompt": "explain what a neural network is", "max_words": 120},
    {"id": "d06", "split": "dev", "kind": "weather", "prompt": "how hot is it in pune", "max_words": 40},
    {"id": "d07", "split": "dev", "kind": "chat", "prompt": "tell me a joke", "max_words": 50},
    {"id": "d08", "split": "dev", "kind": "advice", "prompt": "what should i eat for dinner tonight", "max_words": 70, "allowed_facts": ["peanut"]},
    {"id": "d09", "split": "dev", "kind": "chat", "prompt": "i'm bored", "max_words": 50, "allowed_facts": ["guitar"]},
    {"id": "d10", "split": "dev", "kind": "fact", "prompt": "how do i say good morning in japanese", "max_words": 30},
    {"id": "d11", "split": "dev", "kind": "fact", "prompt": "what is 15% of 240", "max_words": 25},
    {"id": "d12", "split": "dev", "kind": "explain", "prompt": "why is the sky blue", "max_words": 110},
    {"id": "h01", "split": "held-out", "kind": "advice", "prompt": "how long should i sleep before an exam", "max_words": 70},
    {"id": "h02", "split": "held-out", "kind": "explain", "prompt": "what's the difference between a virus and a bacteria", "max_words": 120},
    {"id": "h03", "split": "held-out", "kind": "weather", "prompt": "is it going to rain in chennai today", "max_words": 40},
    {"id": "h04", "split": "held-out", "kind": "advice", "prompt": "suggest a good name for a study group", "max_words": 50},
    {"id": "h05", "split": "held-out", "kind": "fact", "prompt": "what is the speed of light", "max_words": 25},
    {"id": "h06", "split": "held-out", "kind": "chat", "prompt": "ugh my day was long", "max_words": 50},
    {"id": "h07", "split": "held-out", "kind": "advice", "prompt": "how do i stay calm before a test", "max_words": 80},
    {"id": "h08", "split": "held-out", "kind": "fact", "prompt": "who invented the telephone", "max_words": 25},
    {"id": "h09", "split": "held-out", "kind": "advice", "prompt": "can you recommend a hobby", "max_words": 70, "allowed_facts": ["guitar"]},
    {"id": "h10", "split": "held-out", "kind": "explain", "prompt": "what does an operating system do", "max_words": 110},
    {"id": "h11", "split": "held-out", "kind": "fact", "prompt": "how many minutes are in a day", "max_words": 25},
    {"id": "h12", "split": "held-out", "kind": "chat", "prompt": "give me a quick pep talk", "max_words": 50},
]
