"""Hand-written, fictional messages for measuring what the model does with a repeat (docs/SCHEDULE_DESIGN.md, D7 and unit R3).

`add_reminder(content, due_at, repeat)` makes a reminder repeat only if the person said how. The risk is the one reminders
and tasks already showed: a small model makes something happen that was not asked for, here "every ..." from a message that
said it once. Each message goes through the real Agent and the real local model (`python diya_schedule_bench.py`) and the
outcome is scored by what was SAVED, not by what the model said. The messages were written by the author of the guard, so
they show what the guard and the model do with THESE phrasings, not how either does on the way a real person writes.
"""

# Asked for a reminder that repeats, in a way diya_repeat reads. (message, the rule it means, without any "#date" a rule
# that counts days carries). The model should save a repeating reminder with that rule.
REPEAT_ASKED = [
    ("Remind me every day at 8am to take my pills", "daily@08:00"),
    ("remind me every morning to stretch", "daily@09:00"),
    ("Remind me every evening at 7pm to call mum", "daily@19:00"),
    ("Remind me daily at noon to drink water", "daily@12:00"),
    ("Remind me every night at 10pm to lock up", "daily@22:00"),
    ("Remind me every weekday at 8:30 to check the dashboard", "weekdays@08:30"),
    ("remind me on weekdays at 7am to pack my lunch", "weekdays@07:00"),
    ("remind me every weekday morning to check my email", "weekdays@09:00"),
    ("Remind me every Monday at 9am to take out the bins", "weekly:0@09:00"),
    ("Remind me every Wednesday to put the recycling out", "weekly:2@09:00"),
    ("remind me every Friday at 5pm to send the timesheet", "weekly:4@17:00"),
    ("Set a reminder every Saturday at 10am to clean the car", "weekly:5@10:00"),
    ("Remind me every Sunday evening to plan the week", "weekly:6@18:00"),
    ("can you remind me every Monday morning to review my goals", "weekly:0@09:00"),
    ("Please remind me every Tuesday and Thursday at 6pm to water the plants", "weekly:1,3@18:00"),
    ("Remind me on the 1st of every month to pay rent", "monthly:1@09:00"),
    ("remind me every month on the 15th at 9am to check my budget", "monthly:15@09:00"),
    ("Remind me every 3 days to water the cactus", "every:3@09:00"),
    ("remind me every other day at 8pm to take my vitamins", "every:2@20:00"),
    ("Remind me every 2 weeks at 10am to submit the report", "every:14@10:00"),
]

# Asked for a reminder that repeats, in a way diya_repeat will not read. Nothing should be saved as a repeating reminder,
# and nothing should be saved as a one-off that quietly drops the "every": the person should be told why.
REPEAT_UNSUPPORTED = [
    "Remind me every hour to stretch",
    "Remind me every 30 minutes to drink water",
    "Remind me every year on 3 March to call mum",
    "Remind me every second Tuesday to water the ferns",
    "Remind me every day until June to take my medicine",
    "remind me every weekend to call my sister",
    "Remind me twice a day to take my pills",
    "Remind me every week to back up my laptop",
    "Remind me on the last Friday of every month to send the invoices",
]

# Asked for a reminder that does NOT repeat, some with a time and some with the word "every" in another sense. Each must be
# saved as a one-off (or refused for a time it cannot read), never as a repeating reminder.
ONE_OFF = [
    "Remind me tomorrow at 5pm to call mum",
    "remind me on Friday at 3pm to send the report",
    "Remind me in 2 hours to check the oven",
    "Remind me to take my pills at 9pm",
    "Remind me to call the bank on Monday",
    "Remind me to renew my passport",
    "Remind me tonight to lock up",
    "Remind me at 6pm to start dinner",
    "Remind me to give every kid their medicine tomorrow at 8am",
    "remind me to check every window before bed tonight",
    "Remind me to call everyone on Friday at 5pm",
    "Remind me to buy a present for every person on the list on Saturday",
]

# Not a request for a reminder, though some mention a repeat. Nothing at all should be saved.
NOT_A_REMINDER = [
    "I go to the gym every Monday and Wednesday",
    "What time is the bin collection every week?",
    "Every day I walk five kilometres",
    "My flight leaves every Tuesday",
    "I take my pills every morning",
    "Do I have anything on every Friday?",
    "What repeats every week?",
    "My sister calls me every Sunday",
    "What's 9 times 7?",
    "What's the weather in Leeds?",
    "Explain what a mortgage is",
    "I need to buy milk",
]


def all_messages():
    return ([text for text, _ in REPEAT_ASKED] + REPEAT_UNSUPPORTED + ONE_OFF + NOT_A_REMINDER)
