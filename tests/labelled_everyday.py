"""Hand-written, fictional messages that are NOT requests for a reminder: ordinary things a person says to an assistant (docs/ADVISOR_DESIGN.md).

They exist because `diya_advisor.py` found that 71 labelled cases cannot tell a good edit to the reminder gate from a harmful one: `\\blet\\s+me\\b` fixes "Let me know at 3 that it's time to leave" and breaks
none of them, and so would turn "let me know the weather" into a saved reminder. These are the messages such edits have to leave alone, so they are chosen to contain the words a careless edit would
add ("let me", "tell me", "ping", "wake", "alert", "buzz", "show me", "call me") in everyday, non-reminder use. The author of the reminder gate wrote them, like the other labelled sets, so they show what the
gate does, not how it does on every real phrasing. Every one of EVERYDAY is tested to be refused by `is_reminder_request` today (tests/test_advisor.py). EVERYDAY_ALLOWED are two that it accepts and should not: known misses, kept on
purpose like LIMIT_ALLOWED in labelled_requests.py.
"""

EVERYDAY = [
    "Let me know what the weather is like in Pune",
    "Let me see my tasks",
    "Let me think about it",
    "Let me tell you about my day",
    "Let me know if you find anything about the flights",
    "Let me ask you something about Python",
    "Let me start again",
    "Tell me a joke",
    "Tell me about the history of Lisbon",
    "Tell me what time it is in Tokyo",
    "Tell me at least three facts about otters",
    "Tell me about my day",
    "Tell me more about that",
    "Tell me which one is cheaper",
    "Please tell me at which temperature water boils",
    "Can you tell me how to reset my router?",
    "Show me my reminders",
    "Show me what I wrote about the garden",
    "Give me a summary of my notes",
    "Give me ideas for dinner",
    "Send me the list of tasks",
    "Call me Alex from now on",
    "Ping the server to see if it is up",
    "What does ping mean in networking?",
    "How do I ping a website from the command line?",
    "Why do people say 'ping me' at work?",
    "Wake up, Diya",
    "What time should I wake up to catch a 7am train?",
    "Is it bad to hit snooze and wake up late?",
    "The alert on my phone is too loud",
    "How do I turn off weather alerts?",
    "The buzz around the new phone is huge",
    "My phone buzzes all night",
    "Which alarm sound is the least annoying?",
    "What is the best way to wake up early?",
    "Wake me up inside is a good song",
    "Do not alert the neighbours",
    "Keep me company while I cook",
    "Help me plan a trip to Japan",
    "Teach me how decorators work in Python",
    "Take me through the steps to make bread",
    "Read me the first paragraph of my note about the dentist",
    "What did I ask you to remember last week?",
    "Do you remember what I told you about my sister?",
    "Notes from the meeting: the budget is approved",
    "I keep forgetting my keys",
    "Never let me down",
    "Let me out of this conversation",
]

# Not requests, but the gate accepts them today (a false allowance): "remind me" as in "tell me again", and "don't forget" as advice.
EVERYDAY_ALLOWED = [
    "Remind me what we said about the budget",
    "Don't forget to be kind to yourself",
]
