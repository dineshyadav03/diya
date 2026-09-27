"""Hand-written, fictional messages for measuring diya_intent.is_fact_share (test_fact_share.py) and, since
the same shape of decision is exactly what RESEARCH.md entry 10 argues a fast model should make instead of
code, for comparing the two in diya_gate_bench.py.

FACTS is what a person sharing something about themselves looks like; NOT_FACTS is everything else that must
never be mistaken for it (a question, a command, a need, a complaint, plain chat) -- including several that
share a fact's shape (a date, a name) while being one of those instead.
"""

FACTS = [
    "My driving test is on October 12 from 9 to 10am and I take the train from Leeds to York for it.",
    "My sister Anna lives in Lisbon and her birthday is on March 3rd.",
    "My flight to Berlin leaves on Friday at 6am.",
    "I have a dentist appointment next Tuesday at 3pm.",
    "I just moved to a new apartment on Baker Street.",
    "my pottery class is on June 5 from 3 to 5pm and I take the bus to Exampleville for it",
    "I’m allergic to penicillin.",  # phone keyboards send a typographic apostrophe
    "Remember that my locker code is 4821.",
    "We're moving to Paris in June.",
    "My wifi password is on the fridge.",
    "I work at Acme Corp.",
    "I've adopted a cat called Miso.",
]
NOT_FACTS = [
    # questions (including ones only a question mark gives away)
    "What's the weather in London?", "What did I say about my dentist?", "Is my flight on Friday?",
    "I have an exam on Friday, how should I prepare?", "My dog is sick, what should I do?",
    "My flight is on Friday, right?", "I have a dentist appointment on Tuesday, correct?",
    # a statement, but not the user's own (nothing to acknowledge as theirs)
    "The shop closes at 5pm on Sundays.",
    # commands and requests, including ones that look like a fact
    "Remind me to call mom tomorrow.", "Remember to buy milk on Friday.", "Tell me a joke.",
    "Add milk to my shopping list for Friday.", "Search for trains from Leeds to York on Monday.",
    "Can you check my notes for the dentist?", "call my mom on Friday",
    "I have a dentist appointment on Tuesday. Remind me the day before.",
    "My flight leaves on Friday. Can you find hotels near the airport?",
    # needs, wishes, problems, complaints
    "I need a taxi to the airport at 6am.", "I want to book a flight to Berlin on Friday.",
    "I'm looking for a good sushi place in Leeds.", "I don't know what to wear to my interview on Monday.",
    "My printer isn't working, help.", "My laptop crashed yesterday", "My code has a bug on line 40",
    "I keep getting an error when I log in on Monday", "My order hasn't arrived and it was due Tuesday",
    "I have three exams next week and no idea where to start", "I can't find my keys, I left them Tuesday",
    "I need to renew my passport by March",
    # chat, or not first-person, or nothing factual in it
    "hello", "thanks!", "The weather is nice today.", "I'm bored.", "9 times 7", "",
]
