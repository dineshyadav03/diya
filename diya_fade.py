"""Facts that fade unless they are said again (docs/FADING_DESIGN.md), added 2026-10-18 from the study of supermemory's company-brain (docs/STUDY_SUPERMEMORY.md, section 6).

supermemory's capture policy says: "Because memory decays, give transient or low-confidence facts a forget horizon so they fade on their own... When the same thing shows up again, reinforce/update the existing
memory instead of adding a duplicate: that renews it and firms it up." Hindsight keeps a "proof count" and the exact quotes for each belief. Diya had half of this: a fact about a DAY ("exam next Tuesday") is
retired once the day has passed (diya_questions.retire_gone), but a fact about a passing STATE ("I'm reading Dune these days", "for now I'm using the old laptop") stayed in the profile for ever and was told to
the model for ever.

The rule here is deliberately narrow, and written in code, because forgetting something that was meant to last is worse than keeping something that has faded (it is retired, not deleted, and Restore brings it back):

* only a fact that says, in its own words, that it is a passing state fades: "right now", "at the moment", "for now", "for the time being", "temporarily", "this semester", or a progressive activity said with
  "currently / these days / lately" ("currently reading", "lately working on");
* "currently lives in", "currently works at", "currently has a dog" do NOT fade: a marker alone is not enough, the fact must be about an activity;
* anything that says it repeats or lasts ("always", "every", "usually", "used to", "forever") never fades;
* the time it lasts depends on the phrase (a week for "right now", about six weeks for a passing activity, a term for "this semester") and is counted from the last time the person said it: the first time, or any
  time they said it again (a repeat is recorded as a mention and renews it), or when it was restored;
* "Keep" on the Memory page ends the fading for that fact for good.

Importing this module has no side effects.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

_DURABLE = re.compile(r"\b(?:always|never|every|each|usually|used\s+to|forever|permanent\w*|all\s+my\s+life|since\s+\w+\s+\d{4}|since\s+\d{4})\b", re.IGNORECASE)
_ACTIVITY = (
    r"(?:reading|watching|playing|studying|learning|working\s+on|trying|using|testing|listening\s+to|preparing\s+for|revising|building|taking|doing|attending|training|following|practi[sc]ing|writing)"
)
_MARKER = r"(?:currently|presently|these\s+days|nowadays|lately)"
_RULES = (
    (re.compile(r"\b(?:right\s+now|at\s+the\s+moment|at\s+present|as\s+of\s+now)\b", re.IGNORECASE), 7, "a passing state"),
    (re.compile(r"\b(?:for\s+now|for\s+the\s+time\s+being|for\s+a\s+while|temporarily)\b", re.IGNORECASE), 45, "for now"),
    (re.compile(rf"\b{_MARKER}\b.{{0,40}}?\b{_ACTIVITY}\b|\b{_ACTIVITY}\b.{{0,60}}?\b{_MARKER}\b", re.IGNORECASE), 45, "a passing activity"),
    (re.compile(r"\b(?:this|the\s+current)\s+(?:semester|term|quarter)\b", re.IGNORECASE), 120, "this term"),
)


def fade_rule(text):
    """(days, why) for a fact that says it is a passing state; None for one that is meant to last (or that this does not recognise: the safe answer). The shortest matching phrase decides."""
    if not isinstance(text, str) or _DURABLE.search(text):
        return None
    found = [(days, why) for pattern, days, why in _RULES if pattern.search(text)]
    return min(found) if found else None


def fades_on(text, evidence_times):
    """The moment a fact fades: `days` after the LAST time it was said, or None if it does not fade. `evidence_times` are datetimes (all the same kind: aware or naive): when it was first
    taken in, each time it was said again, when it was restored."""
    rule = fade_rule(text)
    if rule is None or not evidence_times:
        return None
    return max(evidence_times) + timedelta(days=rule[0])


def explicit_end(text, created_at):
    """When a fact fades because it SAYS how long it lasts ("until 31 Jan", "the trial ends on 15 Nov", "through the end of March"): the start of the day after that day, as an aware datetime in the person's zone,
    or None. The year of a date written without one is worked out against the day the fact was made (diya_when.ends_on), a date already behind it is ignored, and saying the fact again does not move the date:
    the date is the date. Unlike the passing-state phrases this needs no marker word ("always", "every" do not stop "every Monday until March" from ending in March)."""
    import diya_when

    try:
        made = diya_when.local_date(created_at)
    except (ValueError, TypeError, AttributeError):
        return None
    last = diya_when.ends_on(text, made)
    if last is None:
        return None
    return datetime.combine(last + timedelta(days=1), time.min).astimezone()


def lasts_until(text, created_at):
    """The last day a fact says it lasts to (a date), or None: what the Memory page says instead of "a passing state"."""
    import diya_when

    try:
        return diya_when.ends_on(text, diya_when.local_date(created_at))
    except (ValueError, TypeError, AttributeError):
        return None


def describe(text):
    """The rule as words for the person ("a passing state", "for now", ...), or None."""
    rule = fade_rule(text)
    return rule[1] if rule else None
