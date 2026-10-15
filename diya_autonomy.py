"""The policy for memory that remembers on its own (docs/AUTO_MEMORY_DESIGN.md, D1-D3 and D6; unit A1).

Every fact Diya extracts is put in exactly one lane, by code, from its own words and the flags the deterministic checks already left:

    REMEMBER   accepted at once (by `auto`): a plain, grounded statement in no sensitive class that conflicts with nothing.
    ASK        stays a candidate and a question is opened about it: doubtful, a possible update of what is known, or sensitive.
    NEVER      rejected, and never asked about: a secret (its text is not even kept), an instruction, something the owner
               already rejected, something with no message of theirs behind it, a repeat of what is known.

The deciding is pure: `secret_kind`, `sensitive_class` and `decide` read text and numbers and return a decision; they touch no database,
no clock and no model. The model proposes facts (and may give an opinion); only this decides what happens to one. What it cannot know it asks about, and the detectors
are deliberately over-cautious (a dropped or asked-about fact costs the owner a moment; a kept secret costs far more), which is why
they are tested on labelled cases in both directions (tests/labelled_autonomy.py): what must be caught, and what must not be.

`apply` is the one place that acts on a decision, and only through the store's own methods, so every change is one transaction with
its event, as everything else there is.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

import diya_checks

LANE_REMEMBER, LANE_ASK, LANE_NEVER = "remember", "ask", "never"
LANES = (LANE_REMEMBER, LANE_ASK, LANE_NEVER)

DAILY_AUTO_LIMIT = 20  # facts accepted without a person in any rolling 24 hours; over it, new ones wait as questions
BREAKER_LIMIT = 3  # automatic facts the owner took back in the last 24 hours that pause automatic acceptance
WINDOW_HOURS = 24

KIND_DOUBT, KIND_CONFLICT, KIND_SENSITIVE = "doubt", "conflict", "sensitive"


class Decision(NamedTuple):
    lane: str
    reasons: tuple  # stable codes, for the trail and the page: "secret:password", "sensitive:health", "similar:12", ...
    kind: str | None  # for ASK: what the question will be about


# ---- secrets: never kept ----------------------------------------------------------------------------------------

# Words that mean a credential. Without a value ("the wifi password is on the fridge") they still count: the line between a
# note about a secret and the secret cannot be drawn reliably, and not keeping the note costs little. Each pattern names its kind.
_SECRET_WORDS = (
    ("password", re.compile(
        r"\b(?:passwords?|passphrases?|passcodes?|(?:my|the|his|her|their|your|a|new|old|phone|card|bank|atm|sim|unlock)\s+pin(?!\s*codes?)|pin\s+(?:is|number|[:=])|otps?|one[- ]time\s+(?:password|code|passcode)|verification\s+codes?|"
        r"security\s+codes?|cvv|cvc)\b", re.IGNORECASE)),
    ("token", re.compile(
        r"\b(?:secret\s+keys?|private\s+keys?|api\s+keys?|access\s+tokens?|auth(?:entication)?\s+tokens?|bearer\s+tokens?)\b", re.IGNORECASE)),
    ("recovery", re.compile(r"\b(?:recovery\s+(?:phrase|key|code)s?|seed\s+phrases?)\b", re.IGNORECASE)),
    ("card", re.compile(r"\b(?:card|account|routing)\s+numbers?\b", re.IGNORECASE)),
    ("id", re.compile(
        r"\b(?:aadhaar|aadhar|pan\s+(?:number|card)|social\s+security|ssn|passport\s+numbers?|(?:driving\s+)?licen[cs]e\s+numbers?|national\s+id)\b",
        re.IGNORECASE)),
    ("credential", re.compile(r"\bcredentials?\b", re.IGNORECASE)),
    # Added 2026-10-14, after the two-judge comparison (docs/AUTO_MEMORY_DESIGN.md, 8.5) showed these getting through when the suspicious judge no longer blocks everything: a way into a place.
    ("access", re.compile(
        r"\b(?:combination|combo\s+lock|(?:door|gate|locker|safe|alarm|garage|building|lock)\s+(?:code|combination|pin)|use\s+code\s+\d|(?:spare|hidden|extra)\s+keys?|keys?\s+(?:is|are)?\s*(?:under|inside|behind)\b|"
        r"(?:wi-?fi|wlan)\b[^.]{0,40}\bkey\b)", re.IGNORECASE)),
)
# Values that look like a secret whatever the words around them say.
_TOKEN_PREFIX = re.compile(r"\b(?:sk|pk|rk)[-_][A-Za-z0-9_-]{16,}|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{12,}|\bAIza[0-9A-Za-z_-]{20,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_LONG_MIXED = re.compile(r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{28,}(?![A-Za-z0-9_-])")
_CARD_SHAPE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)(?<!\d[ -])\d{4}[ -]\d{4}[ -]\d{4}(?![ -]?\d)")  # a 4-4-4 group that is not the tail or the head of a longer one
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")  # an Indian permanent account number; case matters, so it is matched on the text as written
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")
_HEX_SECRET = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32,}(?![0-9a-fA-F])")


def _luhn(digits):
    total = 0
    for index, char in enumerate(reversed(digits)):
        n = int(char)
        if index % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def secret_kind(text):
    """What kind of secret `text` contains or names ("password", "token", "recovery", "card", "id", "credential", "access"), or None. Over-cautious
    on purpose."""
    if not isinstance(text, str):
        return None
    for kind, pattern in _SECRET_WORDS:
        if pattern.search(text):
            return kind
    if _TOKEN_PREFIX.search(text) or _JWT.search(text) or _LONG_MIXED.search(text) or _HEX_SECRET.search(text):
        return "token"
    for match in _CARD_SHAPE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return "card"
    if _AADHAAR.search(text) or _SSN.search(text) or _PAN.search(text) or _IBAN.search(text):
        return "id"
    return None


# ---- sensitive classes: always asked first ----------------------------------------------------------------------

_SENSITIVE = (
    ("health", re.compile(
        r"\b(?:diagnos\w*|medications?|medicines?|prescri\w+|dosages?|symptoms?|surgery|surgeries|chemotherapy|therap(?:y|ist)s?|"
        r"pregnan\w*|miscarriage|cancer|diabet\w*|asthma\w*|epilep\w*|depress\w*|anxiety|bipolar|schizophreni\w*|adhd|autis\w*|hiv|"
        r"mental\s+health|blood\s+(?:pressure|sugar|group)|allerg\w*|chronic|disorder|disease|pills?|injections?|antibiotics?|insulin)\b",
        re.IGNORECASE)),
    ("money", re.compile(
        r"(?:[$€£₹]\s?\d|\b(?:rs\.?|inr|usd|eur|gbp|rupees?|dollars?|euros?)\s?\d|\b\d[\d,.]*\s?(?:rs|inr|usd|eur|gbp|rupees?|dollars?|euros?|lakhs?|crores?)\b)"
        r"|\b(?:salary|income|net\s+worth|debts?|loans?|mortgage|emi|credit\s+score|owes?|owed|bankrupt\w*|savings|bank\s+balance|"
        r"tax\s+return|investments?)\b", re.IGNORECASE)),
    ("legal", re.compile(
        r"\b(?:lawsuit|sued|suing|court|arrest\w*|police|custody|divorce[ds]?|restraining|immigration|visa\s+(?:status|rejected|denied)|"
        r"convicted|criminal|bail|attorney|lawyer)\b", re.IGNORECASE)),
    ("address", re.compile(
        r"\b(?:home|house|street|postal|mailing|residential)\s+address\b|\bmy\s+address\b|\b(?:lives?|stays?|living)\s+at\b|"
        r"\b(?:flat|apartment|apt|house|plot|door)\s*(?:no\.?|number|#)?(?:\s+is)?\s*\d+|\b\d+\s+[A-Z][a-z]+\s+(?:street|st|road|rd|avenue|ave|lane|ln|nagar|colony)\b",
        re.IGNORECASE)),
    ("contact", re.compile(
        r"[\w.+-]+@[\w-]+\.[\w.-]+|(?<!\d)(?:\+?\d{1,3}[ -]?)?\d{5}[ -]?\d{5}(?!\d)|(?<!\d)(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3,5}\)?[ -]?)\d{3,4}[ -]?\d{3,4}(?!\d)|\b(?:phone|mobile|whatsapp|contact)\s+(?:number|no\.?)\b",
        re.IGNORECASE)),
    ("belief", re.compile(
        r"\b(?:religio\w*|atheist|agnostic|muslim|christian|hindu|sikh|jewish|buddhist|catholic|gay|lesbian|bisexual|transgender|queer|"
        r"sexual\s+orientation|politic\w*|votes?\s+for|voted|caste|ethnicity|racial)\b", re.IGNORECASE)),
)


def sensitive_class(text):
    """The first sensitive class `text` falls in ("health", "money", "legal", "address", "contact", "belief"), or None."""
    if not isinstance(text, str):
        return None
    for name, pattern in _SENSITIVE:
        if pattern.search(text):
            return name
    return None


# ---- the model's own judgement of what is private ------------------------------------------------------------------

# The word lists above know the words of health, money and the rest, and miss everything said without them: a medicine's name, "I got laid
# off", "my mother has been in the hospital", "the door code is 4829". Measured (docs/AUTO_MEMORY_DESIGN.md, section 8), the local model
# itself, asked this one question, flagged every one of those and a further 11 it had never seen, so what the words let through goes to it.
# The words stay: they cost nothing and never tire. The model's answer can only ADD caution: anything but a plain "OK" (an unsure answer, an
# answer that is not one of the three words, no answer at all) means the person is asked. This text was frozen before the held-out sentences
# were written; change it only together with new held-out sentences, never to fit the ones already measured.
PRIVACY_PROMPT = (
    "You are a privacy filter for a personal assistant's memory. Decide whether remembering the sentence below about a person would store "
    "something private: health or medicine (physical or mental), money or debts, a legal matter, losing a job or another hardship, family "
    "or relationship trouble, a home address or an exact place, a phone number, an email or an ID number, a password or a code or anything "
    "that unlocks something, religion, politics, sexuality, or anything else a person would want to be asked about before it is kept. "
    "Everyday facts such as hobbies, tastes in food or music, pets, habits, plans, work, tools and gadgets are NOT private.\n\n"
    'Sentence: "{text}"\n\nAnswer with exactly one word: PRIVATE, OK or UNSURE.'
)
PRIVACY_ANSWERS = {"OK": "ok", "PRIVATE": "private", "UNSURE": "unsure"}


def privacy_verdict(client, model, text):
    """The model's answer to "is this sentence private?": "ok", "private", "unsure", or "failed" when it could not be asked. Anything that is
    not clearly one of the three words counts as "unsure"; only "ok" lets a fact be remembered without a question."""
    try:
        reply = client.chat.completions.create(
            model=model, temperature=0, max_tokens=8, messages=[{"role": "user", "content": PRIVACY_PROMPT.format(text=text)}]
        )
        words = (reply.choices[0].message.content or "").strip().split()
    except Exception:  # noqa: BLE001 -- the model is down, slow or confused: the answer is "ask", not an error
        return "failed"
    first = words[0].strip(".,!:;\"'*").upper() if words else ""
    return PRIVACY_ANSWERS.get(first, "unsure")


_CAUTIOUS_FIRST = ("failed", "private", "unsure", "ok")


def combine_privacy(strict, main):
    """Two judges, one answer (docs/AUTO_MEMORY_DESIGN.md, 8.5). A suspicious small judge (`strict`) said "unsure" about half of the ordinary facts a person really typed ("has a dog named hog",
    "lives in Pune"), so nothing was ever remembered on its own. Now it keeps its veto, a clear "private", but its "unsure" no longer blocks when the better judge (`main`) says OK; either one failing
    to answer, or the better judge being unsure, still means the person is asked."""
    if "failed" in (strict, main):
        return "failed"
    if "private" in (strict, main):
        return "private"
    return "ok" if main == "ok" else "unsure"


def privacy_of_two(client, strict_model, main_model, texts):
    """The most cautious combined verdict over several sentences (see privacy_of and combine_privacy)."""
    return min((combine_privacy(privacy_verdict(client, strict_model, text), privacy_verdict(client, main_model, text)) for text in texts), key=_CAUTIOUS_FIRST.index)


def privacy_of(client, model, texts):
    """The most cautious verdict over several sentences: the fact, and the message of the person's it was taken from. A fact is a rewrite, and a rewrite
    can lose what made the original private ("my visa expires in June and I still haven't heard back" became "Visa expires in June", which the model
    called OK), so the person's own words are asked about too and the worse answer counts."""
    return min((privacy_verdict(client, model, text) for text in texts), key=_CAUTIOUS_FIRST.index)


