# Study: Atticus for Mac, and what of it is in Diya (2026-10-28)

The owner gave a downloaded copy of **Atticus for Mac** (https://github.com/SaarthurR/atticus-mac, version 1.5.3, MIT per its README) and asked for it to be used in Diya, which runs on Windows. This page says what
Atticus is, which of it can move to Diya and which cannot, and what was done.

## What Atticus is

A voice-first agent for macOS 26: hold a key, say what you need, and it moves windows, opens apps, reads the screen, writes replies, dictates into any text field and runs background agents. Two big files do it:
`Atticus.swift` (7,500 lines, the menu-bar app, windows, screen capture, hotkeys) and `atticus.py` (7,900 lines, the brain: asks an AI client such as Claude Code, Devin, Pi or a local model; remembers; schedules).
It also has HTML pages for its windows, 81 test files with a fake-Mac harness, and a README with a budget for what an ask may cost.

## What cannot move to Windows (and why)

| Part | Why it stays on the Mac |
|---|---|
| The Swift app (hotkeys, menu bar, windows, "point at the spot", drawing on screen) | Apple's own frameworks. There is nothing to translate; a Windows version would be a new program (a Windows port exists, by someone else: github.com/FindlayHi/atticus-windows). |
| "Hands" (clicking and typing in other apps) and moving windows | macOS accessibility and AppleScript. The Windows equivalent is a different API and a different risk; `docs/STUDY_COMPUTER_USE.md` says not now. |
| Dictate anywhere, Meeting Copilot | Microphone and focus handling on the Mac. Diya has local speech-to-text for its own chat only. |
| Routines woken by launchd | macOS's scheduler. Diya already has its own scheduler (reminders, repeating reminders, automations). |
| Agents that hand work to Claude Code, Devin or Pi | Diya is local-only on purpose (`docs/LOCAL_ONLY.md`). |

So "use all of it" is not possible as code: about nine tenths of it speaks to macOS. The ideas are what travel.

## What travelled, and where it is

1. **Learn once, answer at once** ("when I say focus mode, close Slack and open my to-do list"). Atticus saves the commands its AI worked out and replays them with no AI. Diya's version, `diya_shortcuts.py`, saves
   the person's own words instead: a phrase stands for the request they typed, and when the whole message is that phrase, that request is what is answered. Nothing is skipped: the expanded request meets every
   check and approval a typed one does, and a shortcut can never be a yes, a no, or another shortcut. Taught, listed and forgotten by code (`when I say morning check, show me my reminders and tasks`).
2. **A budget that tests enforce** (Atticus: prompt under 10,000 characters, median ask under a cost and 6 seconds). Diya's version, `tests/test_budget.py`, keeps the speed work from growing back: the persona
   at most 1,600 characters, and an ordinary message at most 12 tools and 7,000 characters of tool descriptions (today 1,155, 8 to 10, 5,400).

## Worth porting next, not done

- **"Watch for me"**: set up once, then check every few seconds or minutes with no AI, and tell the person when it fires. For Diya: watch Gmail for a reply from someone, or a calendar change, by code, with a
  card on Home when it happens. Fits the Hark idea of noticing and offering.
- **The fake-world eval harness** (`tests/evals/` in Atticus): scenarios run against a fake Mac with the real brain. Diya has fakes and a scorecard; a scenario file with a fake Google would catch regressions.
- **A Windows dictation hotkey** (hold a key, talk, text lands in any field): a separate small Windows program using Diya's local speech-to-text.

## The licence

MIT, said in the README; the downloaded zip had no `LICENSE` file. No Atticus file was copied into this repository and none of its code is run, so nothing is owed yet, and `THIRD_PARTY_NOTICES.md` names the
source. Before any Atticus code is copied, fetch its `LICENSE` and add the copyright line.

## "Convert to git"

The downloaded folder is not a git repository. It was left as it is (outside this project, untouched). If the wish was to keep a copy of Atticus in this repository for reference, say so: it would be a read-only
folder like `harness/`, and the review already counts one unused copy too many.
