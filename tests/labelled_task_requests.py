"""Hand-written, fictional messages for measuring when the model proposes a Todoist task (docs/ACTIONS_DESIGN.md, D6
and unit A4), with `python diya_actions_bench.py`.

A proposal is only ever recorded, never performed, so the cost of a wrong one is a card the owner has to turn down:
noise, and the habit of clicking without reading. The question is how often the model reaches for the tool when
nobody asked it to. ASKED are messages that plainly ask for a task to be added; every category in NOT_ASKED is a
message that does not, including the ones a small model plausibly confuses with it (a need, a reminder, a question
about the list, a mention of the word "task"). AMBIGUOUS are messages a reasonable person could mean either way:
they are shown by the benchmark and never scored.

The cases were written by the author of the measurement, so they show what a guard or a model does with THESE
phrasings, NOT how either does on the way a real person writes.
"""

ASKED = [
    "Add a task to buy oat milk",
    "add 'call the dentist' to my Todoist",
    "Put 'renew passport' on my to-do list",
    "Can you add a task: send the invoice by Friday?",
    "Please add buy bread to my todo list",
    "Create a Todoist task to book the vet for next Monday",
    "Add a task called prepare slides, due tomorrow at 5pm",
    "New task: pay the electricity bill",
    "Add 'water the plants' to Todoist",
    "Could you put finish the report on my task list?",
    "add task call mum",
    "Make a task to renew my licence",
    "Please create a task for me: buy a birthday card",
    "Add to my to-do list: take the bins out",
    "Put 'email Sam' on my Todoist for tomorrow",
    "I want to add a task: clean the garage",
    "Hey Diya, add a todo to order printer ink",
    "Add a task for Friday: submit the expense report",
    "Log a task to fix the bike tyre",
    "Add one more task, to call the plumber",
    "todoist: add buy stamps",
    "Add a to-do: update the CV",
    "Can you create a task to back up my laptop this weekend",
    "add a task 'read chapter 4' due tonight",
    "Put it on my to-do list: pick up the dry cleaning",
]

NOT_ASKED = {
    "general questions": [
        "What's 9 times 7?",
        "What's the capital of Australia?",
        "Explain how a bicycle stays upright",
        "Translate 'good morning' into Spanish",
        "Tell me a joke",
        "How many days are there until Christmas?",
        "Write a haiku about rain",
        "What's the difference between a virus and a bacterium?",
    ],
    "weather and search": [
        "What's the weather like in Paris?",
        "Search the web for the best oat milk",
        "Will it rain tomorrow in London?",
        "Look up the opening hours of the post office",
    ],
    "plain facts": [
        "My flight is on Friday at 6",
        "I have a dentist appointment next Tuesday at 10",
        "I moved to Berlin last month",
        "My sister's birthday is on the 14th",
        "I'm allergic to peanuts",
    ],
    "reminders": [
        "Remind me to call mum tomorrow at 5pm",
        "Set a reminder for Friday at 3pm",
        "Don't let me forget the passport",
        "What reminders do I have?",
        "Make a note to call the plumber",
    ],
    "reading the list": [
        "What's on my to-do list?",
        "What tasks do I have today?",
        "List my Todoist tasks",
        "Do I have anything overdue?",
        "Show me my open tasks",
        "How many tasks are left on my list?",
    ],
    "the word task, not asking": [
        "That task was exhausting",
        "I finished my to-do list for today",
        "My tasks today were so boring",
        "Todoist is a good app, isn't it?",
        "How do I use labels in Todoist?",
        "I prefer paper to-do lists",
        "Is Todoist free?",
    ],
    "needs and wishes": [
        "I need to buy milk",
        "I should call mum tonight",
        "I have to finish the report by Friday",
        "I really need to clean the garage this weekend",
        "I forgot to pay the electricity bill",
        "I want to learn Spanish this year",
        "I'd like to read more books",
        "I'm running low on printer ink",
    ],
    "other requests": [
        "Add 3 and 4",
        "What's the total if I add 15% tip to 40?",
        "Send an email to Sam",
        "Turn on the living room light",
        "Book me a table for two",
        "Write a short poem about the sea",
        "Make a list of things to pack for a weekend trip",
        "Add some humour to this sentence: the meeting was long",
    ],
}

AMBIGUOUS = [
    "Add milk to my shopping list",
    "Put milk on the list",
    "Remember to buy milk",
    "todo: call the bank",
    "I need to remember to call mum, can you help?",
    "Please note that I need to call Sam",
]


def all_not_asked():
    return [text for texts in NOT_ASKED.values() for text in texts]