# Remembering a new fact beside an old one it replaces ("works as a nurse" next to "works as a teacher") leaves the model told two things that
# cannot both be true. The words checks only catch a near-copy ("similar"); a move to another city shares almost no words with the old address.
# Measured on twenty sentences against eight known facts (docs/AUTO_MEMORY_DESIGN.md, section 9) and then, with the text below unchanged, on
# sixteen more: the capped 4B model named the right fact 19 of 20 and 14 of 16 times, and its two mistakes were a new fact mistaken for a
# replacement, which only costs a question. The 3B model missed a third, so this one is asked of the chat model. Anything but a number or NONE
# is "unclear" and the person is asked: only a clear NONE lets a fact be remembered beside what is known. Frozen like the privacy question.
REPLACE_PROMPT = (
    "Below are facts already known about a person, numbered, and then one new sentence from the person. Decide whether the new sentence REPLACES or "
    "CONTRADICTS one of the known facts, so that the two cannot both be true now (for example a move to another city, a new job, giving something up). "
    "A sentence that only adds something new, or only mentions the same subject, does not replace anything.\n\n"
    'Known facts:\n{known}\n\nNew sentence: "{text}"\n\nAnswer with the number of the fact it replaces, or NONE if it replaces none. Answer with one word.'
)
MAX_KNOWN = 80  # the newest accepted facts put to the model: enough for the whole profile budget, bounded so the question stays short


