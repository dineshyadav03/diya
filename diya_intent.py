"""Is this message just the user telling Diya something?

When the user shares a plain fact ("my driving test is on Friday at 9"), the right response is one
short acknowledgement: the message is already saved to the thread and Dreaming stages the fact
for review, so Diya has nothing to store or look up. A small model left to itself instead writes
a paragraph of advice, and -- worse -- reaches for tools nobody asked for (it saves reminders,
runs web searches). Agent.ask uses this to take tools away for those turns and keep the reply
short.

The test is deliberately conservative. Missing a fact-share only means the old, wordy behaviour;
wrongly calling a real request a fact-share would silently swallow it. So a message counts only
when it is clearly first-person, declarative, has something factual in it, and contains no sign
of a question, a command or a need.
"""
import re

MAX_CHARS = 400
MAX_SENTENCES = 3
MAX_ACK_WORDS = 30

# A message that starts with one of these is asking or telling Diya to do something.
_REQUEST_START = re.compile(
    r"^(what|when|where|who|whom|whose|which|why|how|is|are|was|were|do|does|did|can|could|would|"
    r"should|will|shall|may|might|please|tell|give|show|explain|write|make|find|search|look|remind|"
    r"set|add|create|list|open|call|send|book|schedule|help|let's|lets|check|get|bring|order|"
    r"translate|summarize|summarise|calculate|compare|recommend|suggest|plan|read|delete|remove|"
    r"cancel|turn|play|stop|start|forget|note)\b",
    re.IGNORECASE,
)
# ...and these anywhere in it: a need, a wish, a problem, or an address to Diya.
_REQUEST_ANYWHERE = re.compile(
    r"\b(remind me|tell me|let me know|show me|give me|help me|can you|could you|would you|will you|"
    r"do you|are you|please|any idea|i need|i want|i'd like|i would like|i wanna|i'm looking for|"
    r"i am looking for|i wonder|i'm trying|i am trying|i don't know|i do not know|i can't|i cannot|"
    r"i couldn't|i forgot|i'm not sure|i am not sure|i'm stuck|i'm confused|should i|what should|"
    r"how do i|how can i|i have a problem|i have an issue|i have a question|is there|are there|"
    # a bare "help", or a reported problem, means the user wants something back
    r"help|not working|isn't working|isnt working|doesn't work|does not work|won't|broken|crash(ed|es)?|"
    r"bug|bugs|error|errors|failed|failing|problem|problems|issue|issues|trouble|stuck)\b",
    re.IGNORECASE,
)
# A negative or a loss usually means a complaint or a problem the user wants sorted, not a fact to
# file ("my order hasn't arrived"). A plain negative preference then just gets the normal reply.
_NEGATIVE = re.compile(r"\w+n't\b|\bnot\b|\bnever\b|\bno idea\b|\bmissing\b|\blost\b|\blate\b|\bwrong\b|\bstill no\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(r"^(i|i'm|i've|i'll|i'd|my|we|we're|we've|our)\b", re.IGNORECASE)
# "remember that ..." is a fact with an explicit "keep this"; "remember to ..." is a task and is not.
_KEEP_THIS = re.compile(r"^(remember that|note that|fyi|for your information|keep in mind that)[,:]?\s+", re.IGNORECASE)
_MONTH_OR_DAY = re.compile(
    r"\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|"
    r"nov(ember)?|dec(ember)?|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|"
    r"next week|next month|this weekend)\b",
    re.IGNORECASE,
)
_FACT_WORDS = re.compile(
    r"\b(allergic|birthday|appointment|exam|test|flight|meeting|deadline|interview|wedding|anniversary|"
    r"moved|moving|live|lives|living|work at|works at|working at|work for|works for|working for|born|"
    r"called|named|password|code|address|number|"
    r"is on|are on|leaves|leaving|starts|ends|arrives|graduat\w+|got a new|have a new|adopted)\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!])\s+")


def _sentences(text):
    return [s for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def _has_specifics(text):
    """Something factual: a number, a date/day, a name mid-sentence, or a fact-shaped word."""
    if re.search(r"\d", text):
        return True
    if _MONTH_OR_DAY.search(text) or _FACT_WORDS.search(text):
        return True
    words = text.split()
    return any(w[:1].isupper() and w.lower() not in ("i", "i'm", "i've", "i'll", "i'd") for w in words[1:])


def is_fact_share(text):
    """True only for a clear, first-person statement of fact -- never a question, command or need."""
    if not isinstance(text, str):
        return False
    text = text.strip().replace("’", "'")  # phone keyboards send a typographic apostrophe
    if not text or len(text) > MAX_CHARS or "?" in text:
        return False
    keep = _KEEP_THIS.match(text)
    if keep:
        text = text[keep.end():].strip()
    else:
        if not _FIRST_PERSON.match(text):
            return False
    sentences = _sentences(text)
    if not sentences or len(sentences) > MAX_SENTENCES:
        return False
    if _REQUEST_ANYWHERE.search(text) or _NEGATIVE.search(text):
        return False
    for sentence in sentences:
        if _REQUEST_START.match(sentence.strip()):
            return False
    return _has_specifics(text)


def shorten_ack(reply):
    """Keep an acknowledgement to a sentence. Used as a last resort on fact-shares: the prompt
    and the missing tools should already have produced a short reply."""
    text = (reply or "").strip()
    if len(text.split()) <= MAX_ACK_WORDS:
        return text
    first = _sentences(text)[0].strip() if _sentences(text) else ""
    if first and len(first.split()) <= MAX_ACK_WORDS:
        return first
    return "Got it."
