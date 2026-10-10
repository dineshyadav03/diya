# Reminders

Diya can remember something for you and tell you when its time comes. The design, and what was measured with the real
model, is in [PROACTIVITY_DESIGN.md](PROACTIVITY_DESIGN.md); this page is how to use it.

## Saying it

In the chat: "remind me to call mum tomorrow at 5pm", "set a reminder for Friday at 3pm to send the report", "don't let
me forget the passport". Diya saves one only if your message asks for one, and the time is read by code, not by the
model:

- Read: today, tonight, tomorrow, the day after tomorrow, weekday names, "in 2 hours", "in 3 days at 3pm", a date such
  as "3 October" or "2026-10-03", and a time as 5pm, 5:30pm, 17:30, noon, or morning (09:00) / afternoon (15:00) /
  evening (18:00). A day with no time is 09:00, and Diya says so.
- Refused on purpose, because two people mean two things: "next Friday", a bare "at 5" (morning or evening?), "3/4"
  (March 4th or April 3rd?), midnight. Also refused: "next week", "the weekend", "after lunch", "in five minutes" (it
  reads digits, not number words). Say it another way, or add the reminder on the Reminders page.
- If the small model changes the time you gave (turns "morning" into "8am", drops the date), the reminder is not saved
  and it asks you again. That is the safe failure: a reminder at a time you never said would fire at the wrong time.

Without a time, a reminder is saved but never fires, and Diya tells you so.

## Seeing it

The **Reminders** page (linked from the chat header on a wide screen, and from History and Memory) lists what is
**due now**, what is **coming up** and what has **no time set**. Add one there ("Remind me to..." and a time such as
"Friday 5pm"), and mark one **Done**. The page looks again once a minute while it is open, and the chat header shows how
many are due. A closed browser tab learns nothing: for that, use the notifier below.

## Being told outside the app (optional)

```bash
python diya_notify.py --test      # show one notification that says nothing about your reminders
python diya_notify.py --dry-run   # say what it would tell, and tell nothing
python diya_notify.py             # one pass: tell each reminder that has come due, once
```

It shows a Windows notification (through the PowerShell that ships with Windows; nothing is installed). Each reminder is
told once; if a notification could not be shown it is tried again on the next pass. If many come due at once (the
computer was off), the first few are shown and the rest as one "N more reminders are due". Set
`DIYA_NOTIFY_SHOW_TEXT=0` to show "A reminder is due" instead of the words, for a screen other people can see. It logs
counts and reminder ids (never the words) to `notify_log.txt`, or `DIYA_NOTIFY_LOG_PATH`.

Like Dreaming, it does one pass and never loops, so run it on a schedule. **Nothing registers itself**; this is the
one step left to you. For a pass every five minutes, in PowerShell, from the folder that holds `diya_notify.py`
(change the two paths to yours; `pythonw.exe` has no console window):

```powershell
$action   = New-ScheduledTaskAction -Execute "C:\Path\To\pythonw.exe" -Argument "diya_notify.py" -WorkingDirectory "C:\Path\To\diya"
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "Diya_Notify" -Action $action -Trigger $trigger -Settings $settings
```

If you keep Diya's data outside the code folder (`DIYA_DATA_DIR`, see the README), set it as a user environment variable so this task finds the
same database as the API does; see [Dreaming](dreaming.md), "Files and settings".

The two battery switches matter on a laptop: without them Windows quietly does not run the task on battery. Run it as yourself, while you are logged in (that is the default): a notification needs your desktop. Remove it with
`Unregister-ScheduledTask -TaskName "Diya_Notify" -Confirm:$false`. Like Dreaming's task, it runs the files in the folder
as they are, so a change to the code takes effect at the next pass. Nothing fires while the computer is off or asleep;
a reminder that came due then is told at the first pass afterwards.

## Repeating reminders

Say it the way you would: "remind me every Monday at 9am to take out the bins", "remind me on weekdays at 8:30 to check the
dashboard", "remind me on the 1st of every month to pay rent", "remind me every 2 weeks at 10am to submit the report". The repeat
is read by code from **your own words**, not from what the model passes on (a small model splits the time off, paraphrases, or
forgets that it repeats, so its version is not trusted): what you said is what is saved, and the answer says it back in words,
with when the first one falls.

- Read: every day / daily / every morning (09:00) / every evening (18:00); every weekday; every Monday, every Tuesday and
  Thursday; every month on the 15th (29-31 means the last day of a shorter month); every 3 days, every 2 weeks, every other day.
  A time of day is part of it ("every day at 8am"); with none it is 09:00, and Diya says so.
- Refused on purpose, with the reason: more often than once a day ("every hour"), an end or a count ("until June", "for 5
  weeks": stop it from the Scheduled page instead), "every second Tuesday", "the last Friday", "every weekend", a bare "every week"
  or "every month", and yearly. A message with two repeats in it ("every Monday and every Friday at 5pm") is not guessed at either.
- A repeat is part of the request only when it sits in the request itself ("remind me every day at 8am to...", "every day at
  8am, remind me to..."). "Remind me to call mum tomorrow, I do it every Sunday" is a single reminder.

Each time one falls it becomes an ordinary reminder, so it shows under **Due now**, the notifier tells you once, and **Done**
closes it. If the computer was off for a week, you get **one** reminder for the latest time that passed, not seven; the rest are
recorded as missed. If you never marked the last one done, it is closed ("lapsed") when the next one arrives, so a daily reminder
you ignored does not pile up.

## The Scheduled page

Linked from every page. It lists your repeating reminders (running, paused, stopped) with when each next falls, and a plain-words
record of what happened lately ("Skipped the next time of ...", "Missed 5 earlier times of ... (Diya was not looking); made one
reminder"). You can add one there, **Pause**, **Resume**, **Skip next**, or **Stop** it (Stop takes two presses and cannot be
undone; a stopped one stays in the list, greyed). Editing one is not offered: stop it and make a new one. The model can make a
repeating reminder and read the list; it cannot pause, skip or stop one. At most 20 are running at once.

## Pushing a reminder back

On the Reminders page every reminder that has a time has **10 min**, **1 hour** and **Tomorrow morning** buttons. The reminder's
time moves, it is told again then, and a repeating reminder it came from is not touched. A reminder that is already done cannot
be pushed back.

## The Today page

What is due now and later today, the tasks that are overdue or due today, and which repeating reminders make one next. It is
built in code from your own reminders and tasks: nothing on it is written by a model, so there is nothing to double-check. A
reminder with no time, or a task with no date, is counted at the bottom and left out of the day. It only shows; ticking off and
pushing back are done on the page each thing lives on.

## Limits

No editing a reminder's time or words (a repeating reminder: stop it and make a new one). The time reader knows a small set of
phrases and refuses the rest. Nothing is told outside the app unless you schedule the notifier above, and nothing fires while the
computer is off or asleep: it is caught up, as one reminder, at the first look afterwards. Tasks do not repeat (a thing that must
come back and tell you is a repeating reminder).
