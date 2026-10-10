'use client'

import { Fragment, useEffect, useRef, useState } from 'react'
import VoiceBar from '../components/VoiceBar'
import { describeLoadFailure, describeSendFailure } from '../lib/api-failure.mjs'

// Every /api/... call below is same-origin: this app's own route handlers (app/api) forward it to
// the Python API and attach the access token on the server. The browser never holds the token.
// The navigation, and the counts on it, live in components/AppShell.jsx; this page is only the chat.

// Every real tool Diya can call (diya.py's TOOLS/AVAILABLE_FUNCTIONS), named by what it did, for the chips
// under a reply. A tool that is not listed here is not shown.
const TOOL_LABELS = {
  search_notes: 'searched your notes',
  web_search: 'searched the web',
  get_weather: 'checked the weather',
  add_reminder: 'saved a reminder',
  list_reminders: 'checked your reminders',
  add_task: 'added a task',
  list_tasks: 'checked your tasks',
  list_files: 'listed files',
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
  // True once we know whether there is a past thread to load, so the empty state
  // doesn't flash up for a moment before an existing conversation arrives.
  const [ready, setReady] = useState(false)
  // Why a saved chat couldn't be opened ('' when it loaded, or none was asked for). It replaces the
  // empty state: an empty chat would say the thread has nothing in it, which is not what happened.
  const [loadProblem, setLoadProblem] = useState('')
  // True while a saved chat's messages are being fetched (and not for a brand new chat, so nothing
  // is disabled for a moment on ordinary page loads).
  const [loadingChat, setLoadingChat] = useState(false)
  // Which load is the current one. A load that finishes after a newer one started, or after New
  // chat, is stale and must not touch the page: it would drop the old thread's messages into a chat
  // that has since been started over.
  const loadSeqRef = useRef(0)
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
    if (threadId) loadThread(threadId)
    else setReady(true)
  }, [])

  // Fetch a saved chat's past messages. When that fails, say why and offer to try again: it used to
  // be swallowed, leaving an empty chat that looked as if the thread had nothing in it.
  function loadThread(threadId) {
    let status // stays undefined when the request never got an answer at all
    const seq = ++loadSeqRef.current
    const stale = () => seq !== loadSeqRef.current
    setLoadProblem('')
    setLoadingChat(true)
    setReady(false)
    fetch(`/api/history/${threadId}`)
      .then((r) => {
        status = r.status
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data) => {
        if (stale()) return
        if (!Array.isArray(data.messages)) throw new Error('not a history')
        const loaded = data.messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({ role: m.role, text: m.content }))
        setMessages(loaded)
      })
      .catch(() => {
        if (!stale()) setLoadProblem(describeLoadFailure(status))
      })
      .finally(() => {
        if (stale()) return
        setLoadingChat(false)
        setReady(true)
      })
  }

  useEffect(() => {
    logRef.current?.lastElementChild?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages])

  // Messages get an id so a failed one can be found again (marked, retried) later.
  const nextIdRef = useRef(1)
  function addMsg(role, text) {
    const id = nextIdRef.current++
    setMessages((prev) => [...prev, { id, role, text }])
    return id
  }
  function setFailed(id, failed) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, failed } : m)))
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

  // Sends one message. If the server can't be reached -- or answers with an error or
  // something that isn't a reply -- the failure is shown on the message itself (outlined,
  // with the reason and a "Try again"). It used to be swallowed: the message sat there
  // looking delivered, and an HTTP error rendered an empty reply and saved the thread id
  // as "undefined".
  async function sendMessage(text, id) {
    setThinking(true)
    try {
      let data
      let status // stays undefined when the request never got an answer at all
      try {
        const res = await fetch('/api/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ thread_id: threadIdRef.current, message: text }),
        })
        status = res.status
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        data = await res.json()
        if (typeof data.answer !== 'string') throw new Error('not a reply')
      } catch {
        // the reason is stored on the message (a string, so still truthy) and shown as its error text
        setFailed(id, describeSendFailure(status))
        return
      }
      setFailed(id, false)
      if (data.thread_id != null) {
        threadIdRef.current = data.thread_id
        localStorage.setItem('diya_thread_id', data.thread_id)
      }
      const usedTools = [...new Set(data.tools_called || [])].filter((name) => TOOL_LABELS[name])
      if (usedTools.length) {
        setMessages((prev) => [...prev, { id: nextIdRef.current++, role: 'tools', tools: usedTools }])
      }
      addMsg('assistant', data.answer)
      speak(data.answer)
    } finally {
      setThinking(false)
    }
  }

  async function handleSend(text) {
    // The composer is off in these states (see `unavailable`); this is the backstop. A message sent
    // into a chat that isn't on screen would be added to a thread the person can't see.
    if (loadingChat || loadProblem) return
    const id = addMsg('user', text)
    await sendMessage(text, id)
  }

  function retrySend(id, text) {
    setFailed(id, false)
    sendMessage(text, id)
  }

  function handleNewChat() {
    threadIdRef.current = null
    localStorage.removeItem('diya_thread_id')
    window.history.replaceState(null, '', '/')
    loadSeqRef.current += 1 // whatever load is still in flight is for the chat being left
    setLoadProblem('') // starting over is the way out of a chat that wouldn't open
    setLoadingChat(false)
    setReady(true)
    setMessages([])
  }

  return (
    <div className="chat">
      <div className="chat-bar">
        <span className="chat-title">Chat</span>
        <div className="chat-tools">
          <button className="quiet-btn" onClick={() => speak('This is a test of the voice output.', { force: true })} suppressHydrationWarning>
            Test voice
          </button>
          <label className="quiet-btn">
            <input
              type="checkbox"
              checked={speakOn}
              onChange={(e) => {
                setSpeakOn(e.target.checked)
                localStorage.setItem('diya_speak', e.target.checked ? '1' : '0')
                if (!e.target.checked) window.speechSynthesis?.cancel()
              }}
              suppressHydrationWarning
            />
            Speak replies
          </label>
        </div>
      </div>
      <div id="log" ref={logRef}>
        {ready && messages.length === 0 && !thinking && (loadProblem ? (
          <div className="empty-state" role="alert">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h1>Couldn&rsquo;t load this chat</h1>
            <p>{loadProblem}</p>
            <button type="button" className="cta" onClick={() => loadThread(threadIdRef.current)}>
              Try again
            </button>
          </div>
        ) : (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h1>Ask Diya anything</h1>
            <p>Type below, or hold the mic to talk.</p>
          </div>
        ))}
        {messages.map((m, i) => {
          if (m.role === 'tools') {
            return (
              <div key={m.id ?? 'h' + i} className="msg system tool-recap">
                {m.tools.map((name) => (
                  <span key={name} className="tool-recap-item">
                    {TOOL_LABELS[name]}
                  </span>
                ))}
              </div>
            )
          }
          if (m.role === 'user' && m.failed) {
            return (
              <Fragment key={m.id ?? 'h' + i}>
                <div className="msg user failed">{m.text}</div>
                <div className="send-error" role="alert">
                  <span className="send-error-icon" aria-hidden="true">
                    !
                  </span>
                  <span>{m.failed}</span>
                  <button type="button" className="cta small" onClick={() => retrySend(m.id, m.text)}>
                    Try again
                  </button>
                </div>
              </Fragment>
            )
          }
          return (
            <div key={m.id ?? 'h' + i} className={'msg ' + m.role}>
              {m.text}
            </div>
          )
        })}
        {thinking && (
          <div className="msg assistant thinking-row" role="status" aria-label="Diya is working on it">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>
      <VoiceBar
        onSend={handleSend}
        onSystemMessage={(t) => addMsg('system', t)}
        onNewChat={handleNewChat}
        processing={thinking || speaking}
        unavailable={
          loadingChat
            ? 'Loading this chat…'
            : loadProblem
              ? 'This chat didn’t load. Try again, or start a new one.'
              : ''
        }
      />
    </div>
  )
}
