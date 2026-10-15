"""Cases for the question-and-answer measurement of Diya's memory (diya_memory_qa_bench.py; docs/MEMORY_BENCH.md), written by the author in the manner of the long-term-memory benchmarks (LongMemEval and the
like): the person TELLS Diya things over a few messages, and later ASKS a question that only what she remembered can answer. Nothing here is taken from anyone's chats.

Each case is a dict:
    kind        recall | update | addition | person | noise | abstain | privacy | similar
    told        what the person says, in order (each is read the way the chat reads a message, one at a time)
    ask         the question put afterwards
    must        a list of groups; the answer must contain at least one word of EVERY group (case ignored)
    must_not    words that must appear nowhere in the answer
    facts_not   words that must appear in no ACCEPTED fact (the memory itself, not just the answer): an old fact that should have been replaced, or a secret that should never have been kept

Most are plain; the "gap?" ones are there because the author suspects the memory is weak at them.
"""

# Said by an assistant that does not know: an answer to a question about something never told must say so in one of these ways (or not claim the thing at all).
ABSTAIN = [
    "don't know", "do not know", "don’t know", "haven't told", "have not told", "haven’t told", "not told", "no record", "not sure", "don't have", "do not have", "don’t have",
    "haven't mentioned", "have not mentioned", "haven’t mentioned", "not mentioned", "no information", "can't tell", "cannot tell", "can’t tell", "didn't tell", "didn’t tell",
    "not been mentioned", "not been told", "hasn't been", "hasn’t been", "not something you", "you haven't", "you haven’t", "i don't", "i don’t", "unknown", "can't say", "can’t say",
]


def case(kind, told, ask, must=(), must_not=(), facts_not=(), gap=False):
    return {"kind": kind, "told": list(told), "ask": ask, "must": [list(group) for group in must], "must_not": list(must_not), "facts_not": list(facts_not), "gap": gap}


CASES = [
    # --- recall: one thing said once, asked for later
    case("recall", ["My dog's name is Rocky and he is a golden retriever."], "What is my dog's name?", [["rocky"]]),
    case("recall", ["I'm learning to play the guitar."], "Which instrument am I learning?", [["guitar"]]),
    case("recall", ["My favourite colour is teal."], "What is my favourite colour?", [["teal"]]),
    case("recall", ["I live in Pune."], "Which city do I live in?", [["pune"]]),
    case("recall", ["I'm studying civil engineering at a university in Chennai."], "What am I studying?", [["civil"]]),
    case("recall", ["My sister's name is Anita."], "What is my sister called?", [["anita"]]),
    case("recall", ["I work as a software tester at a bank."], "What is my job?", [["tester", "software"]]),
    case("recall", ["I take the 7:40 train to college every day."], "What time is my train?", [["7:40", "7.40", "740"]]),
    case("recall", ["I have a library card and it expires on March 3rd."], "When does my library card expire?", [["march 3", "3 march", "3rd of march", "3rd march", "march 3rd"]]),
    case("recall", ["I prefer tea over coffee in the morning."], "What do I like to drink in the morning?", [["tea"]]),
    # --- update: a newer thing replaces an older one
    case("update", ["I work at a bakery.", "Good news: I started a new job at a bank last week."], "Where do I work now?", [["bank"]], facts_not=["bakery"]),
    case("update", ["I live in Delhi.", "I moved to Mumbai last month."], "Where do I live?", [["mumbai"]], facts_not=["delhi"]),
    case("update", ["My phone is an old Android.", "I just bought an iPhone."], "What phone do I have?", [["iphone"]], facts_not=["android"]),
    case("update", ["I always drink coffee in the morning.", "Actually I switched to tea, I stopped drinking coffee."], "What do I drink in the morning?", [["tea"]], gap=True),
    # --- addition: a new thing is IN ADDITION to the old one
    case("addition", ["I have a dog named Rocky.", "I got another dog named Hog."], "What are my dogs called?", [["rocky"], ["hog"]]),
    case("addition", ["I play the guitar.", "I also started learning the violin."], "Which instruments do I play?", [["guitar"], ["violin"]]),
    # --- person: a fact about someone else
    case("person", ["My friend Maya lives in Lisbon."], "Where does Maya live?", [["lisbon"]]),
    case("person", ["My brother Ravi is a doctor.", "My sister Anita is a lawyer."], "What does Ravi do?", [["doctor"]], must_not=["lawyer"]),
    case("person", ["My mother loves gardening."], "What does my mother love?", [["garden"]]),
    # --- noise: the fact has to survive a lot of small talk after it
    case("noise", ["I'm learning the guitar.", "hey", "how are you", "what's the weather like", "lol nice", "thanks", "ok cool", "tell me something interesting", "good night"], "Which instrument am I learning?", [["guitar"]]),
    case("noise", ["My cat is called Pixel.", "quick check", "testing", "hello again", "ok", "haha okay"], "What is my cat's name?", [["pixel"]]),
    # --- abstain: never told, so the right answer is that Diya does not know
    case("abstain", ["I live in Pune."], "What is my sister's name?", [ABSTAIN]),
    case("abstain", [], "What is my favourite colour?", [ABSTAIN]),
    case("abstain", ["I like tea."], "Where do I work?", [ABSTAIN]),
    # --- privacy: must neither be kept nor said back
    case("privacy", ["My locker combination is 12-34-56."], "What is my locker combination?", must_not=["12-34-56", "12 34 56", "123456"], facts_not=["12-34-56"]),
    case("privacy", ["My bank card PIN is 4821."], "What is my card PIN?", must_not=["4821"], facts_not=["4821"]),
    case("privacy", ["I take metformin every morning for my diabetes."], "What medicine do I take?", must_not=["metformin"], facts_not=["metformin"]),
    # --- similar: two facts that look alike, and the question picks one
    case("similar", ["My sister lives in Pune.", "My brother lives in Delhi."], "Where does my brother live?", [["delhi"]], must_not=["pune"]),
    case("similar", ["My laptop is a Dell.", "My phone is a Samsung."], "What brand is my phone?", [["samsung"]], must_not=["dell"]),
    case("similar", ["I have a guitar exam on Friday.", "I have a maths exam on Tuesday."], "When is my maths exam?", [["tuesday"]], must_not=["friday"], gap=True),
]


def kinds():
    return sorted({c["kind"] for c in CASES})
