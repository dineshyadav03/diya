'use client'

import { useEffect, useRef, useState } from 'react'
import Orb from './Orb'
import { describeTranscribeFailure } from '../lib/api-failure.mjs'
import { SILENT_BELOW, deviceOf, describeMicrophoneFailure, markSilent, markWorking, openMicrophone, watchLevel } from '../lib/microphone.mjs'

const MIN_RECORDING_MS = 600 // a recording shorter than this was a double tap, not something said
const MAX_RECORDING_MS = 60_000 // a forgotten recording stops and is sent by itself after this

// The message box (docs/UI_DESIGN.md, D3): a text field, Tap to talk (tap to start, tap again to send; docs/VOICE_DESIGN.md) and Send. Diya has one chat now (docs/ONE_CHAT_DESIGN.md), so nothing in the box starts another. It was a drawing with a WebGL
// ring, a voice-reactive glow and a liquid menu; it is a text box now, and what it shows of Diya working is words and one thin line.

// `unavailable` is why nothing can be sent right now ('' when something can): the page is still
// loading, or failed to load, the saved chat a message would continue. It is shown as the
// placeholder, and while it is set typing, Send and the microphone are all off -- a message sent
// into a chat the page hasn't shown would be added to a thread the person can't see.
export default function VoiceBar({ onSend, onSystemMessage, processing, unavailable = '' }) {
  const [value, setValue] = useState('')
  const [recording, setRecording] = useState(false)
  const [starting, setStarting] = useState(false) // the browser is still opening the microphone (it may be asking permission)
  const [micName, setMicName] = useState('') // which microphone is listening, so a wrong one is noticed at once
  const [micDisabled, setMicDisabled] = useState(false)
  const mediaRecorderRef = useRef(null)
  const audioChunksRef = useRef([])
  const startedAtRef = useRef(0)
  const peakRef = useRef(0) // the loudest the microphone got during this recording (0 to 1)
  const discardRef = useRef(false) // Cancel was pressed: what was recorded is thrown away
  const timerRef = useRef(null)
  const stopMeterRef = useRef(null)
  const [level, setLevel] = useState(0) // how loud the microphone is, for the listening orb
  // The same test submit() uses, so Send is filled exactly when it would send (and not while nothing can be sent).
  const hasText = value.trim().length > 0 && !unavailable

  function submit(text) {
    if (unavailable) return // leave what was typed where it is
    const trimmed = text.trim()
    if (!trimmed) return
    setValue('')
    onSend(trimmed)
  }

  // Tap once to start listening, tap again to stop and send. (It was hold-to-talk; holding a button while speaking is not how anyone expects a microphone to work.)
  async function startRecording() {
    if (unavailable || recording || starting) return
    setStarting(true)
    let mic
    try {
      mic = await openMicrophone() // the default microphone, or, when that will not start or was heard to be silent, each other real one in turn
    } catch (err) {
      setStarting(false)
      onSystemMessage(describeMicrophoneFailure(err))
      return
    }
    setStarting(false)
    audioChunksRef.current = []
    peakRef.current = 0
    discardRef.current = false
    const mediaRecorder = new MediaRecorder(mic)
    mediaRecorder.ondataavailable = (e) => audioChunksRef.current.push(e.data)
    mediaRecorder.onstop = () => sendRecording(mediaRecorder, mic)
    mediaRecorder.start()
    mediaRecorderRef.current = mediaRecorder
    startedAtRef.current = Date.now()
    stopMeterRef.current = watchLevel(mic, (value) => {
      peakRef.current = Math.max(peakRef.current, value)
      setLevel(value)
    })
    timerRef.current = setTimeout(() => stopRecording(), MAX_RECORDING_MS)
    setMicName(deviceOf(mic).label)
    setRecording(true)
  }

  function stopRecording(discard = false) {
    discardRef.current = discard === true
    clearTimeout(timerRef.current)
    const mediaRecorder = mediaRecorderRef.current
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop()
      mediaRecorder.stream.getTracks().forEach((t) => t.stop())
    }
    stopMeterRef.current?.()
    stopMeterRef.current = null
    setRecording(false)
  }

  // Leaving the page while it listens must not leave the microphone on.
  useEffect(
    () => () => {
      discardRef.current = true
      clearTimeout(timerRef.current)
      const mediaRecorder = mediaRecorderRef.current
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop()
        mediaRecorder.stream.getTracks().forEach((t) => t.stop())
      }
      stopMeterRef.current?.()
    },
    [],
  )

  async function sendRecording(mediaRecorder, mic) {
    if (discardRef.current) return
    const mimeType = mediaRecorder.mimeType || 'audio/webm'
    const blob = new Blob(audioChunksRef.current, { type: mimeType })

    if (Date.now() - startedAtRef.current < MIN_RECORDING_MS) {
      onSystemMessage('That was too short to hear. Tap the mic, say what you want, then tap it again.')
      return
    }
    if (peakRef.current < SILENT_BELOW) {
      // Not even a murmur reached it: speaking into a microphone that is not the one listening (a virtual cable, a muted or disconnected device) is the usual reason, and Whisper
      // would make words out of the silence. Nothing is sent; the next tap uses a different microphone.
      markSilent(mic)
      const name = deviceOf(mic).label
      onSystemMessage(`Nothing was heard${name ? ` from "${name}"` : ''}. Tap the mic and try again: I will use a different microphone this time.`)
      return
    }
    markWorking(mic)

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
      onSystemMessage("I couldn't hear any words in that. Tap the mic, wait until it says Listening, then speak.")
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
        {(starting || recording || micDisabled) && (
          <div className="mic-status" role="status">
            <Orb state={recording ? 'listening' : 'thinking'} level={recording ? level : 0} size={22} />
            {recording ? (
              <>
                <span>Listening{micName ? ` (${micName})` : ''}. Tap the mic again when you are done.</span>
                <button type="button" className="composer-btn composer-btn--quiet" onClick={() => stopRecording(true)} suppressHydrationWarning>
                  Cancel
                </button>
              </>
            ) : starting ? (
              'Opening the microphone...'
            ) : (
              'Transcribing...'
            )}
          </div>
        )}
        <div className="composer-row">
          <div className="composer-actions">
            <button
              type="button"
              className={'composer-btn' + (recording ? ' recording' : '')}
              aria-label={recording ? 'Tap to stop and send' : 'Tap to talk'}
              aria-pressed={recording}
              disabled={micDisabled || starting || !!unavailable}
              onClick={() => (recording ? stopRecording() : startRecording())}
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
