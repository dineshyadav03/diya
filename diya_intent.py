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

import diya_repeat

MAX_CHARS = 400
MAX_SENTENCES = 3
MAX_ACK_WORDS = 30

# A message that starts with one of these is asking or telling Diya to do something.
_REQUEST_START = re.compile(
    r"^(what|when|where|who|whom|whose|which|why|how|is|are|was|were|do|does|did|can|could|would|"
    r"should|will|shall|may|might|please|tell|give|show|explain|write|make|find|search|look|remind|"
    r"set|add|create|list|open|call|send|book|schedule|help|let's|lets|check|get|bring|order|"
    r"translate|summarize|summarise|calculate|compare|recommend|suggest|plan|read|delete|remove|"
    r"cancel|turn|play|stop|start|forget|note|automate|try|run|ask|say|use)\b",  # automate...use: found on the owner's own chat, where "automate whats the weather in bangalore" was read for facts
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


# A greeting, a thank-you, a goodbye or "how are you" and nothing else (docs/SPEED_DESIGN.md). Such a message cannot need a tool, and the eight tools' descriptions are about 1,000 tokens that the
# model must read before it may answer "hey": about 13 seconds of the 20 the first message after a pause took on this computer's CPU. Deliberately narrow, like is_fact_share: a message that is
# anything more (a name, a question, a number, "yes" or "ok", which may be the answer to an offer that needs a tool) is not small talk, and missing one only means the tools are offered as before.
_GREETING = r"(?:hi+|hey+|hello+|hiya|howdy|yo|sup|good\s+(?:morning|afternoon|evening|night)|(?:morning|afternoon|evening)|gm|gn)"
_VOCATIVE = r"(?:there|diya|buddy|friend|again|everyone|all)"
_THANKS = r"(?:thanks?|thank\s+you|thx|ty|cheers|much\s+appreciated)(?:\s+(?:so\s+much|a\s+lot|very\s+much|diya))?"
_GOODBYE = r"(?:bye+|goodbye|good\s+bye|see\s+(?:you|ya)(?:\s+(?:later|soon|tomorrow))?|ttyl|cya|later)"
_HOW_ARE_YOU = r"(?:how\s+are\s+(?:you|u)(?:\s+(?:doing|today))?|how'?s\s+it\s+going|how\s+do\s+you\s+do|what'?s\s+up|wass?up|how\s+have\s+you\s+been)"
_SMALL_TALK = re.compile(
    rf"(?:{_GREETING}(?:\s+{_VOCATIVE})*|{_THANKS}|{_GOODBYE})?\s*(?:{_HOW_ARE_YOU})?(?:\s+{_VOCATIVE})?",
    re.IGNORECASE,
)
MAX_SMALL_TALK_CHARS = 40


def is_small_talk(text):
    """True only for a greeting, thanks, goodbye or "how are you" (or a greeting followed by one), with nothing else in the message."""
    if not isinstance(text, str):
        return False
    words = re.sub(r"[^\w\s']", " ", text.replace("’", "'")).strip()  # punctuation and emoji go; an apostrophe stays ("how's")
    words = re.sub(r"\s+", " ", words).strip("' ")
    if not words or len(text) > MAX_SMALL_TALK_CHARS:
        return False
    return _SMALL_TALK.fullmatch(words) is not None


# A question about something the person did ("when did I buy the guitar strings?", "did I call the bank?", "have I paid the rent yet?", "what have I finished?"). Whether and when they did it can only be
# answered from what they ticked off, so such a question is given the done reminders and tasks (diya.Agent._done_note) instead of being left to the model to remember to ask for them: measured, a
# 4B model asked "when did i buy new guitar" searched the notes and answered about barre chords.
_DONE_QUESTION = re.compile(
    r"\bwhen\s+(?:did|was)\s+i\b"
    r"|^\W*(?:(?:and|so|also|hey|diya)[\s,]+)*(?:did|have|had)\s+i\s+(?:already\s+|ever\s+|actually\s+|finally\s+)?\w+"
    r"|^\W*(?:and\s+|so\s+)?what\s+(?:did|have)\s+i\s+(?:already\s+|actually\s+)?(?:done|do|finish\w*|complet\w*|bought|buy|got|get|tick\w*|paid|pay)\b"
    r"|\b(?:reminders?|tasks?|things)\s+(?:have\s+)?i(?:'ve)?\s+(?:already\s+)?(?:done|completed|finished|ticked)\b",
    re.IGNORECASE,
)
MAX_DONE_QUESTION_CHARS = 200


def is_done_question(text):
    """True for a question about something the person did or has not yet done, in the patterns above. Deliberately narrow: a miss only means the model answers as it always did."""
    if not isinstance(text, str) or len(text) > MAX_DONE_QUESTION_CHARS:
        return False
    return _DONE_QUESTION.search(text.replace("’", "'")) is not None


# A general question: about the world, not about the person, Diya's own lists or Diya herself. Such a question is one the web can answer, so it is looked up when it needs today's facts
# (wants_lookup) and when the model gave up on it (gave_up) instead of the person being told to look it up themselves. Deliberately narrow, like the checks above: a miss only means the
# model answers as it always did.
_ABOUT_THEM_OR_DIYA = re.compile(r"\b(?:i|i'm|i've|i'll|i'd|my|me|mine|myself|we|our|you|your|u|ur|diya)\b", re.IGNORECASE)
_OWN_THINGS = re.compile(
    r"\b(?:weather|temperature|forecast|tasks?|reminders?|notes?|automations?|calendar|schedule|todo|to-do|memory|facts?|chats?|history|connections?|actions?)\b"
    r"|\b(?:current|working|this)\s+(?:folder|directory|dir|path)\b|\bwhat\s+files\b",  # "what files are in the current folder" is about this computer, and "current" is not a news word here
    re.IGNORECASE,
)
# Arithmetic ("what's 9 times 7", "what is 15% of 80", "what is 2+2"): the model, or a calculator, answers it; the web does not. Measured 2026-10-14 by the real-model evals: "What's 9 times 7?" was
# taken for "what is <a short name>" and searched on the web.
_ARITHMETIC = re.compile(
    r"\d\s*(?:[+*/x\u00d7\u00f7^]|\s-\s|times|plus|minus|divided|multiplied|over|squared|cubed|percent|%)\s*(?:\d|of\b|by\b)|\b(?:square|cube)\s+root\b|\d\s*(?:squared|cubed)\b", re.IGNORECASE
)
_QUESTION_WORD = re.compile(
    r"^\W*(?:and\s+|so\s+|ok\s+|okay\s+)?(?:what|what's|whats|who|who's|whos|when|where|why|how|which|is|are|was|were|does|do|did|can|could|explain|define|tell\s+me\s+(?:about|what|who|how)|describe|compare)\b|\?\s*$",
    re.IGNORECASE,
)
_RECENT = re.compile(
    r"\b(?:latest|current(?:ly)?|right\s+now|today'?s|news|recent(?:ly)?|this\s+(?:week|month|year)|as\s+of|price\s+of|stock\s+price|score|who\s+won|release\s+date|newest|new\s+version|just\s+(?:released|announced)|breaking)\b",
    re.IGNORECASE,
)
_GAVE_UP = re.compile(
    r"\b(?:i\s+(?:do\s*n['’]?t|don['’]?t|dont)\s+(?:really\s+)?(?:know|have\s+(?:any\s+|that\s+|real-?time\s+)?(?:information|info|access|data|record)|recognis?e|understand\s+what)"
    r"|i['’]?m\s+not\s+(?:sure|certain|familiar)|i\s+am\s+not\s+(?:sure|certain|familiar)|i\s+(?:can['’]?t|cannot|can\s*not)\s+(?:confirm|verify|find|provide|access|say|tell)"
    r"|no\s+real-?time\s+(?:access|data|information)|not\s+(?:something|anything)\s+i\s+(?:was\s+)?(?:taught|told)|as\s+of\s+my\s+(?:last|latest)\s+(?:update|knowledge)"
    r"|(?:check|visit|consult)\s+(?:the\s+)?(?:official|their)\s+(?:website|site)|i\s+recommend\s+checking)",
    re.IGNORECASE,
)
MAX_LOOKUP_QUESTION_CHARS = 300
# "what is Opus", "who is Sam Altman": a short name or term being asked about. A small model answers these from a half-remembered guess, confidently and wrongly (measured: "what is Opus" came back as
# "a large language model developed by OpenAI"), so they are searched first like a question that needs today's facts. Not "what is the time" or "what is that", which are not about a thing in the world.
_DEFINITION = re.compile(r"^\W*(?:and\s+)?(?:what|who)(?:\s+is|\s+are|\s+was|\s+were|['’]s)\s+(?:(?:an?|the)\s+)?(?P<subject>[\w.+#-]+(?:\s+[\w.+#-]+){0,2})\W*$", re.IGNORECASE)
_NOT_A_THING = re.compile(
    r"\b(?:time|date|day|today|tomorrow|yesterday|now|this|that|these|those|it|there|here|happening|going|wrong|next|left|up|new|name|plan|point|problem|answer|difference|best|good|bad"
    r"|of|in|on|for|to|with|between|from|and|or|by|at)\b",  # a phrase with these in it ("the capital of Australia") is a question for the model, not a name to look up
    re.IGNORECASE,
)
_CLOCK = re.compile(r"^\W*(?:what|whats|what['’]s)(?:\s+is)?\s+(?:the\s+|today['’]?s\s+)*(?:current\s+)?(?:time|date|day)\b", re.IGNORECASE)  # the computer's clock is not on the web


def _is_general_question(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_LOOKUP_QUESTION_CHARS or "\n" in text.strip():
        return False
    return bool(_QUESTION_WORD.search(text)) and not _ABOUT_THEM_OR_DIYA.search(text) and not _OWN_THINGS.search(text) and not _ARITHMETIC.search(text)


def wants_lookup(text):
    """A general question that needs today's facts (who the current head of something is, the latest news, a price or score), or asks what a short name or term is: searched before the model
    answers, because a small model answers these from what it learned long ago, from a guess, or says it cannot know."""
    if not _is_general_question(text) or _CLOCK.match(text):
        return False
    if _RECENT.search(text):
        return True
    asked = _DEFINITION.match(text)
    return bool(asked) and not _NOT_A_THING.search(asked.group("subject"))


def is_lookup_question(text):
    """Any general question, for the second chance after the model gave up on it."""
    return _is_general_question(text)


def gave_up(answer):
    """Did the answer say the model does not know, cannot confirm or has no access (or send the person off to look it up themselves)?"""
    return isinstance(answer, str) and bool(_GAVE_UP.search(answer[:400]))


# A first-person word anywhere in a message: the person is saying something about themselves, however else the message is shaped.
_SAYS_SOMETHING_OF_ME = re.compile(r"\b(?:i|i'm|i've|i'll|i'd|my|we|we're|we've|our)\b", re.IGNORECASE)


def only_asks(text):
    """True if the message only asks or tells Diya something and says nothing in the first person: a question, or a request, with no "I", "my" or
    "we" in it ("what's a good name for a kitten?", "remind me what a monad is"). There is nothing about the person in it for memory to read, and
    measured (docs/AUTO_MEMORY_DESIGN.md, section 10) a model handed only such messages invents a fact from them. A message that mixes a statement
    about someone else with a question ("Maya got a new job, any gift ideas?") is read as only asking too, and its fact is not taken in live: the
    price of the rule, said here so it is chosen and not found."""
    if not isinstance(text, str):
        return False
    text = text.strip().replace("\u2019", "'")
    if not text:
        return True
    asks = "?" in text or _REQUEST_START.match(text) is not None or _REQUEST_ANYWHERE.search(text) is not None
    return asks and _SAYS_SOMETHING_OF_ME.search(text) is None


# ---- is the person correcting something Diya knows? (docs/AUTO_MEMORY_DESIGN.md, D4 and unit A3) ----
#
# A correction is what lets a fact replace the one it contradicts WITHOUT a question: the model has said which known fact the new one replaces, and the person's
# own words say they are changing something ("no, I live in Pune", "I no longer drink tea", "I moved", "that's wrong"). Both are needed; either alone only asks.
# A short list of the ways people say it, in code: missing an unusual phrasing is the safe direction (the person is asked instead).
_CORRECTION = re.compile(
    r"^\s*(?:no|nope|nah)\b[\s,.!:;-]"
    r"|\bactually\b"
    r"|\bthat(?:'s| is)\s+(?:wrong|not\s+(?:right|true|correct)|incorrect|outdated|old)\b"
    r"|\b(?:not|isn't|aren't|don't|doesn't|didn't)\b[^.!?;]*\b(?:any\s?more|any\s?longer)\b"
    r"|\bany\s?more\b|\bno\s+longer\b|\bnot\s+any\s?longer\b"
    r"|\b(?:stopped|quit|gave\s+up|sold|moved|switched|changed|left)\b"
    r"|\bused\s+to\b"
    r"|\bnow\s+(?:work|works|live|lives|use|uses|drive|drives|have|has|ride|rides|study|studies|go|goes|am|play|plays|prefer|prefers)\b"
    r"|\bis\s+gone\b"
    # Added 2026-10-16 after the memory question-and-answer measurement (docs/MEMORY_BENCH.md): "I started a new job at a bank" and "I just bought an iPhone" are changes too, and were only asked about.
    # The model must still name the fact they replace, so a word here alone replaces nothing.
    r"|\b(?:started|began|landed|took|got)\s+(?:a\s+)?new\s+(?:job|role|position|place|flat|apartment|house|home|phone|laptop|car|bike|course|school|college)\b"
    r"|\bjust\s+(?:bought|started|joined|moved|switched|changed|upgraded|quit|left)\b"
    r"|\b(?:bought|got)\s+(?:a\s+)?new\s+(?:phone|laptop|car|bike|computer|watch)\b"
    r"|\bupgraded\b|\breplaced\b|\bstarted\s+(?:working|studying|living|using)\b",
    re.IGNORECASE,
)


def is_correction(text):
    """True if the message reads as the person changing something already said ("no, I live in Pune", "I no longer drink tea", "I moved flats",
    "that's wrong"). Words only: it is one half of the test for replacing a known fact without asking, the other being the model's answer to which
    fact the new one replaces. Not a question."""
    if not isinstance(text, str):
        return False
    text = text.strip().replace("\u2019", "'")
    return bool(text) and "?" not in text and _CORRECTION.search(text) is not None


# ---- "forget that I said ..." and "forget everything about Maya" ----
_FORGET = re.compile(r"^\s*(?:please\s+)?(?:forget|stop\s+remembering|delete)\s+(?:about\s+|that\s+|what\s+i\s+(?:said|told\s+you)\s+(?:about\s+)?)?(.+?)\s*[.!]?\s*$", re.IGNORECASE)
_FORGET_PERSON = re.compile(r"^(?:everything|anything|all|what\s+you\s+know)\s+(?:about|on|of)\s+(.+)$", re.IGNORECASE)


def forget_target(text):
    """What the person asked Diya to forget, or None if the message is not that: ("person", "Maya") for "forget everything about Maya", ("fact", "I like
    tea") for "forget that I like tea". Only the words are read here; whether anything matches is for the memory to say. A question is not an order."""
    if not isinstance(text, str):
        return None
    text = text.strip().replace("\u2019", "'")
    if not text or "?" in text or len(text) > MAX_CHARS:
        return None
    found = _FORGET.match(text)
    if not found:
        return None
    what = found.group(1).strip()
    person = _FORGET_PERSON.match(what)
    if person:
        name = person.group(1).strip(" .!")
        return ("person", name) if name and len(name.split()) <= 4 else None
    return ("fact", what) if what else None


def is_worth_capturing(text):
    """True if memory should read this message for facts the moment it is said (docs/AUTO_MEMORY_DESIGN.md, unit A4): a first-person statement (or
    "remember that ..."), short, not a question, not a request, a reminder or a task. Stricter than it needs to be on purpose: what it lets by is read
    by the model at once, and everything else is still read by the scheduled Dreaming pass within the half hour. A negative is fine here ("I don't like
    spicy food" is a fact), unlike in is_fact_share, which also decides whether a reply is shortened."""
    if not isinstance(text, str):
        return False
    text = text.strip().replace("\u2019", "'")
    if not text or len(text) > MAX_CHARS or "?" in text:
        return False
    # A correction often starts with something else ("no, I live in Pune", "actually I work at a bank"): it is read if it says something about the person
    if not (_FIRST_PERSON.match(text) or _KEEP_THIS.match(text) or (is_correction(text) and _SAYS_SOMETHING_OF_ME.search(text))):
        return False
    if _REQUEST_ANYWHERE.search(text) or _REMINDER_REQUEST.search(text) or is_task_request(text):
        return False
    return True


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


# ---- did the person ask for a reminder? (docs/PROACTIVITY_DESIGN.md, D9) ----
#
# A reminder that fires is louder than one that sits in a table, and a small model saves reminders nobody asked
# for. So Agent.add_reminder saves nothing unless the latest message asks for one. The test is a short list of
# the ways people ask; missing an unusual phrasing is the safe direction (they can say "remind me to ...").
_REMINDER_REQUEST = re.compile(
    r"\bremind\s+(?:me|us|myself|ourselves)\b"
    r"|\b(?:set|add|create|make|schedule|save|put|give)\s+(?:me\s+|us\s+)?(?:a|an|another|the|this|that|new)?\s*(?:new\s+)?(?:reminder|alarm)\b"
    r"|\b(?:a|an|another|new)\s+reminder\s+(?:to|for|about|that|at|on|in)\b"
    r"|\b(?:don'?t|do\s+not)\s+(?:let\s+me\s+)?forget\b"
    r"|\bnever\s+let\s+me\s+forget\b"
    r"|\bremember\s+to\b"
    r"|\bnote\s+to\s+self\b"
    r"|\bmake\s+a\s+note\b",
    re.IGNORECASE,
)


# ---- did the person ask for a task to be added? (docs/ACTIONS_DESIGN.md, D6 and unit A4) ----
#
# A proposal is only recorded, never performed, but a small model proposes tasks nobody asked for (measured: docs/
# ACTIONS_DESIGN.md, section 6), and a page of cards to turn down teaches clicking without reading. So Agent._propose
# refuses a task proposal unless the latest message asks for one. Like the reminder test it is a short list of the ways
# people ask; missing an unusual phrasing is the safe direction (they can say "add a task to ...").
_TASK_NOUN = r"(?:task|to-?do)"
_TASK_REQUEST = re.compile(
    # "add a task", "create a Todoist task", "make a new to-do", "log one more task", "add task call mum"
    r"\b(?:add|create|make|log|put|save|enter|record|jot\s+down)\s+(?:me\s+|us\s+)?(?:a|another|one\s+more|the|this|that)?"
    r"\s*(?:new\s+)?(?:todoist\s+)?" + _TASK_NOUN + r"\b"
    # "add 'x' to my Todoist", "put it on my to-do list", "add to my task list: x"
    r"|\b(?:add|put|save|log|enter|record)\b.{1,120}?\b(?:to|on|in|into|onto)\s+(?:my\s+|the\s+|your\s+)?"
    r"(?:todoist|to-?dos?(?:\s+list)?|task\s*list|tasks)\b"
    # a line that says it is one: "new task: pay the bill", "todoist: add stamps", "todo: call the bank"
    r"|^\s*(?:todoist|new\s+task|task|to-?do)\s*[:\-]",
    re.IGNORECASE,
)
# A question about the app or about tasks in general is not a request to add one ("how do I add a task in Todoist?").
_TASK_QUESTION = re.compile(r"^\s*(?:how|what|why|where|when|who|which|is|are|does|did|do)\b|^\s*(?:can|could)\s+i\b", re.IGNORECASE)
# ...and neither is telling Diya NOT to ("don't add a task for that"): a negation anywhere refuses it, which also refuses
# the odd real request that contains one -- the safe direction, since the person can say it again without.
_TASK_NEGATED = re.compile(r"\b(?:don'?t|do\s+not|never|stop|without|no\s+need\s+to|not\s+to)\b", re.IGNORECASE)


def is_task_request(text):
    """True if the message asks for a task to be added to the to-do list ("add a task to ...", "put x on my to-do list",
    "new task: ..."). Not a question about Todoist, not a look at the list, not a need or a reminder, not an instruction
    NOT to add one: those are False, as is anything that is not text."""
    if not isinstance(text, str):
        return False
    text = text.replace(chr(0x2019), "'")
    return bool(_TASK_REQUEST.search(text)) and not _TASK_QUESTION.match(text) and not _TASK_NEGATED.search(text)


_MENTIONS_REPEAT = re.compile(r"\b(?:every|each|daily|weekly|monthly|weekdays?|hourly|yearly|annually|recurring|repeat\w*)\b", re.IGNORECASE)


def mentions_repeat(text):
    """Does the message say anything about repeating ("every", "each", "daily", "weekly" ...)? Not whether it asks for a repeat, or
    that it can be read: only that the person talked about one, so a repeat the model passed that is NOT in their words means the
    model garbled theirs (ask again) and not that it made one up (leave it out). docs/SCHEDULE_DESIGN.md, D7."""
    return isinstance(text, str) and _MENTIONS_REPEAT.search(text) is not None


# What may sit between "remind me" and a repeat for the repeat to be part of the request: the reminder's own content ("... to take
# my pills every day at 8am"), but not another clause ("... to call mum tomorrow, I do it every Sunday").
_NEW_CLAUSE = re.compile(r"[.!?;]|,\s*(?:i|we|he|she|they|it|and|but)\b|\b(?:because|but|although|though|since|whereas|while)\b", re.IGNORECASE)
# What may follow a repeat that is part of a request: the content ("... every day at 8am to take my pills"), the end, or a pause. Anything
# else ("... every day except Sunday") might change what was said, and is not guessed at.
_CONTENT_FOLLOWS = re.compile(r"\s*(?:$|[.!?,;:]|(?:to|that|about|for|please|thanks)\b)", re.IGNORECASE)
_LEAD_IN = re.compile(r"[\s,:;.-]*(?:(?:please|and|then|just|can you|could you|would you|will you)[\s,]*)*", re.IGNORECASE)


def attached_repeat(text, now=None):
    """The person's own words for a repeat that is part of their request for a reminder ("Remind me every Monday at 9am to ...",
    "Every Monday at 9am, remind me to ...", "Set a reminder to ... every day at 8am"), or None: no reminder asked for, no repeat
    that diya_repeat reads, or a repeat that is part of something else ("remind me to call mum tomorrow, I do it every Sunday") or
    is followed by words that could change it ("every day except Sunday"). docs/SCHEDULE_DESIGN.md, D7."""
    found = diya_repeat.find_repeat(text, now)  # None for anything that is not text
    request = _REMINDER_REQUEST.search(text.replace(chr(0x2019), "'")) if found else None
    if request is None:
        return None
    if found.start >= request.end():  # the request first, the content and the repeat after it
        if _NEW_CLAUSE.search(text[request.end():found.start]) or not _CONTENT_FOLLOWS.match(text[found.end:]):
            return None
        return found.words
    if found.end <= request.start():  # the repeat first: "Every Monday at 9am, remind me to ..."
        return found.words if _LEAD_IN.fullmatch(text[found.end:request.start()]) else None
    return None


_TODOIST = re.compile(r"\btodoist\b", re.IGNORECASE)


def names_todoist(text):
    """True if the message says Todoist. A task asked for by name in Todoist is Todoist's; any other is Diya's own list's
    (docs/TASKS_DESIGN.md, D6) -- decided here, in code, so the two tools never compete for the same message."""
    return isinstance(text, str) and _TODOIST.search(text) is not None


def is_todoist_task_request(text):
    """A request for a task (is_task_request) that names Todoist: the only kind a Todoist task is proposed for."""
    return names_todoist(text) and is_task_request(text)


def said_in(phrase, text):
    """Is `phrase` (a due date, say) among the person's own words? Whole words, any capitals, spaces and the full stop or
    comma after it ignored -- "tomorrow" in "add it for Tomorrow." yes, "day" in "Monday" no. Anything that is not text,
    and an empty phrase, is not."""
    if not isinstance(phrase, str) or not isinstance(text, str):
        return False
    phrase = " ".join(phrase.lower().split()).strip(" .,;:!?")
    words = " ".join(text.lower().split())
    return bool(phrase) and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", words) is not None


def is_reminder_request(text):
    """True if the message asks for a reminder ("remind me to ...", "set a reminder", "don't let me forget ...").
    Not a question about reminders, not a fact, not a sum: those are False, as is anything that is not text."""
    if not isinstance(text, str):
        return False
    return bool(_REMINDER_REQUEST.search(text.replace(chr(0x2019), "'")))


# ---- is this a question about what the person's own notes say? (docs/KNOWLEDGE_DESIGN.md, step 3) ----
#
# Decided here, in code, like the other gates: the chat answers such a question from the person's page about the name in it (diya.Agent._pages_note), with no tools. It must be a question or a request
# to look (not a thing to write down, not a reminder), and it must talk about the person's notes or what they wrote; which name it is about is found in diya_knowledge.page_for.
_NOTES_FRAME = re.compile(
    r"\bmy\s+notes?\b|\bnotes?\s+(?:say|said|mention\w*|about|on)\b|\b(?:i|we)(?:'ve|\s+have|\s+had)?\s+(?:written|wrote|noted|jotted|saved)\b"
    r"|\b(?:did|do|does|have|had)\s+(?:i|we)\s+(?:ever\s+)?(?:write|wrote|written|note|noted|jot|jotted|save|saved)\b",
    re.IGNORECASE,
)
_NOTES_ASK = re.compile(
    r"^\W*(?:(?:hey|hi|ok|okay|please|diya|and|so)\b[\s,]*)*(?:what|which|who|where|when|why|how|anything|everything|whatever|do|did|does|have|has|had|is|are|was|were|can|could|would|tell|show|give|list|"
    r"summari[sz]e|find|search|look|read|pull|check)\b|\?\s*$",
    re.IGNORECASE,
)
_NOTES_WRITE = re.compile(
    r"(?:^|[.!?;:,]\s*|\b(?:please|can\s+you|could\s+you|would\s+you|will\s+you|and|then)\s+)\W*(?:add|put|save|write|store|jot|keep|append|record)\b[^.?!]*\b(?:in|to|into|on)\s+my\s+notes?\b"
    r"|\bmake\s+a\s+note\b|\bnote\s+(?:that|to\s+self)\b",
    re.IGNORECASE,
)
MAX_NOTES_QUESTION_CHARS = 300


def repo_to_study(text):
    """(owner, repo) if the message gives a GitHub repository address and asks for it to be studied, explained or looked into; else None (diya_repostudy.wants_study)."""
    import diya_repostudy

    return diya_repostudy.repo_from_text(text) if diya_repostudy.wants_study(text) else None


def asks_about_notes(text):
    """True if the message asks what the person's own notes say ("what do my notes say about Maya?", "anything I wrote about the trip?"). Not something to be written down ("add this to my notes"), not a
    reminder, and not anything that is not one short piece of text: those are False."""
    if not isinstance(text, str) or len(text) > MAX_NOTES_QUESTION_CHARS or "\n" in text:
        return False
    text = text.replace(chr(0x2019), "'")
    return bool(_NOTES_FRAME.search(text)) and bool(_NOTES_ASK.search(text)) and not _NOTES_WRITE.search(text) and not is_reminder_request(text)


# ---- a greeting is tidied in code (docs/SPEED_DESIGN.md, "Greetings are tidied") ----
#
# Measured on 2026-10-14 with the real chat model and a greeting each time: with nothing in memory, 8 of 12 replies addressed the person by a name nobody had given ("Good morning, Alex!"), the name in memory
# was ignored (Alex, Maya and Anna for a user called Priya), "Good morning" was said in the afternoon, and the prompt's "no emoji" and "never say how can I assist you" were not kept. A prompt did not hold a model
# of this size to any of it, so what the person sees is made right here, after the model has written it: a name that is not the person's is removed, the part of the day is the real one, no emoji, and no offer
# to assist. The model still writes the greeting; code only takes out what it had no way of knowing.
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\u2B55\uFE0F\u200D]")
_OPENER = r"(?:hi+|hey+|hello+|hiya|howdy|good\s+(?:morning|afternoon|evening|night)|morning|afternoon|evening|welcome\s+back|thanks|thank\s+you|you['’]re\s+welcome|bye+|goodbye|see\s+you)"
_ADDRESSED = re.compile(rf"^(?P<open>\W*(?i:{_OPENER})(?:\s+(?:again|there))?)(?P<comma>\s*,)?\s+(?P<name>[A-Z][a-z]{{1,20}})(?P<after>[,!.?]?)(?=\s|$)")
_NOT_A_NAME = frozenset(
    "how what i it its you your youre glad hope nice great happy welcome sorry good have let lets take enjoy feeling no yes ok okay so well anything everything talk see there again friend everyone all "
    "here this that today tonight tomorrow ready doing hows whats thanks thank hello hi hey".split()
)
_DAYPART = re.compile(r"\bgood\s+(?:morning|afternoon|evening)\b", re.IGNORECASE)  # "good night" is a goodbye at any hour: left alone
_USER_SAID_A_PART = re.compile(r"\b(?:morning|afternoon|evening|night|gm|gn)\b", re.IGNORECASE)
_OFFER = re.compile(r"\b(?:how\s+(?:can|may)\s+i\s+(?:assist|help)|what\s+can\s+i\s+do\s+for\s+you|is\s+there\s+anything\s+(?:else\s+)?i\s+can\s+(?:help|assist))\b", re.IGNORECASE)
_MY_NAME = re.compile(r"^\s*(?:my\s+)?name\s+is\s+([A-Za-z]{2,20})\s*[.!]?\s*$", re.IGNORECASE)


def known_name(fact_texts):
    """What to call the person: the name in a fact that says "name is X" or "my name is X", else None."""
    for text in fact_texts:
        found = _MY_NAME.match(text) if isinstance(text, str) else None
        if found:
            return found.group(1).capitalize()
    return None


def part_of_day(hour):
    """The greeting for this hour; None in the small hours and late evening, where "good morning" is wrong and "good night" is a goodbye."""
    return "Good morning" if 5 <= hour < 12 else "Good afternoon" if 12 <= hour < 17 else "Good evening" if 17 <= hour < 22 else None


def tidy_small_talk(reply, user_text, name, hour):
    """A model's greeting, thank-you or goodbye made right: a name that is not `name` is taken out, the part of the day is the one it is (unless the person named one), pictures are taken out, and a sentence that
    offers to assist is dropped. It only takes words out, except that it puts the real part of the day where the model wrote another; it never adds a thought of its own."""
    text = _EMOJI.sub("", reply if isinstance(reply, str) else "").strip()
    found = _ADDRESSED.match(text)
    if found:
        called = found.group("name").lower()
        if called != (name or "").lower() and called not in _NOT_A_NAME:  # not who the person is (the model made it up, or took "Diya" for the user)
            text = found.group("open") + (found.group("after") or found.group("comma") or "") + text[found.end():]
    if not _USER_SAID_A_PART.search(user_text or ""):
        first = _DAYPART.search(text)
        if first and not re.search(r"[.!?]", text[: first.start()]):  # only the opening words, where a greeting is
            wanted = part_of_day(hour) or "Hi"
            if first.group(0)[0].islower():
                wanted = wanted[0].lower() + wanted[1:]
            text = text[: first.start()] + wanted + text[first.end():]
    pieces = [piece for piece in re.split(r"(?<=[.!?])\s+", text) if piece and not _OFFER.search(piece)]
    text = " ".join(pieces)
    text = re.sub(r"\s+([,!.?])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()
    return text or "Hi."


# ---- is this a question about Diya herself: what she can do, how to connect or set something up? (2026-10-14) ----
#
# Asked "how do i connect you to my google account" the model answered "I can't connect to Google or any external services ... no connectors", and "what can you do" with a list of things it made up,
# because nothing in what it is told says what Diya really is. Code recognises such a question and gives the model the facts (diya.ABOUT_DIYA_NOTE) for that turn only.
_SERVICE = r"(?:google|calendar|gmail|drive|todoist|notion|home\s*assistant|telegram|account|accounts|connector|connectors|integration|integrations)"
_ABOUT_DIYA = re.compile(
    rf"\b(?:connect|link|sync|integrate|hook\s+up|set\s*up|add)\b[^.?!]{{0,40}}\b{_SERVICE}\b"
    rf"|\b{_SERVICE}\b[^.?!]{{0,30}}\b(?:connect|connected|connection|link|sync|setup|set\s*up)\b"
    r"|\bwhat\s+(?:can|could|do)\s+(?:you|u)\s+(?:do|help\s+(?:me\s+)?with|offer)\b"
    r"|\bwhat\s+(?:are|is)\s+(?:you|your)\s+(?:able\s+to\s+do|features?|abilit\w+|capabilit\w+)\b|\byour\s+(?:features|abilities|capabilities)\b|\bwhat\s+(?:features|connectors|integrations)\s+(?:do\s+you|are)\b"
    rf"|\b(?:do\s+)?(?:you|u)\s+(?:have|got|support)\s+(?:the\s+|a\s+|an\s+|any\s+)?{_SERVICE}\b"
    rf"|\b(?:is|are)\s+there\s+(?:a\s+|an\s+|any\s+)?(?:\w+\s+)?{_SERVICE}\b"
    r"|\bhow\s+(?:do|can|would)\s+(?:i|we)\s+(?:use|turn\s+on|enable|find|open|add|make)\s+(?:the\s+|an?\s+|my\s+)?(?:memory|automations?|knowledge|connections?|reminders?|tasks?|voice|mic(?:rophone)?)\b",
    re.IGNORECASE,
)
MAX_ABOUT_QUESTION_CHARS = 200


def asks_about_diya(text):
    """True if the message asks what Diya can do, or how to connect her to an account or turn a feature on ("how do i connect you to my google account", "what can you do"). Not a statement, not a long
    message, and not anything that is not text."""
    if not isinstance(text, str) or len(text) > MAX_ABOUT_QUESTION_CHARS or "\n" in text:
        return False
    return bool(_ABOUT_DIYA.search(text.replace(chr(0x2019), "'")))