# The person's own words say it ADDS to what is known: "I got another dog named Hog" next to "my dog is Rocky". The replacement question saw only the rewritten fact ("has a dog named hog"), lost
# the "another", and took it for Rocky's replacement, so the fact waited as a question (2026-10-14). Code reads these few words first and the model is not asked.
_ADDS = re.compile(r"\b(?:another|a\s+second|one\s+more|an?\s+additional|yet\s+another|also\s+(?:got|have|has|bought|adopted|started))\b", re.IGNORECASE)


def says_it_adds(texts):
    """True if any of the person's own `texts` says the new thing is in addition to what they had (another, a second, one more, also got ...)."""
    return any(isinstance(text, str) and _ADDS.search(text) for text in texts)


class Replacement(NamedTuple):
    answer: str  # "none", "replaces", "unclear" or "failed" (the model could not be asked)
    fact_id: Optional[int]  # the fact it replaces, only when the answer is "replaces"


def _known_line(fact):
    return f"{fact['person']}: {fact['text']}" if fact.get("person") else fact["text"]


def replacement_of(client, model, known, text):
    """Which of the `known` facts (dicts with id and text, as `Memory.facts` gives them) the sentence `text` replaces: a Replacement. With nothing
    known there is nothing to replace and the model is not asked. Only the newest MAX_KNOWN are put to it."""
    known = known[-MAX_KNOWN:]
    if not known:
        return Replacement("none", None)
    listing = "\n".join(f"{number}. {_known_line(fact)}" for number, fact in enumerate(known, start=1))
    try:
        reply = client.chat.completions.create(
            model=model, temperature=0, max_tokens=8, messages=[{"role": "user", "content": REPLACE_PROMPT.format(known=listing, text=text)}]
        )
        words = (reply.choices[0].message.content or "").strip().split()
    except Exception:  # noqa: BLE001 -- the model is down, slow or confused: the answer is "ask", not an error
        return Replacement("failed", None)
    first = words[0].strip(".,!:;\"'*") if words else ""
    if first.upper() == "NONE":
        return Replacement("none", None)
    if first.isdigit() and 1 <= int(first) <= len(known):
        return Replacement("replaces", known[int(first) - 1]["id"])
    return Replacement("unclear", None)


