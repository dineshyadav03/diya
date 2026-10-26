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
_KEEP_THIS = re.compile(r"^(remember that|note that|fyi|for your information|keep in mind that|btw|by the way|also|oh and|oh also)[,:]?\s+", re.IGNORECASE)
# Phone typing leaves the apostrophe out ("ive been", "im allergic"); put it back before looking, so the same words are read the same way ("im looking for ..." is then a request, as "i'm looking for" is).
_NO_APOSTROPHE = re.compile(r"\b(i)(ve|m)\b", re.IGNORECASE)
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
    r"is on|are on|leaves|leaving|starts|ends|arrives|graduat\w+|got a new|have a new|adopted|switch(?:ed|ing)?|enrolled|joined|bought|studying|favou?rite)\b",
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
    text = _NO_APOSTROPHE.sub(lambda m: f"{m.group(1)}'{m.group(2)}", text)
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
    # A correction often starts with something else ("no, I live in Pune", "actually I work at a bank"): it is read if it says something about the person, or, since a correction names the thing it
    # corrects by a pronoun ("Actually his name is Hogg, not Hog": the Hog regression, 2026-10-18), if it is a real sentence (four words or more: not "no thanks"). Capture then gives the model the
    # message before it, so that "his" is somebody (dreaming.Dreamer.capture_message).
    if not (_FIRST_PERSON.match(text) or _KEEP_THIS.match(text) or (is_correction(text) and (_SAYS_SOMETHING_OF_ME.search(text) or len(text.split()) >= 4))):
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


# ---- did the person ask for something to be added to their Google account? (docs/GOOGLE_WRITE_DESIGN.md) ----
#
# Same rule as the Todoist task: a proposal is only recorded, never performed, but a small model proposes things nobody asked for, and a page of cards to turn down teaches clicking without reading. So each
# kind of Google write is proposed only when the latest message asks for exactly that thing, in these words; missing an unusual phrasing is the safe direction (they can say it again plainly).
_GOOGLE_TASKS = re.compile(r"\bgoogle\s+tasks?\b", re.IGNORECASE)
_ADD_VERB = re.compile(r"\b(?:add|put|create|make|schedule|book|block|save|log|enter|record|jot\s+down|set\s+up)\b", re.IGNORECASE)
_CALENDAR_WORD = re.compile(r"\bcalendar\b", re.IGNORECASE)
_BOOK_AN_EVENT = re.compile(r"\b(?:schedule|book|set\s+up|block)\s+(?:in\s+)?(?:an?\s+|the\s+|my\s+)?(?:\w+\s+){0,3}?(?:meeting|appointment|event|session|interview|class|lecture)\b", re.IGNORECASE)
_DRIVE_WORD = re.compile(r"\b(?:google\s+)?drive\b", re.IGNORECASE)
_FOLDER_WORD = re.compile(r"\bfolder\b", re.IGNORECASE)
_GOOGLE_DOC = re.compile(r"\bgoogle\s+(?:docs?|documents?)\b", re.IGNORECASE)


def names_google_tasks(text):
    """True if the message says Google Tasks. A task asked for by name in Google Tasks is Google's, as one asked for in Todoist is Todoist's: decided here, in code."""
    return isinstance(text, str) and _GOOGLE_TASKS.search(text) is not None


def _asks_to_add(text):
    """A message that gives an instruction to add something: it has an adding word, and is not a question about how, not a refusal ("don't add ..."), and not a reminder."""
    if not isinstance(text, str):
        return False
    text = text.replace(chr(0x2019), "'")
    return bool(_ADD_VERB.search(text)) and not _TASK_QUESTION.match(text) and not _TASK_NEGATED.search(text) and not is_reminder_request(text)


def asks_for_google_task(text):
    """True if the message asks for a task in Google Tasks, by name ("add buy milk to my Google Tasks")."""
    return names_google_tasks(text) and _asks_to_add(text)


def asks_to_add_calendar_event(text):
    """True if the message asks for an event on the calendar ("put the dentist on my calendar for friday at 5pm", "schedule a meeting with Sam tomorrow at 10"). Not a look at the calendar, not a reminder."""
    return _asks_to_add(text) and (_CALENDAR_WORD.search(text) is not None or _BOOK_AN_EVENT.search(text) is not None)


def asks_for_drive_folder(text):
    """True if the message asks for a folder in Google Drive ("make a folder called Exams in my Drive")."""
    return _asks_to_add(text) and _FOLDER_WORD.search(text) is not None and _DRIVE_WORD.search(text) is not None


