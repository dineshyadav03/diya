'use client'

import { useLayoutEffect, useRef, useState } from 'react'
import dynamic from 'next/dynamic'
import { VoiceBeam } from 'voice-glow'
import { BorderBeam } from 'border-beam'
import { Liquid } from 'liquid-gooey'
import { ThinkingOrb } from 'thinking-orbs'
import { apiBase } from '../lib/api'

// A plain host element (not a component) because MetalFx measures its child
// as a DOM host. Shared so the ring-on, ring-off and loading states are the
// same button.
const SEND_BUTTON = (
  <button type="submit" className="mock-vchat-btn" aria-label="Send" suppressHydrationWarning>
    <span className="mk-ico mk-ico-arrow" />
  </button>
)

// WebGL2 support can only be checked client-side (isMetalFxSupported()), so
// SSR and the client render differently -- a real hydration mismatch, not
// just a warning. Same fix as img-fx: skip the server render entirely.
// dynamic() renders nothing until its chunk loads, and Send is MetalFx's
// child -- so the fallback is the plain button, or Send would vanish for
// the moment after the first keystroke.
const MetalFx = dynamic(() => import('metal-fx').then((m) => m.MetalFx), {
  ssr: false,
  loading: () => SEND_BUTTON,
})

// Authored width of the chat-input mock this bar is ported from
// (Jakubantalik/Libraries.dev, sites/home/src/examples/beam-mocks.tsx
// ChatInputMock + public/assets/examples.css .mock-vchat) -- their own
// voice.tsx demo page shrinks VoiceBeam's `scale` by clientWidth/371 so
// the effect's px-authored geometry still matches a narrower host.
const CHAT_WIDTH = 371

// Geometry of the "+" -> "New chat" liquid menu (button and pill sizes come
// from .mock-vchat-btn / .mock-vchat-btn--liquid.mock-vchat-agent).
// At rest the pill sits centred behind the "+" and scaled down so its blob is
// wholly inside the plus's -- the two read as one droplet. Opening moves it
// out to the right, past the goo's reach (blur 6) so the pieces end up clearly
// separate. The group is sized for the open footprint, as the library asks.
const MENU_BTN = 36
const MENU_PILL = 84
const MENU_GAP = 16
const PILL_REST_X = -(MENU_BTN + MENU_PILL / 2 - MENU_BTN / 2) // centre-to-centre
const MENU_WIDTH = MENU_BTN + MENU_GAP + MENU_PILL

function useFitScale() {
  const ref = useRef(null)
  const [scale, setScale] = useState(1)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const measure = () => setScale(Math.min(1, el.clientWidth / CHAT_WIDTH))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, scale]
}

