# The interface, redesigned: one calm system in two themes -- design spec

> **Status (2026-10-10):** built (U1-U3), checked with the design rig in both themes at three widths (below), nothing pushed. The owner said they did not like the interface and pasted two design systems as references
> (Notion's, a warm paper canvas under near-black type with one blue; and xAI's, a near-black canvas with hairlines, outline pills and
> small monospace labels), and said to go for any of them. This records what was chosen, why, and what changes, so the choice can be
> reversed or adjusted by changing tokens rather than hunting through pages.

## 1. What was wrong, in the current interface

- **A header that is a wall of buttons.** Nine pill buttons plus "Test voice" and "Speak" wrap onto three rows on a laptop-width
  window, and a decorative spinning orb sits beside the name. Navigation and the chat's own controls are the same kind of thing, in the
  same place, on every page, and each page repeats the whole header (nine copies, and each new page meant editing all of them).
- **A composer that is a drawing.** The message box is a fixed 371 x 104 px mock, absolutely positioned, with a WebGL ring on Send, a
  voice-reactive glow, an animated border and a "liquid" menu for New chat. It is the most decorative thing on the screen and the thing
  used most.
- **Seven decorative libraries** (`voice-glow`, `border-beam`, `liquid-gooey`, `metal-fx`, `thinking-orbs`, `img-fx`, `three`) for
  effects nothing in the product needs, one of which (`img-fx`) was already switched off because it hung a browser.
- **Dark only, with one warm accent (oat).** No light theme at all, and the accent colour was spent on everything at once.

## 2. Decisions

### D1. Two themes from the two references, one set of tokens

- **Light = Notion's system.** A warm paper page (`#f6f5f4`), white cards with a 1 px hairline and 12 px corners, near-black type,
  muted text `#615d59`, and a single blue (`#0075de`) that is the only colour on a primary action. Pill-shaped primary buttons.
- **Dark = xAI's system.** A near-black page (`#0a0a0a`), charcoal cards (`#191919`) with a 1 px hairline and no shadow, white type,
  outline pills, small uppercase monospace labels ("eyebrows") for section names. The primary action is the rare white pill.
- The theme follows the operating system and can be set to Light, Dark or System at the foot of the sidebar; the choice is kept in
  this browser only, and the page never flashes the wrong theme on load.
- Everything is a CSS variable (`--bg`, `--surface`, `--text`, `--text-dim`, `--border`, `--border-strong`, `--accent`, `--link`,
  `--danger-text`, ...), so a third theme or a different blue is one block of `globals.css`.

### D2. One shell: a sidebar on a laptop, a menu on a phone

A single component (`components/AppShell.jsx`) owns the navigation for every page: the brand, the pages in three groups (the day:
Today, Reminders, Scheduled, Tasks; the assistant: Chat, History, Memory; the system: Connections, Actions), a count on Reminders (due
now) and Actions (waiting for you), and the theme control. From 880 px wide it is a 248 px sidebar; below that it is a slim top bar
with a Menu button that opens the same list (44 px targets, Escape or a tap outside closes it, the current page is marked with
`aria-current`). Pages no longer carry a header: they say `<AppShell>` and put their content inside it. A link to every page from every
page is now one thing to check, not nine.

### D3. A composer that is a text box

A rounded white (or charcoal) box with the message field, a Hold-to-talk button, a Send button that is a filled pill when there is
something to send, and a quiet "New chat" that asks for confirmation inline (no liquid menu). The same props, the same failure
messages, the same rule that it is off while a saved chat is loading or failed to load. "Listening..." and "Transcribing..." are a
text chip. Diya working is three quiet dots, never a spinner; speaking is a thin line along the top of the composer. Nothing moves when
the person has asked the system for reduced motion.

### D4. Messages that read like a document

The person's messages are a soft, right-aligned block; Diya's are plain text on the page (no bubble, as in a document or a log), with
the tools it used shown as small labelled chips ("checked your tasks"). Failed sends keep their dashed outline, reason and Try again.

### D5. Type and shape

System fonts (Inter first if it is installed; nothing is downloaded, so the app still makes no request to anyone). Headings 650 weight
with slightly tight tracking, body 15-16 px at 1.5, section labels in monospace capitals at 12 px. Corners: 8 px on fields and small
buttons, 12 px on cards, a full pill on primary actions. No shadows (one hairline is the only depth), and no gradients except the
loading shimmer.

### D6. Accessibility is a gate, not a goal