def asks_for_google_doc(text):
    """True if the message asks for a Google Doc, by name ("create a Google Doc called Study plan")."""
    return _asks_to_add(text) and _GOOGLE_DOC.search(text) is not None


def said_in(phrase, text):
    """Is `phrase` (a due date, say) among the person's own words? Whole words, any capitals, spaces and the full stop or
    comma after it ignored -- "tomorrow" in "add it for Tomorrow." yes, "day" in "Monday" no. Anything that is not text,
    and an empty phrase, is not."""
    if not isinstance(phrase, str) or not isinstance(text, str):
        return False
    phrase = " ".join(phrase.lower().split()).strip(" .,;:!?")
    words = " ".join(text.lower().split())
    return bool(phrase) and re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", words) is not None


# A reply that says a reminder or a task WAS saved. Used only when the person asked for one and no tool that saves one ran in the turn: then the claim is false, whoever wrote it (found 2026-10-26, replaying the
# owner's long chat: asked "remind me about the dentist", the model answered "I've added a reminder ... Reminder: Don't forget the dentist" and had called nothing).
_CLAIMS_REMINDER = re.compile(
    r"\bi(?:'ve|\s+have)\s+(?:just\s+)?(?:set|added|created|saved|made)\s+(?:a|an|the|your)\s+(?:\w+\s+){0,3}?(?:reminder|alarm)\b|\b(?:reminder|alarm)\s+(?:has\s+been\s+|is\s+)?(?:set|saved|added|created)\b|\*\*reminder\*\*\s*:",
    re.IGNORECASE,
)
_CLAIMS_TASK = re.compile(
    r"\bi(?:'ve|\s+have)\s+(?:just\s+)?(?:added|created|saved|put|made)\s+(?:a|an|the|your)\s+(?:\w+\s+){0,3}?(?:task|to-?do)\b|\btask\s+(?:has\s+been\s+|is\s+)?(?:added|saved|created)\b|\*\*task\*\*\s*:",
    re.IGNORECASE,
)


def claims_a_reminder(reply):
    """Does this reply say that a reminder was set, added or saved?"""
    return isinstance(reply, str) and _CLAIMS_REMINDER.search(reply.replace(chr(0x2019), "'")) is not None


def claims_a_task(reply):
    """Does this reply say that a task was added or saved?"""
    return isinstance(reply, str) and _CLAIMS_TASK.search(reply.replace(chr(0x2019), "'")) is not None


# What looks like a request for a reminder and is not (found by the capture-gate benchmark on 2026-10-26: the code let these through, 4 of 71): a refusal ("please don't set a reminder for that", "never remind me
# again"), a question about the phrase or about how ("what does 'remind me' mean in spanish", "how do i set a reminder on my phone"), and a habit ("i remember to lock the door every night"). Refusing a
# request that was real is the safe direction, and "remind me how to work the thermostat at 6" is still a request: the question rule only reads a message that BEGINS with the question word.
_REMINDER_NOT_A_REQUEST = re.compile(
    r"\b(?:don'?t|do\s+not|never|no\s+need\s+to|stop)\s+(?:\w+\s+){0,2}?(?:set|add|create|make|schedule|save|put|give|remind)\b"
    r"|^\W*(?:what|how|why|where|when)\b[^.!]*\b(?:does|do|is|are|to)\b[^.!]*\b(?:mean|means|meaning|work|works|set\s+(?:up\s+)?(?:a\s+)?(?:reminder|alarm))\b"
    r"|^\W*i\s+(?:always\s+|usually\s+|often\s+|never\s+)?remember\s+to\b",
    re.IGNORECASE,
)


def is_reminder_request(text):
    """True if the message asks for a reminder ("remind me to ...", "set a reminder", "don't let me forget ...").
    Not a question about reminders, not a refusal, not a habit, not a fact, not a sum: those are False, as is anything that is not text."""
    if not isinstance(text, str):
        return False
    text = text.replace(chr(0x2019), "'")
    return bool(_REMINDER_REQUEST.search(text)) and not _REMINDER_NOT_A_REQUEST.search(text)


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


