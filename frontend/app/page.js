'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import dynamic from 'next/dynamic'
import { ThinkingOrb } from 'thinking-orbs'
import VoiceBar from '../components/VoiceBar'
import { apiBase } from '../lib/api'

// WebGL/three -- keep off the server render entirely rather than rely on
// the library deferring canvas setup to an effect on its own.
const ImageGeneration = dynamic(() => import('img-fx').then((m) => m.ImageGeneration), { ssr: false })

// img-fx runs a continuous WebGL shader loop. Verified working (metal-fx,
// border-beam, liquid-gooey, thinking-orbs, voice-glow all render fine),
// but img-fx specifically hard-hung the browser used to test this build --
// `getContext('webgl2')` reported success while actual rendering never
// completed a frame, so there's no reliable way to feature-detect around
// it from here. Off by default; flip to true to try it on a real GPU.
const IMG_FX_ENABLED = false

// Every real tool Diya can call (diya.py's TOOLS/AVAILABLE_FUNCTIONS), mapped
// to the thinking-orbs state that actually matches what it does -- not a
// decorative pick, each pairing is the real verb: notes/web lookups search,
// weather reaches an external service, a reminder gets written down, and the
// two listing tools shape an existing list into view.
const TOOL_ORB = {
  search_notes: { state: 'searching', label: 'searched your notes' },
  web_search: { state: 'weaving', label: 'searched the web' },
  get_weather: { state: 'connecting', label: 'checked the weather' },
  add_reminder: { state: 'composing', label: 'saved a reminder' },
  list_reminders: { state: 'solving', label: 'checked your reminders' },
  list_files: { state: 'shaping', label: 'listed files' },
}

let cachedVoices = []
function loadVoices() {
  return new Promise((resolve) => {
    const voices = speechSynthesis.getVoices()
    if (voices.length) {
      resolve(voices)
      return
    }
    speechSynthesis.onvoiceschanged = () => resolve(speechSynthesis.getVoices())
  })
}

