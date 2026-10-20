"""Labelled requests for picking a playbook by meaning (diya_playbooks.pick, docs/PLAYBOOKS_DESIGN.md), invented. `PICK` are (request, the playbook it should pick); `NONE` are requests that should pick
nothing, some of them near misses on purpose (a plan for a day is not a study plan; a weekly review playbook that allows only the user to name it is never picked by meaning). The playbooks are the three
in `sample_playbooks/`."""

PICK = [
    ("can you make me a study plan for my pharmacology exam?", "study-plan"),
    ("I need a revision schedule for the exam on the 5th of November", "study-plan"),
    ("how should I prepare for my anatomy test next week", "study-plan"),
    ("help me plan my exam preparation", "study-plan"),
    ("make a timetable to revise for statistics", "study-plan"),
    ("summarise this: Photosynthesis is the process by which plants convert light energy into chemical energy stored in glucose", "summarise-notes"),
    ("can you condense my notes on the brachial plexus", "summarise-notes"),
    ("make short notes out of this paragraph about the Krebs cycle", "summarise-notes"),
    ("give me a quick summary of the cardiology text I pasted", "summarise-notes"),
    ("turn my lecture notes on beta blockers into bullet points", "summarise-notes"),
]

NONE = [
    "what is the capital of France?",
    "tell me a joke",
    "remind me to call mom at 5",
    "how is the weather in Pune?",
    "I bought a new guitar",
    "what is 17 times 23?",
    "explain how insulin works",
    "write an email to my professor asking for an extension",
    "plan my day tomorrow",
    "how did my week go?",
    "what should I focus on next week?",
    "what time is mess dinner?",
    "translate good morning into Hindi",
    "recommend a book like Dune",
]