# What the person asks their notes about, as a few words to search for ("what did i write about the garden?" -> "garden"). Found 2026-10-26: asked this with the persona and the list of what is known about them in front of it,
# the small model answered "I don't have access to your notes" instead of calling search_notes (3 of 5 questions, with the old persona as well as the new), so code makes the search and the model only words the answer.
_NOTES_TOPIC = re.compile(
    r"\b(?:about|regarding|on|re)\s+(?:(?:the|a|an|my|any|our)\s+)*([a-z0-9][a-z0-9 '._-]{1,60}?)\s*(?=[?.!,;]|$|\s+(?:in|from|that|which|i|we|last|this|yesterday|today)\b)",
    re.IGNORECASE,
)
_NOTES_TOPIC_ABOUT = re.compile(_NOTES_TOPIC.pattern.replace("(?:about|regarding|on|re)", "(?:about|regarding|re)"), re.IGNORECASE)  # "about" wins over "on" ("what did i write on friday about the exam")


def notes_topic(text):
    """The few words a question about the person's own notes is about ("what did i write about the garden?" -> "garden"), or None if it names none."""
    if not isinstance(text, str):
        return None
    text = text.replace(chr(0x2019), "'")
    found = _NOTES_TOPIC_ABOUT.search(text) or _NOTES_TOPIC.search(text)
    topic = " ".join(found.group(1).split()).strip(" .'-") if found else ""
    return topic if len(topic) >= 2 and topic.lower() not in {"it", "that", "this", "them", "me", "my notes", "notes"} else None


# ---- is the person asking about their own mail? (docs/GMAIL_DESIGN.md) ----
#
# Code decides, in words, so that a question about mail is read by the code that reads mail and answered by a model with no tools. A request to WRITE, send or delete mail is recognised too, and answered
# with the plain fact that Diya's access is read-only. A miss only means the model answers as it always did.
_MAIL_WORD = re.compile(r"\b(?:e-?mails?|inbox|gmail|mails|mail)\b", re.IGNORECASE)
_MAIL_READ = re.compile(
    r"\b(?:check|read|show|find|search|look|any|anything|did|has|have|had|latest|newest|new|unread|recent|summari[sz]e|what|which|who|when|list|open|see|got|received|waiting|from|about|regarding)\b", re.IGNORECASE
)
_MAIL_NOT_ABOUT_MINE = re.compile(
    r"\bhow\s+(?:do|does|did|to|can)\b[^?]*\b(?:work|works|set\s*up|use)\b|\bwhat\s+(?:is|are)\s+(?:an?\s+)?(?:e-?mail|gmail|inbox)\b|\bhistory\s+of\b|\b(?:my\s+)?e-?mail\s+(?:address|id|password)\b|\b(?:connect|link|set\s*up)\b",
    re.IGNORECASE,
)
# "put 'email professor sharma' on my to-do list" holds the word email and the word list, and is a task, not a look through the mailbox (found by the held-out benchmark on 2026-10-26: Diya answered "Gmail is not
# connected" instead of adding the task). A message that is plainly about a to-do list, a task or a reminder is not a question about mail, whatever else it mentions.
_MAIL_IS_A_TO_DO = re.compile(r"\b(?:to-?\s?do|task\s+list|my\s+tasks?|a\s+tasks?|add\s+(?:a\s+)?task|remind(?:ers?|\s+me))\b|^\W*(?:to-?do|task)\s*:", re.IGNORECASE)
_MAIL_WRITE_AT_START = re.compile(r"^\W*(?:please\s+)?(?:(?:can|could|will|would)\s+you\s+)?(?:send|write|draft|compose|forward|delete|archive|trash|unsubscribe|mark|label|move|reply|respond)\b", re.IGNORECASE)
_MAIL_WRITE_ANYWHERE = re.compile(r"\b(?:send|write|draft|compose)\s+(?:an?\s+|the\s+|my\s+|some\s+)?(?:e-?mail|mail|message|reply)\b|\b(?:delete|archive|trash)\s+(?:all\s+|my\s+|the\s+|that\s+|this\s+)?(?:e-?mails?|mails?|messages?)\b", re.IGNORECASE)
MAX_MAIL_QUESTION_CHARS = 300


def _mail_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_MAIL_QUESTION_CHARS or "\n" in text.strip():
        return None
    return text.replace("\u2019", "'")


def wants_mail_written(text):
    """True for a request to send, write, reply to, delete or file mail ("send an email to mum", "delete all my emails"): Diya can read mail and nothing else."""
    text = _mail_text(text)
    return text is not None and _MAIL_WORD.search(text) is not None and (_MAIL_WRITE_AT_START.search(text) is not None or _MAIL_WRITE_ANYWHERE.search(text) is not None)