# ---- the decision -----------------------------------------------------------------------------------------------

_NEVER_FLAGS = (
    (diya_checks.FLAG_INSTRUCTION, "instruction_shaped"),
    ("preamble", "preamble"),
    (diya_checks.FLAG_NO_SOURCE, "no_source"),
    ("too_long", "too_long"),
)


def _flag_names(flags):
    return {flag.partition(":")[0]: flag.partition(":")[2] for flag in flags}


def decide(fact, *, auto_recent=0, breaker_open=False, limit=DAILY_AUTO_LIMIT):
    """The lane for one candidate. `fact` is a dict with `text`, `status` and `flags` (what `Memory.facts()` returns). `auto_recent` is how
    many facts were accepted automatically in the last 24 hours, and `breaker_open` says the owner took back too many of them. Raises
    ValueError for anything that is not a candidate: only a candidate has anything left to decide."""
    if fact.get("status") != "candidate":
        raise ValueError(f"only a candidate can be decided, this fact is {fact.get('status')!r}")
    text, flags = fact["text"], fact.get("flags") or []
    named = _flag_names(flags)

    secret = secret_kind(text)
    if secret:
        return Decision(LANE_NEVER, (f"secret:{secret}",), None)
    never = [reason for flag, reason in _NEVER_FLAGS if flag in named]
    if diya_checks.FLAG_PREVIOUSLY_REJECTED in named:
        never.append("previously_rejected")
    if diya_checks.FLAG_DUPLICATE in named:
        never.append("duplicate")
    if diya_checks.FLAG_UNGROUNDED in named and named.get("verifier") == "no":
        never.append("unsupported")  # two independent signals that the owner never said it
    if never:
        return Decision(LANE_NEVER, tuple(never), None)

    sensitive = sensitive_class(text)
    if sensitive:
        return Decision(LANE_ASK, (f"sensitive:{sensitive}",), KIND_SENSITIVE)
    if diya_checks.FLAG_SIMILAR in named:
        return Decision(LANE_ASK, (f"similar:{named[diya_checks.FLAG_SIMILAR]}",), KIND_CONFLICT)
    doubts = []
    if diya_checks.FLAG_UNGROUNDED in named:
        doubts.append("ungrounded")
    if named.get("verifier") in ("no", "unclear"):
        doubts.append(f"verifier:{named['verifier']}")
    if doubts:
        return Decision(LANE_ASK, tuple(doubts), KIND_DOUBT)
    if breaker_open:
        return Decision(LANE_ASK, ("breaker_open",), KIND_DOUBT)
    if auto_recent >= limit:
        return Decision(LANE_ASK, ("daily_cap",), KIND_DOUBT)
    return Decision(LANE_REMEMBER, ("plain",), None)


