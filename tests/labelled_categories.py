"""Messages written for measuring how Diya sorts what is said into categories (diya_categories; docs/ONE_CHAT_DESIGN.md). Written by the author, not taken from anyone's chats.

Each is (the message, the category letters that would be an acceptable place for it): W Weather, R Reminders & tasks, M About me, D About Diya, L Learning, C Chat.
Several are on purpose a poor fit for every category ("book me a table", "play some music", "what should I do this weekend"): with no "Other", they must still land somewhere sensible.
"""
LETTERS = {"W": "Weather", "R": "Reminders & tasks", "M": "About me", "D": "About Diya", "L": "Learning", "C": "Chat"}

MESSAGES = [
    # weather
    ("Is it going to rain tomorrow in Delhi?", "W"),
    ("how hot is it in Chennai right now", "W"),
    ("do I need an umbrella today", "W"),
    ("temperature in Oslo?", "W"),
    # reminders and tasks
    ("remind me to call the bank at 3pm", "R"),
    ("add buy milk to my to-do list", "R"),
    ("what's on my list for today", "R"),
    ("did I already pay the electricity bill?", "RM"),
    ("every Monday remind me to water the plants", "R"),
    ("snooze that for an hour", "R"),
    ("mark the dentist task as done", "R"),
    # about the person
    ("my sister's wedding is in December", "M"),
    ("I'm vegetarian", "M"),
    ("where do I work?", "M"),
    ("I moved to Pune last month", "M"),
    ("my mum's birthday is on 4 March", "M"),
    ("what do you remember about my sister?", "M"),
    ("I got an A on my physics test", "M"),
    ("I feel really tired today", "MC"),
    # about Diya
    ("can you read my emails", "D"),
    ("how do I turn on automations", "D"),
    ("are you connected to the internet", "D"),
    ("what's your name", "DC"),
    ("which model are you running on", "D"),
    ("can you set up Notion for me", "D"),
    ("who made you", "D"),
    # learning
    ("how does a transformer neural network work", "L"),
    ("who won the world cup in 2018", "L"),
    ("explain photosynthesis simply", "L"),
    ("what is the capital of Australia", "L"),
    ("translate good morning into French", "L"),
    ("what's 15% of 80", "L"),
    ("how do I fix a KeyError in python", "L"),
    ("give me a recipe for pancakes", "L"),
    ("recommend a good book about habits", "L"),
    # chat
    ("thanks, that helped", "C"),
    ("good night", "C"),
    ("lol you're funny", "C"),
    ("tell me a joke", "CL"),
    ("are you there?", "C"),
    ("ok", "C"),
    ("never mind", "C"),
    ("testing 123", "C"),
    # a poor fit for every category: it must still land somewhere sensible
    ("book me a table for two at 8pm", "RD"),
    ("call my dad", "RD"),
    ("play some music", "DC"),
    ("what should I do this weekend", "LC"),
    ("I'm bored", "C"),
]