export default function VoiceBar({ onSend, onSystemMessage, onNewChat, processing }) {
  const [value, setValue] = useState('')
  const [stream, setStream] = useState(null)
  const [recording, setRecording] = useState(false)
  const [micDisabled, setMicDisabled] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  const [fitRef, fitScale] = useFitScale()
  // Same test submit() uses, so the ring is lit exactly when Send would send.
  const hasText = value.trim().length > 0

  function submit(text) {
    const trimmed = text.trim()
    if (!trimmed) return
    setValue('')
    onSend(trimmed)
  }

  async function startRecording() {
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioChunksRef.current = []
      const mediaRecorder = new MediaRecorder(mic)
      mediaRecorder.ondataavailable = (e) => audioChunksRef.current.push(e.data)
      mediaRecorder.onstop = () => sendRecording(mediaRecorder)
      mediaRecorder.start()
      mediaRecorderRef.current = mediaRecorder
      setRecording(true)
      setStream(mic)
    } catch (err) {
      onSystemMessage('Microphone error: ' + err.message + ' -- did you allow mic access?')
    }
  }

  function stopRecording() {
    const mediaRecorder = mediaRecorderRef.current
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop()
      mediaRecorder.stream.getTracks().forEach((t) => t.stop())
    }
    setStream(null)
    setRecording(false)
  }

  async function sendRecording(mediaRecorder) {
    const mimeType = mediaRecorder.mimeType || 'audio/webm'
    const blob = new Blob(audioChunksRef.current, { type: mimeType })

    const kb = (blob.size / 1024).toFixed(1)
    onSystemMessage(`recorded ${kb} KB · ${mimeType}`)
    if (blob.size < 1000) {
      onSystemMessage("that's suspiciously small -- the mic may not have actually captured audio")
    }

    setMicDisabled(true)
    const ext = mimeType.includes('mp4') ? 'mp4' : mimeType.includes('ogg') ? 'ogg' : 'webm'
    const form = new FormData()
    form.append('audio', blob, 'recording.' + ext)
    let data
    try {
      const res = await fetch(`${apiBase()}/api/transcribe`, { method: 'POST', body: form })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      data = await res.json()
    } catch {
      // The server didn't answer. This used to throw here, leaving the mic disabled on
      // "Transcribing..." for good; give it back and say what happened.
      setMicDisabled(false)
      onSystemMessage("Couldn't reach Diya's server to transcribe that. Hold the mic to try again.")
      return
    }
    setMicDisabled(false)

    if (data.error) {
      onSystemMessage('Transcription error: ' + data.error)
    } else if (data.text && data.text.trim()) {
      submit(data.text.trim())
    } else {
      onSystemMessage("Didn't catch that -- try again")
    }
  }

  return (
    <div className="bar-dock">
      <div ref={fitRef} className="voice-fit">
        {/* border-beam's `line` type is tuned against voice-glow's dark stage
            so the two read as one family (see voice-glow's own source
            comment). Gated on the same condition as voice-glow: the composer
            is the one surface that's always on screen, so it stays quiet when
            idle and only lights up while Diya is actually listening,
            thinking or speaking. */}
        <BorderBeam size="line" theme="dark" active={!!stream || !!processing}>
          <VoiceBeam
            stream={stream}
            active={!!stream || processing}
            processing={processing}
            type="default"
            theme="dark"
            scale={fitScale}
          >
            <form
              className="mock-vchat"
              aria-label="Message Diya"
              onSubmit={(e) => {
                e.preventDefault()
                submit(value)
              }}
            >
              <input
                className="mock-vchat-input"
                type="text"
                placeholder="Message Diya..."
                aria-label="Message"
                autoComplete="off"
                spellCheck={false}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                suppressHydrationWarning
              />
              {/* Two real phases the old build gave zero feedback for --
                  capturing your voice, then Whisper turning it into text. */}
              {(recording || micDisabled) && (
                <div className="mic-status" role="status">
                  {/* thinking-orbs ships exactly two size presets, 64 and 20. Any other
                      size makes it throw while rendering, which takes the whole page
                      down ("Application error") the moment the mic is held. */}
                  <ThinkingOrb state={recording ? 'listening' : 'working'} size={20} theme="dark" />
                  {recording ? 'Listening...' : 'Transcribing...'}
                </div>
              )}
              <div className="mock-vchat-row">
                {/* liquid-gooey's own quickstart example is exactly this: a
                    plus button that splits into a menu like a droplet. Real
                    use here -- New Chat wipes the thread, so it asks first
                    instead of firing on a single tap.
                    Flex + centre on the group: its items are inline-block, so
                    left alone an icon button and a text button sit on different
                    baselines and land a few px apart. Buttons are transparent
                    (.mock-vchat-btn--liquid) -- the liquid is their surface. */}
                <Liquid
                  className="liquid-menu"
                  style={{ display: 'flex', alignItems: 'center', width: MENU_WIDTH, height: MENU_BTN }}
                >
                  <Liquid.Item x={0} transition="bouncy">
                    <button
                      type="button"
                      className="mock-vchat-btn mock-vchat-btn--liquid"
                      aria-label={menuOpen ? 'Close menu' : 'Menu'}
                      aria-expanded={menuOpen}
                      onClick={() => setMenuOpen((o) => !o)}
                      suppressHydrationWarning
                    >
                      <span className={'mk-ico mk-ico-plus' + (menuOpen ? ' mk-ico-x' : '')} />
                    </button>
                  </Liquid.Item>
                  {/* The wrapper's pointer-events matter: at rest it is stacked
                      on top of the "+" and would swallow clicks meant for it. */}
                  <Liquid.Item
                    x={menuOpen ? MENU_GAP : PILL_REST_X}
                    scale={menuOpen ? 1 : 0.3}
                    transition="bouncy"
                    delay={40}
                    style={{ pointerEvents: menuOpen ? 'auto' : 'none' }}
                  >
                    <button
                      type="button"
                      className="mock-vchat-btn mock-vchat-btn--liquid mock-vchat-agent"
                      aria-label="Confirm new chat"
                      tabIndex={menuOpen ? 0 : -1}
                      style={{
                        opacity: menuOpen ? 1 : 0,
                        // keeps .mock-vchat-btn's press-scale transition alongside the fade
                        transition: 'opacity 0.15s ease, transform 0.15s cubic-bezier(0.22, 1, 0.36, 1)',
                      }}
                      onClick={() => {
                        setMenuOpen(false)
                        onNewChat()
                      }}
                      suppressHydrationWarning
                    >
                      New chat
                    </button>
                  </Liquid.Item>
                </Liquid>
                <div className="mock-vchat-actions">
                  <button
                    type="button"
                    className={'mock-vchat-btn' + (recording ? ' recording' : '')}
                    aria-label="Hold to talk"
                    disabled={micDisabled}
                    onPointerDown={startRecording}
                    onPointerUp={stopRecording}
                    onPointerLeave={stopRecording}
                    suppressHydrationWarning
                  >
                    <span className="mk-ico mk-ico-mic" />
                  </button>
                  {/* Metal ring only when there's something to send: idle, Send
                      is as flat as its neighbours, and the ring reads as "armed".
                      Not just strength={0} -- the wrapper's own rim and dark fill
                      would still set this button apart from mic and plus. */}
                  {hasText ? (
                    <MetalFx variant="circle" preset="gold">
                      {SEND_BUTTON}
                    </MetalFx>
                  ) : (
                    SEND_BUTTON
                  )}
                </div>
              </div>
            </form>
          </VoiceBeam>
        </BorderBeam>
      </div>
    </div>
  )
}