# ---- acting on a decision ---------------------------------------------------------------------------------------

class Report(NamedTuple):
    remembered: int  # candidates accepted on their own
    asked: int  # left as candidates, with a question to come
    never: int  # rejected (secrets discarded without their text)
    held: int  # could not be accepted yet: the profile is full
    replaced: int = 0  # accepted in place of a known fact, because the person was correcting it (and the model said which)


def apply(memory, *, now=None, limit=DAILY_AUTO_LIMIT, breaker_limit=BREAKER_LIMIT, actor="auto", private=None, replaces=None, corrects=None, adds=None):
    """Put every candidate in its lane and act on it, each change one transaction with its event (which records the lane and why).
    Idempotent: a second run over the same candidates changes nothing. `now` is an aware datetime, for tests; the caps and the circuit
    breaker look at the 24 hours before it. `private(fact)` is the model's judgement of a fact the words let through (privacy_of): asked
    only of a fact about to be remembered, and only "ok" lets it be; with none given there is no such check (the pure-policy tests).
    `replaces(fact)` is the model's judgement of whether such a fact replaces one already known (replacement_of): asked after the privacy
    check, of a fact that passed it, and only a clear "none" lets the fact be remembered; with none given there is no such check.
    `adds(fact)` says whether the person's own words said the fact is IN ADDITION to what is known ("another dog named Hog", "I also play the violin"; says_it_adds on the message it came from): such a fact
    is not held up for looking like a known one (the `similar` check is about copies, and a second dog's name looks like the first's), and it replaces nothing.
    `corrects(fact)` says whether the person's own words were correcting something (diya_intent.is_correction on the message the fact came from): when
    it is true AND the model named the fact the new one replaces, the new fact replaces it at once (Memory.supersede, by `actor`) instead of waiting as a
    question; either alone still asks. The replacement counts toward the daily limit, and is the person's to undo.
    Returns what was done."""
    import diya_memory
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=WINDOW_HOURS)).isoformat()
    memory.run_checks("system")  # flags are advisory input to the lanes, so they must be current
    recent = memory.count_events("accepted", actor, since)
    breaker_open = memory.taken_back_count(since) >= breaker_limit
    remembered = asked = never = held = replaced = 0
    for fact in memory.facts("candidate"):
        decision = decide(fact, auto_recent=recent, breaker_open=breaker_open, limit=limit)
        if decision.lane == LANE_ASK and decision.reasons and decision.reasons[0].startswith("similar:") and adds is not None and adds(fact):
            fact = dict(fact, flags=[f for f in fact["flags"] if not f.startswith(("similar:", "ask:conflict:similar:"))])  # "another": it is not a copy, whatever the words look like
            decision = decide(fact, auto_recent=recent, breaker_open=breaker_open, limit=limit)
        detail = {"lane": decision.lane, "reasons": list(decision.reasons)}
        if decision.lane == LANE_NEVER:
            if decision.reasons[0].startswith("secret:"):
                memory.discard_secret(fact["id"], decision.reasons[0].partition(":")[2], actor)
            else:
                memory.decide(fact["id"], "reject", actor, detail)
                _clear_ask(memory, fact["id"], actor)
            never += 1
        elif decision.lane == LANE_REMEMBER:
            verdict = _privacy(fact, private)
            if verdict != "ok":  # the model thinks it private, is unsure, or could not be asked: the person decides
                if verdict == "failed":
                    _mark_ask(memory, fact, KIND_DOUBT, "privacy_check_failed", actor)  # not sticky: asked again at the next run
                else:
                    _mark_ask(memory, fact, KIND_SENSITIVE, f"model_{verdict}", actor)
                asked += 1
                continue
            replacement = _replacement(fact, replaces)
            if replacement.answer != "none":  # it may replace what is known, or the model could not say: the person decides
                if replacement.answer == "failed":
                    _mark_ask(memory, fact, KIND_DOUBT, "replace_check_failed", actor)  # not sticky: asked again at the next run
                elif replacement.answer == "unclear":
                    _mark_ask(memory, fact, KIND_CONFLICT, "replaces_unclear", actor)
                else:
                    if corrects is not None and corrects(fact) and _replace_now(memory, fact, replacement.fact_id, actor):
                        replaced += 1
                        recent += 1
                        continue
                    _mark_ask(memory, fact, KIND_CONFLICT, f"replaces:{replacement.fact_id}", actor)
                asked += 1
                continue
            try:
                memory.decide(fact["id"], "accept", actor, detail)
            except diya_memory.DuplicateFact:
                memory.decide(fact["id"], "reject", actor, {"lane": LANE_NEVER, "reasons": ["duplicate"]})
                _clear_ask(memory, fact["id"], actor)
                never += 1
            except diya_memory.BudgetExceeded:
                _mark_ask(memory, fact, KIND_DOUBT, "memory_full", actor)
                held += 1
            except diya_memory.InvalidFact:  # too long to accept as it stands
                memory.decide(fact["id"], "reject", actor, {"lane": LANE_NEVER, "reasons": ["too_long"]})
                _clear_ask(memory, fact["id"], actor)
                never += 1
            else:
                _clear_ask(memory, fact["id"], actor)
                remembered += 1
                recent += 1
        else:
            _mark_ask(memory, fact, decision.kind, decision.reasons[0], actor)
            asked += 1
    return Report(remembered, asked, never, held, replaced)