def asks_about_mail(text):
    """True for a short question or request to look through the person's own mail ("any email from the college?", "what did the bank email say", "check my inbox"). Not a request to write mail, not
    a question about mail in general ("what is gmail", "how does email work", "what is my email address"), and not about connecting it (asks_about_diya)."""
    text = _mail_text(text)
    if text is None or wants_mail_written(text) or _MAIL_IS_A_TO_DO.search(text):
        return False
    return _MAIL_WORD.search(text) is not None and _MAIL_NOT_ABOUT_MINE.search(text) is None and _MAIL_READ.search(text) is not None


# After Diya has told the person what her search of their mail found, a short message that argues with it ("but there are mails", "check again", "are you sure?") is a request to look again, not a new
# subject: without this the model, which has no mail tool, told the owner it had no access to Gmail at all (2026-10-26, the first day Gmail was connected). Used only when the answer before was a mail report.
_MAIL_DISPUTE = re.compile(
    r"\b(?:but|there\s+(?:are|is|were|must\s+be)|i\s+(?:do\s+)?(?:have|got|see)|are\s+you\s+sure|really|wrong|not\s+true|that'?s\s+not\s+(?:right|true)|you\s+missed)\b|\b(?:check|look|search|try|read)\s+(?:it\s+)?again\b",
    re.IGNORECASE,
)
MAX_DISPUTE_CHARS = 90