export default function ChatPage() {
  const [messages, setMessages] = useState([])
  // Speaking is opt-in: off until the user ticks "Speak", then remembered per browser.
  // (The saved choice is read in the mount effect, not here, so the server render
  // and the first client render agree -- same reason as the suppressHydrationWarning below.)
  const [speakOn, setSpeakOn] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  // Once revealed, freeze the shader/scheduler rather than let it render
  // forever -- see IMG_FX_ENABLED above for why this alone isn't enough
  // to make it safe by default.
  const [logoPaused, setLogoPaused] = useState(false)
  const threadIdRef = useRef(null)
  const logRef = useRef(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    setSpeakOn(localStorage.getItem('diya_speak') === '1')
    const urlThread = params.get('thread')
    const threadId = urlThread || localStorage.getItem('diya_thread_id')
    if (urlThread) localStorage.setItem('diya_thread_id', urlThread)
    threadIdRef.current = threadId

    // If opened from History, load and show that thread's real past messages.
    if (threadId) {
      fetch(`${apiBase()}/api/history/${threadId}`)
        .then((r) => r.json())
        .then((data) => {
          const loaded = data.messages
            .filter((m) => m.role === 'user' || m.role === 'assistant')
            .map((m) => ({ role: m.role, text: m.content }))
          setMessages(loaded)
        })
    }
  }, [])

  useEffect(() => {
    logRef.current?.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  function addMsg(role, text) {
    setMessages((prev) => [...prev, { role, text }])
  }

  // `force` is for an explicit click ("Test voice"), which should always speak.
  async function speak(text, { force = false } = {}) {
    if (!speakOn && !force) return
    if (!('speechSynthesis' in window)) {
      addMsg('system', 'No speechSynthesis in this browser')
      return
    }
    const utter = new SpeechSynthesisUtterance(text)

    // Safari's default pick is often the worst-sounding voice on the device --
    // explicitly prefer a higher-quality one if one is actually installed.
    if (!cachedVoices.length) cachedVoices = await loadVoices()
    const best =
      cachedVoices.find((v) => v.lang.startsWith('en') && /enhanced|premium/i.test(v.name)) ||
      cachedVoices.find((v) => v.lang === 'en-US') ||
      cachedVoices.find((v) => v.lang.startsWith('en'))
    if (best) utter.voice = best

    // The glow should track actual speech, not the network round-trip -- speak()
    // itself is fire-and-forget (the browser plays audio in the background), so
    // onstart/onend are the only real signal for how long Diya is actually talking.
    utter.onstart = () => setSpeaking(true)
    utter.onend = () => setSpeaking(false)
    utter.onerror = (e) => {
      setSpeaking(false)
      // cancel() (unticking Speak, or a newer reply cutting this one off) reports
      // "canceled"/"interrupted" -- a deliberate stop, not a voice failure.
      if (e.error === 'canceled' || e.error === 'interrupted') return
      addMsg('system', 'Voice error: ' + e.error)
    }
    // iOS Safari can silently drop speak() if it's called right after cancel() --
    // only cancel if something is actually mid-speech, and give it a beat either way.
    if (speechSynthesis.speaking) {
      speechSynthesis.cancel()
      setTimeout(() => speechSynthesis.speak(utter), 250)
    } else {
      speechSynthesis.speak(utter)
    }
  }

  async function handleSend(text) {
    addMsg('user', text)
    setThinking(true)
    try {
      const res = await fetch(`${apiBase()}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadIdRef.current, message: text }),
      })
      const data = await res.json()
      threadIdRef.current = data.thread_id
      localStorage.setItem('diya_thread_id', data.thread_id)
      const usedTools = [...new Set(data.tools_called || [])].filter((name) => TOOL_ORB[name])
      if (usedTools.length) {
        setMessages((prev) => [...prev, { role: 'tools', tools: usedTools }])
      }
      addMsg('assistant', data.answer)
      speak(data.answer)
    } finally {
      setThinking(false)
    }
  }

  function handleNewChat() {
    threadIdRef.current = null
    localStorage.removeItem('diya_thread_id')
    window.history.replaceState(null, '', '/')
    setMessages([])
  }

  return (
    <div className="app">
      <header>
        <div className="title">
          {/* img-fx's own pitch is a loader that becomes the image -- a nice
              fit for a brand mark that only needs to resolve once per load,
              rather than a feature Diya's actual chat surface has a use for
              (there's no image-message flow to attach it to). */}
          {IMG_FX_ENABLED ? (
            <ImageGeneration
              preset="pixels-organic"
              images={['/diya-flame.svg']}
              autoReveal
              theme="light"
              paused={logoPaused}
              onCycle={(phase) => {
                if (phase === 'visible') setLogoPaused(true)
              }}
            >
              <div className="brand-mark" />
            </ImageGeneration>
          ) : (
            <img src="/diya-flame.svg" alt="" className="brand-mark" />
          )}
          Diya
          {/* Ambient presence when nothing else is happening -- the one
              orb state with no specific task behind it, on purpose. */}
          {!thinking && !speaking && <ThinkingOrb state="breathing" size={20} theme="light" />}
        </div>
        <div className="controls">
          <Link className="icon-btn" href="/history" style={{ textDecoration: 'none' }}>
            History
          </Link>
          <button
            className="icon-btn"
            onClick={() => speak('This is a test of the voice output.', { force: true })}
            suppressHydrationWarning
          >
            Test voice
          </button>
          <label className="icon-btn">
            <input
              type="checkbox"
              checked={speakOn}
              onChange={(e) => {
                setSpeakOn(e.target.checked)
                localStorage.setItem('diya_speak', e.target.checked ? '1' : '0')
                if (!e.target.checked) window.speechSynthesis?.cancel()
              }}
              suppressHydrationWarning
            />{' '}
            Speak
          </label>
        </div>
      </header>
      <div id="log" ref={logRef}>
        {messages.map((m, i) => {
          if (m.role === 'tools') {
            return (
              <div key={i} className="msg system tool-recap">
                {m.tools.map((name) => (
                  <span key={name} className="tool-recap-item">
                    <ThinkingOrb state={TOOL_ORB[name].state} size={20} theme="light" />
                    {TOOL_ORB[name].label}
                  </span>
                ))}
              </div>
            )
          }
          return (
            <div key={i} className={'msg ' + m.role}>
              {m.text}
            </div>
          )
        })}
        {thinking && (
          <div className="msg assistant thinking-row">
            <ThinkingOrb state="working" size={20} theme="light" />
          </div>
        )}
      </div>
      <VoiceBar
        onSend={handleSend}
        onSystemMessage={(t) => addMsg('system', t)}
        onNewChat={handleNewChat}
        processing={thinking || speaking}
      />
    </div>
  )
}