Every text pairing is computed (WCAG 2.x, not eyeballed) and the design rig audits every visible text run in both themes: body text at
least 4.5:1, and the edges of fields and buttons at least 3:1 (`--border-strong`; the lighter `--border` hairline is only ever a
decoration around a card). Visible focus on everything, 44 px touch targets on a phone, no colour-only state (an overdue task says
"Overdue"), a skip link, and `prefers-reduced-motion` honoured.

## 3. Palette (measured)

| Token | Light | Dark | Used for |
|---|---|---|---|
| `--bg` | `#f6f5f4` | `#0a0a0a` | the page, the sidebar |
| `--surface` | `#ffffff` | `#191919` | cards, the composer, fields |
| `--surface-hover` | `#efedeb` | `#262626` | a hovered row or button |
| `--text` | `#000000` (19.3:1) | `#ffffff` (19.8:1) | headings and body |
| `--text-dim` | `#615d59` (6.0:1 on the page, 6.5:1 on a card) | `#8d9197` (6.3:1, 5.6:1) | secondary text |
| `--accent` / on it | `#0075de` / `#ffffff` (4.6:1) | `#ffffff` / `#0a0a0a` (19.8:1) | the primary action |
| `--link` | `#005bab` (6.3:1) | `#62aef0` (8.3:1) | links and the focus ring |
| `--danger-text` | `#b42318` (6.6:1) | `#ff7a6b` (6.9:1) | errors, "Overdue" |
| `--border` | `#e6e6e6` | `#212327` | the hairline round a card (decoration) |
| `--border-strong` | `#86817b` (3.6:1) | `#70757b` (3.8:1) | the edge of a field or button |

## 4. Units

| Unit | What |
|---|---|
| U1 | The tokens and a rewritten `globals.css`; `layout.js` (theme without a flash, theme colour); `AppShell` with the sidebar, the phone menu, the counts and the theme control; every page moved into it. |
| U2 | The chat: the composer, the messages, the empty and loading states, the tool chips; the seven decorative libraries removed from `package.json`, the lock file and the notices. |
| U3 | Verification: the design rig (contrast audit, overflow, page errors, the failure scenarios) in both themes and on a phone, the tests updated to say what they now mean (every page uses the shell; the shell links to every page), and a real-browser pass. |

## 5. What does not change

Behaviour. The same routes, the same proxy, the same messages for every failure, the same chat logic (loading a saved chat, stale
loads, retry, voice recording, speaking replies), and the same class names on the content pages (`memory-fact`, `reminder`, `task`,
...), restyled. A page's own tests still read its own source.

## 6. What needs the owner's yes

- **Dark is xAI-like and light is Notion-like.** If one of them should be the only look, delete the other block of variables.
- **The decorative libraries are gone.** The Hold-to-talk glow and the orb are not coming back unless asked for; the product's
  state is shown in words and two quiet motions instead.
- **The flame mark stays** (the one asset that is the product's own), shown at 24 px in the sidebar.

## 7. What was checked, and what was not

- **The palette**: `tests/test_frontend_theme.py` computes the WCAG contrast of every pairing in the table above from the stylesheet's own
  values, in both themes (text 4.5:1, the edge of a field or button 3:1), checks the two copies of the dark theme match, that the theme
  is applied before first paint to only the two names the sidebar writes, that the stylesheet asks nobody for anything, that reduced
  motion is honoured and that touch targets are 44 px on a phone. Weakening one colour makes it fail (tried).
- **The pages**: the design rig (`frontend/tools/design-rig`) in a headless Edge against the dev server: every chat and History
  scenario (the failure and retry paths included) and the seven content pages (Today, Reminders, Scheduled, Tasks, Memory, Actions,
  Connections) against a scratch database. Light: 64 screens and 188 checks for the chat and History at laptop and phone width, and 21
  screens and 63 checks for the content pages at laptop, phone and the narrowest phone (320 px). Dark: 96 screens and 282 checks
  (the same, plus the narrowest phone), and 21 screens and 63 checks for the content pages. No check failed, no text run failed the
  contrast audit, and there was no horizontal overflow and no page error in any of them.
- **By eye**: the chat in both themes at laptop and phone width, Today at laptop width, and a click-through in the browser pane.
- **Not checked**: a real phone, Safari or Firefox (Edge only); the Hold to talk glow and the orb are gone, so the voice states
  ("Listening...", "Transcribing...") are checked as text, not by speaking into a microphone; the audit measures text, not the edge of
  every control (that is the palette test's job); and "does it feel right" is the owner's call, which is why the whole look is tokens.