def _replace_now(memory, fact, old_id, actor):
    """Replace the known fact `old_id` with `fact` as a correction (Memory.supersede). False, with nothing changed, if it cannot be done (the old fact is
    no longer accepted, an accepted fact already says the same, no room): the fact then waits as a question like any other."""
    import diya_memory

    try:
        memory.supersede(fact["id"], old_id, actor, why={"lane": LANE_REMEMBER, "reasons": ["correction"]})
    except diya_memory.FactError:
        return False
    return True


def _privacy(fact, private):
    """"ok" if the fact may be remembered as far as privacy goes, else why not. A fact the model already judged private or unsure keeps
    waiting for the person without being asked again (a second answer must not undo the first), and one the model could not be asked about
    is asked again next time."""
    if private is None:
        return "ok"
    for flag in fact["flags"]:
        if flag.startswith("ask:sensitive:model_"):
            return flag.rpartition("model_")[2]
    return private(fact)


def _replacement(fact, replaces):
    """"none" if the fact replaces nothing known, as far as the model can say, else what it said. A fact that was already judged to replace
    something (or judged unclear) keeps waiting for the person without being asked again; one the model could not be asked about is asked again."""
    if replaces is None:
        return Replacement("none", None)
    for flag in fact["flags"]:
        if flag.startswith("ask:conflict:replaces:"):
            return Replacement("replaces", int(flag.rpartition(":")[2]))
        if flag == "ask:conflict:replaces_unclear":
            return Replacement("unclear", None)
    return replaces(fact)


def _clear_ask(memory, fact_id, actor):
    """Take an `ask:` flag off a fact that is no longer waiting to be asked about (it was accepted or rejected since), so the page does not
    say Diya will ask about something that has been settled."""
    import diya_memory

    flags = memory.get(fact_id)["flags"]
    kept = [flag for flag in flags if not flag.startswith(diya_memory.ASK_PREFIX)]
    if kept != flags:
        memory.set_flags(fact_id, kept, actor)


def _mark_ask(memory, fact, kind, reason, actor):
    """Leave `ask:<kind>:<reason>` on a candidate (replacing an earlier one), so the page and the question queue can say why it waits.
    Records a `flagged` event only if the flag actually changed."""
    import diya_memory

    flags = [flag for flag in fact["flags"] if not flag.startswith(diya_memory.ASK_PREFIX)]
    detail = reason[len(kind) + 1:] if reason.startswith(kind + ":") else reason  # "sensitive:health" under kind "sensitive" is "health"
    memory.set_flags(fact["id"], flags + [f"{diya_memory.ASK_PREFIX}{kind}:{detail}"], actor)
