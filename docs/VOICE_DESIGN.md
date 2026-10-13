# Voice in: tap to talk, and not turning silence into words

> **Status (2026-10-13):** built (`frontend/components/VoiceBar.jsx`, `frontend/lib/microphone.mjs`, `WhisperTranscriber.transcribe` in `diya_web.py`). The owner sent a screenshot of the chat: every
> time they used the microphone the chat showed a message that said only "You", and Diya answered it ("I'm Diya, your personal assistant ..."). They also said the button should not have to be held:
> tap to start, tap again to stop.

## What was wrong

1. **Whisper invents words for silence.** Reproduced with the real model (Whisper `base`, the one Diya uses): four seconds of pure silence came back as "You", every time. Faint hiss and fan noise
   came back empty; real speech came back right ("Hey dear, what is the weather in Pune today?": it mishears "Diya", a known limit). So the "You" messages were recordings with no sound in them.
2. **Why there was no sound:** the microphone that was listening was not the one being spoken into. This computer has a virtual cable and a Voicemeeter among its inputs and an AirPods set that is not
   connected; the browser's default can be any of them, and a virtual cable gives perfect silence. Nothing in the page noticed.
3. **Hold to talk** is not how a microphone is expected to work.

## What it does now

- **Tap the mic to start listening; tap it again to stop and send.** While it listens the status line says which microphone it is using ("Listening (Microphone Array ...). Tap the mic again when you are
  done."), the orb swells with the sound it hears, and a Cancel button throws the recording away. A recording is stopped and sent by itself after 60 seconds, and leaving the page lets go of the
  microphone. A recording shorter than 0.6 seconds was a double tap and says so.
- **A recording with no sound is never sent.** The page measures the loudest the microphone got while it listened (`SILENT_BELOW`, 0.04 on a 0 to 1 scale; speech into a laptop microphone reaches 0.2 or
  more). Below that nothing is uploaded, and it says: `Nothing was heard from "<that microphone>". Tap the mic and try again: I will use a different microphone this time.` That microphone, and the same
  physical one under another id, is not offered again this session, so each silent try moves on to the next real microphone. The first one that picks up sound is remembered and tried first next time.
  If every microphone the browser can see has been silent, it says so once and starts over: `none of the microphones ... picked up any sound`, with where to look in Windows' sound settings.
- **The server also refuses to read silence.** `WhisperTranscriber.transcribe` runs Whisper only over the stretches a speech detector (`vad_filter`) finds, and does not carry text from one stretch into
  the next. Measured on the same four files: silence, hiss and noise all give `""`; the speech gives the same words as before. An empty transcript is shown as "I couldn't hear any words in that."

## What is not verified

A real microphone. The behaviour above was exercised in a real browser with stand-in microphones (a silent one first, then one carrying a tone): the first tap listened to the silent one and sent nothing,
the second tap used the other microphone and the message arrived and was answered. Whether the owner's real devices behave the same is theirs to find out; if the microphone still errors, the exact message
is what is needed. Speech recognition quality (Whisper `base` mishearing names) is unchanged.
