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
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName "Diya_Notify" -Action $action -Trigger $trigger -Settings $settings
```

Run it as yourself, while you are logged in (that is the default): a notification needs your desktop. Remove it with
`Unregister-ScheduledTask -TaskName "Diya_Notify" -Confirm:$false`. Like Dreaming's task, it runs the files in the folder
as they are, so a change to the code takes effect at the next pass. Nothing fires while the computer is off or asleep;
a reminder that came due then is told at the first pass afterwards.

## Limits

No snooze, no editing a reminder's time, no "every Monday" (a repeating reminder is a workflow, which is a later,
separate piece of work). The time reader knows a small set of phrases and refuses the rest.
