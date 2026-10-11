# Replies that appear as they are written, the orbs, and the microphone

> **Status (2026-10-11):** built. The owner said a reply took a long time and wanted to see it come word by word, wanted the orbs back, and said the microphone always gave an error.
> Speed itself is in `docs/SPEED_DESIGN.md`; this is what the screen does.

## Replies word by word

`POST /api/chat/stream` runs the same turn as `/api/chat` and tells it as it happens, one JSON object per line: `start` (the chat), `delta` (the next piece of the reply), `reset` (the text so far was only a
preface to a tool call, take it back), `tool`, `wait` (still working, every ten seconds, so a model that is slow to load does not look like a dead connection), then `done` with exactly what `/api/chat`
returns, or `error` with the reason and the chat the message was kept in. The chat page uses it: the orb shows while the model reads the question, the words appear as they are written, and the whole reply
replaces them when it is done. If the API has no such route (an older one still running) the page asks for the whole reply instead.

Two things are deliberately not streamed: a message that is only telling Diya a fact (its reply is shortened afterwards, so it is shown whole), and anything the page could not show truthfully (a failure
half way removes the half reply and shows the usual "Didn't send" with Try again).

The turn runs in one thread of its own, not in the response's: what a turn knows about the message it is answering (is this really a reminder request?) is kept per thread, and a streamed response is
read from several. Measured with the real model on this CPU: the first word of "hey" about two seconds after sending when the model is not primed, and a word about every 0.2 seconds after that (the
model writes about five tokens a second here); streaming does not make an answer shorter, it makes it readable while it is being written.

## The orbs

`components/Orb.jsx`: pure CSS (no library, nothing downloaded), in the theme's own accent colour. A breathing sphere with a turning ring while Diya is thinking; the sphere swells with how loud the microphone
is while you hold to talk; the ring pulses while a reply is read aloud. With "reduce motion" switched on in the system the animations stop and a still sphere is left. (The seven decorative libraries
removed in the redesign stay removed: `docs/UI_DESIGN.md` said the orb would not come back unless asked for, and it was asked for.)

## The microphone

The old button opened the default microphone once, and every failure said "did you allow mic access?". On this computer there are many audio devices (a virtual audio cable, Voicemeeter, AirPods that are
not connected), so the default input is often one that cannot start. Now: the default is tried, then, if it will not start, each real microphone in turn, remembering the first that works; a refusal is never
retried (another device would be refused too); and each failure says what to do: the secure address, the browser's per-site permission, Windows's privacy setting, another app holding it, a default
that is a disconnected headset. Letting go of the button before the browser had finished opening the microphone no longer leaves it recording; the button keeps hearing the release even if the pointer drifts
off it; a tap shorter than 0.4 seconds says "hold the button while you speak" instead of sending nothing; and the "recorded 12.3 KB" line after every recording is gone.

**Not verified:** a real microphone. Which device the owner's browser picks, and whether Whisper then hears them, can only be found by pressing the button; if the message still appears, it now says which
of the five causes it is.