def disputes_mail_answer(text):
    """True for a short one-line message that disputes or repeats a look through the mail ("but there are mails", "i have emails", "check again", "are you sure?"). Meaningful only straight after a mail report."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_DISPUTE_CHARS or "\n" in text.strip():
        return False
    text = text.replace("’", "'")
    again = re.search(r"\b(?:check|look|search|try|read)\s+(?:it\s+)?again\b", text, re.IGNORECASE) is not None
    return again or (_MAIL_DISPUTE.search(text) is not None and (_MAIL_WORD.search(text) is not None or re.search(r"\bare\s+you\s+sure\b|\byou\s+missed\b", text, re.IGNORECASE) is not None))


def mentions_mail(text):
    """Does the message use a word for email (email, mail, inbox, gmail)? Used only to decide whether to tell the model that Gmail is connected."""
    return isinstance(text, str) and _MAIL_WORD.search(text) is not None


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


# ---- short plain replies, like Hark's (2026-10-26) ----
#
# The owner put Diya's replies beside Hark's and asked for them to be short: Diya's had emoji, "Why? To help test my own system", "Want me to ... ?", "Just say the word", a P.S. about the dog, and an opening
# "You're absolutely right and thank you for calling that out". The persona now says how to answer (diya.PERSONA), and this takes out what a small model still adds after being told not to. It only TAKES OUT, and
# only these things: pictures, a closing offer, a P.S., and a one-word praise at the start. It never rewrites, adds, or touches anything in a code block.
EMOJI = _EMOJI
_PICTURES = re.compile(f"(?:{_EMOJI.pattern})+[ \\t]?")  # a run of pictures and the one space after it, so "🔥 **Bold**" does not leave a space at the start of the line
_OFFER_START = re.compile(
    r"^\W*(?:want\s+me\s+to|would\s+you\s+like(?:\s+me\s+to)?|do\s+you\s+want\s+me\s+to|let\s+me\s+know|feel\s+free\s+to|just\s+(?:say|ask|tell\s+me)|if\s+you(?:['’]d|\s+would)\s+like|if\s+you\s+want|"
    r"i['’]m\s+(?:always\s+)?here\s+(?:to|if|for|whenever)|i\s+can\s+also\s+(?:help|do|set|add)|hope\s+(?:this|that)\s+helps|is\s+there\s+anything\s+else|anything\s+else\s+(?:i|you)|need\s+anything\s+else|"
    r"happy\s+to\s+help)\b",
    re.IGNORECASE,
)
_POSTSCRIPT = re.compile(r"(?:^|(?<=\s))(?:\*\*)?(?:P\.\s?S\.?|PS:)(?:\*\*)?[:.\s].*\Z", re.IGNORECASE | re.DOTALL)
_FILLER_OPEN = re.compile(r"^\W*(?:sure|absolutely|of\s+course|certainly|great\s+question|good\s+question|nice\s+question)[!.]\s+", re.IGNORECASE)
_RIGHT_OPEN = re.compile(r"^\W*you['’]re\s+(?:absolutely\s+|totally\s+|completely\s+)?right\b[^.!?\n]{0,70}[.!?]\s+", re.IGNORECASE)


# The persona tells the model to be honest about being small WHEN ASKED; a fact answer ended "I'm smaller than cloud models like Claude or GPT" with nobody asking (2026-10-26). A sentence like that is taken out
# unless the person's own message was about the model, what it is, or how it compares.
_SMALLNESS = re.compile(r"\bsmaller\s+than\s+(?:the\s+)?(?:cloud|big|larger|bigger|other)\b|\bsmall\s+open[- ]source\s+model\b|\bmuch\s+smaller\s+than\b", re.IGNORECASE)
_ASKED_ABOUT_THE_MODEL = re.compile(r"\b(?:model|gpt|claude|chatgpt|gemini|cloud|small|smaller|smart|smarter|intelligent|compare[ds]?|better|worse|powerful|parameters|open[- ]source|llm|ai)\b|\bwho\s+are\s+you\b|\bwhat\s+are\s+you\b", re.IGNORECASE)


def has_a_postscript(reply):
    """Does the reply end with a "P.S." (the model's habit of tacking a personal remark on the end)?"""
    return isinstance(reply, str) and _POSTSCRIPT.search(reply) is not None


def ends_with_an_offer(reply):
    """Is the last sentence or paragraph of the reply an offer of more help ("Want me to ...?", "Let me know if ...", "Just say the word", "I'm here to help")?"""
    if not isinstance(reply, str) or not reply.strip():
        return False
    last = [piece for piece in re.split(r"(?<=[.!?])\s+|\n+", _EMOJI.sub("", reply).strip()) if piece.strip()]
    return bool(last) and _OFFER_START.search(last[-1]) is not None and len(last) > 1


def starts_with_filler(reply):
    """Does the reply open by praising the question or agreeing ("Great question!", "Sure!", "You're absolutely right ...")?"""
    return isinstance(reply, str) and (_FILLER_OPEN.search(reply) is not None or _RIGHT_OPEN.search(reply) is not None)


def tidy_reply(reply, user_text=""):
    """An ordinary reply made short and plain by taking out only what the model should not have added: pictures (unless the person used one), a closing offer of more help, a P.S., and a one-word praise or
    "you're right" at the start. Code blocks and `code` are left exactly as written. If nothing but those would be left, the reply is returned as it was (less its pictures)."""
    if not isinstance(reply, str) or not reply.strip() or "```" in reply:
        return reply
    keep_pictures = isinstance(user_text, str) and _EMOJI.search(user_text) is not None
    text = reply if keep_pictures else _PICTURES.sub("", reply)
    candidate = _POSTSCRIPT.sub("", text).rstrip()
    candidate = _FILLER_OPEN.sub("", candidate, count=1)
    candidate = _RIGHT_OPEN.sub("", candidate, count=1)
    if _SMALLNESS.search(candidate) and not _ASKED_ABOUT_THE_MODEL.search(user_text if isinstance(user_text, str) else ""):
        kept = [piece for piece in re.split(r"(?<=[.!?])(\s+)", candidate) if not _SMALLNESS.search(piece)]
        candidate = "".join(kept).strip() or candidate  # (whitespace pieces never match, so the paragraphs the model made are kept)
    pieces = re.split(r"(?<=[.!?])(\s+)", candidate)  # sentences with their gaps kept, so the paragraphs the model made are kept
    while len(pieces) >= 3 and _OFFER_START.search(pieces[-1]) is not None:
        pieces = pieces[:-2]
    candidate = "".join(pieces).rstrip()
    # a whole last paragraph that is an offer (it may not end with a full stop)
    paragraphs = re.split(r"\n\s*\n", candidate)
    while len(paragraphs) > 1 and _OFFER_START.search(paragraphs[-1].strip()) is not None:
        paragraphs = paragraphs[:-1]
    candidate = "\n\n".join(paragraphs).strip()
    candidate = re.sub(r"[ \t]+([,.!?;:])", r"\1", re.sub(r"[ \t]{2,}", " ", candidate))
    candidate = re.sub(r"[ \t]+\n", "\n", candidate)
    if " ".join(candidate.split()) == " ".join(reply.split()):
        return reply  # nothing was taken out: exactly as the model wrote it, down to the last space
    return candidate if len(candidate.split()) >= 1 else text.strip()


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
