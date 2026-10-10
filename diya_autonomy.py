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
from typing import NamedTuple

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
    """What kind of secret `text` contains or names ("password", "token", "recovery", "card", "id", "credential"), or None. Over-cautious
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


def apply(memory, *, now=None, limit=DAILY_AUTO_LIMIT, breaker_limit=BREAKER_LIMIT, actor="auto"):
    """Put every candidate in its lane and act on it, each change one transaction with its event (which records the lane and why).
    Idempotent: a second run over the same candidates changes nothing. `now` is an aware datetime, for tests; the caps and the circuit
    breaker look at the 24 hours before it. Returns what was done."""
    import diya_memory
    from datetime import datetime, timedelta, timezone

    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=WINDOW_HOURS)).isoformat()
    memory.run_checks("system")  # flags are advisory input to the lanes, so they must be current
    recent = memory.count_events("accepted", actor, since)
    breaker_open = memory.taken_back_count(since) >= breaker_limit
    remembered = asked = never = held = 0
    for fact in memory.facts("candidate"):
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
    return Report(remembered, asked, never, held)


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
