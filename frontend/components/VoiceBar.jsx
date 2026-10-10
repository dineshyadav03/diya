'use client'

import { useRef, useState } from 'react'
import { describeTranscribeFailure } from '../lib/api-failure.mjs'

// The message box (docs/UI_DESIGN.md, D3): a text field, Hold to talk, Send, and a New chat that asks first. It was a drawing with a WebGL
// ring, a voice-reactive glow and a liquid menu; it is a text box now, and what it shows of Diya working is words and one thin line.

// `unavailable` is why nothing can be sent right now ('' when something can): the page is still
// loading, or failed to load, the saved chat a message would continue. It is shown as the
// placeholder, and while it is set typing, Send and the microphone are all off -- a message sent
// into a chat the page hasn't shown would be added to a thread the person can't see. New chat (the
// menu) stays available: it is the way out.
export default function VoiceBar({ onSend, onSystemMessage, onNewChat, processing, unavailable = '' }) {
  const [value, setValue] = useState('')
  const [recording, setRecording] = useState(false)
  const [micDisabled, setMicDisabled] = useState(false)
  const [confirming, setConfirming] = useState(false) // New chat has been pressed once and is asking
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  // The same test submit() uses, so Send is filled exactly when it would send (and not while nothing can be sent).
  const hasText = value.trim().length > 0 && !unavailable

  function submit(text) {
    if (unavailable) return // leave what was typed where it is
    const trimmed = text.trim()
    if (!trimmed) return
    setValue('')
    onSend(trimmed)
  }

  async function startRecording() {
    if (unavailable) return
    try {
      const mic = await navigator.mediaDevices.getUserMedia({ audio: true })
      audioChunksRef.current = []
      const mediaRecorder = new MediaRecorder(mic)
      mediaRecorder.ondataavailable = (e) => audioChunksRef.current.push(e.data)
      mediaRecorder.onstop = () => sendRecording(mediaRecorder)
      mediaRecorder.start()
      mediaRecorderRef.current = mediaRecorder
      setRecording(true)
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
    let status // stays undefined when the request never got an answer at all
    try {
      // same-origin: app/api/transcribe forwards the upload, with the access token, from the server
      const res = await fetch('/api/transcribe', { method: 'POST', body: form })
      status = res.status
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      data = await res.json()
    } catch {
      // It didn't work. This used to throw here, leaving the mic disabled on "Transcribing..." for
      // good; give it back and say what happened -- no answer, a refused access token and an
      // error are different things to fix.
      setMicDisabled(false)
      onSystemMessage(describeTranscribeFailure(status))
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
    <div className="composer-dock">
      <form
        className="composer"
        aria-label="Message Diya"
        data-busy={processing ? 'true' : 'false'}
        onSubmit={(e) => {
          e.preventDefault()
          submit(value)
        }}
      >
        <div className="composer-progress" aria-hidden="true" />
        <input
          className="composer-input"
          type="text"
          placeholder={unavailable || 'Message Diya...'}
          disabled={!!unavailable}
          aria-label="Message"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          suppressHydrationWarning
        />
        {/* Two real phases the old build gave zero feedback for -- capturing your voice, then Whisper turning it into text. */}
        {(recording || micDisabled) && (
          <div className="mic-status" role="status">
            {recording ? 'Listening...' : 'Transcribing...'}
          </div>
        )}
        <div className="composer-row">
          {/* New chat wipes the thread, so it asks first instead of firing on a single press. */}
          {confirming ? (
            <span className="composer-confirm" role="group" aria-label="Start a new chat?">
              Start a new chat?
              <button
                type="button"
                className="composer-btn"
                aria-label="Confirm new chat"
                onClick={() => {
                  setConfirming(false)
                  onNewChat()
                }}
                suppressHydrationWarning
              >
                New chat
              </button>
              <button type="button" className="composer-btn composer-btn--quiet" onClick={() => setConfirming(false)} suppressHydrationWarning>
                Keep this one
              </button>
            </span>
          ) : (
            <button type="button" className="composer-btn composer-btn--quiet" aria-label="New chat" onClick={() => setConfirming(true)} suppressHydrationWarning>
              + New chat
            </button>
          )}
          <div className="composer-actions">
            <button
              type="button"
              className={'composer-btn' + (recording ? ' recording' : '')}
              aria-label="Hold to talk"
              disabled={micDisabled || !!unavailable}
              onPointerDown={startRecording}
              onPointerUp={stopRecording}
              onPointerLeave={stopRecording}
              suppressHydrationWarning
            >
              <span className="mk-ico mk-ico-mic" />
            </button>
            <button
              type="submit"
              className={'composer-btn composer-btn--send'}
              aria-label="Send"
              disabled={!hasText}
              suppressHydrationWarning
            >
              <span className="mk-ico mk-ico-arrow" />
            </button>
          </div>
        </div>
      </form>
    </div>
  )
}
