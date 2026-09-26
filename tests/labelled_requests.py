"""Hand-written, fictional messages for measuring diya_intent.is_reminder_request (docs/PROACTIVITY_DESIGN.md, D9).

The guard decides whether `add_reminder` may save anything on a turn: only if the person's latest message asks
for a reminder. It exists because a reminder that fires is louder than one that sits in a table, and a small
model saves reminders nobody asked for. The cases were written by the author of the guard, so they show what it
does, NOT how it does on the way a real person phrases things; the two LIMITS lists keep the known failures on
purpose. A false refusal is the safe direction (the person can say "remind me to ..."); a false allowance is the
status quo before the guard.
"""

# Messages that ask for a reminder: the guard must allow these.
REQUESTS = [
    "Remind me to call mum tomorrow at 5pm",
    "remind me to take my pills at 9pm",
    "REMIND ME to stretch",
    "Please remind me to water the plants",
    "Hey Diya, remind me in 2 hours to check the oven",
    "Can you remind me about the dentist on Thursday?",
    "Could you please remind me that the rent is due",
    "remind us to leave at 7",
    "Write a note to remind myself to buy milk",
    "Set a reminder for Friday at 3pm to send the report",
    "set reminder: pay rent on the 1st",
    "Would you set a reminder for me to call Sam?",
    "Add a reminder to buy milk",
    "create a reminder for my flight",
    "Make a reminder that the bins go out tonight",
    "Schedule a reminder for 6pm",
    "Save a reminder: dentist Thursday 3pm",
    "Put a reminder in for tomorrow morning",
    "Set an alarm for 7am",
    "I need a reminder to book the vet",
    "I'd like a reminder for my appointment",
    "Give me a reminder about the meeting",
    "Don't let me forget the passport",
    "Do not let me forget mum's birthday",
    "never let me forget to lock up",
    "Don't forget I have a meeting at 3",
    "Remember to email Sam on Monday",
    "note to self: renew the licence",
    "Make a note to call the plumber",
    "Don" + chr(0x2019) + "t let me forget the tickets",  # a phone keyboard's curly apostrophe
]

# Messages that do not: the guard must refuse these.
NOT_REQUESTS = [
    "What's 9 times 7?",
    "What did I say about my dentist?",
    "What reminders do I have?",
    "List my reminders",
    "Do I have any reminders for tomorrow?",
    "Show me my reminders",
    "my flight is Friday at 6",
    "I have a dentist appointment on Thursday at 3pm",
    "Tell me a joke",
    "What's the weather in Oslo?",
    "Search the web for pasta recipes",
    "Translate hello into French",
    "I'm learning Portuguese",
    "I forgot my keys",
    "I never forget a face",
    "Remember when we talked about the garden?",
    "Can you note that I like tea?",
    "Jot down my idea for the garden",
    "The reminder email said Thursday",
    "Send a reminder email to the team",
    "Make a list of things to buy",
    "What is the reminder for?",
    "Do you remember my sister's name?",
    "Set the table for four",
    "Add 5 and 7",
    "Create a poem about autumn",
    "Schedule looks busy this week",
    "",
    "   ",
    None,
    42,
]

# Not requests, but the guard allows them (a false allowance: no worse than before the guard existed).
LIMIT_ALLOWED = [
    "How do I set a reminder on my phone?",
    "I remember to lock the door every night",
    "Please don't set a reminder for that",
    "What does 'remind me' mean in Spanish?",
]

# Requests a person would recognise, which the guard refuses (a false refusal: they can say "remind me to ...").
LIMIT_REFUSED = [
    "Ping me at 5 about the call",
    "Alert me when it's 6",
    "Wake me up at 7",
    "Let me know at 3 that it's time to leave",
    "Buzz me tomorrow at 9",
    "Tell me at noon to eat lunch",
]
