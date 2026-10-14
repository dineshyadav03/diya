'use client'

import { Fragment, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import Orb from '../components/Orb'
import VoiceBar from '../components/VoiceBar'
import { readChatStream } from '../lib/chat-stream.mjs'
import { describeLoadFailure, describeSendFailure, readFailure } from '../lib/api-failure.mjs'
import { describeActionFailure } from '../lib/api-failure.mjs'

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

// A tool of an MCP server the person approved (docs/MCP_DESIGN.md) is named mcp_<server>_<tool>: the chip says a program outside Diya was used, and which one.
function toolLabel(name) {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name]
  return typeof name === 'string' && name.startsWith('mcp_') ? `used a connected program (${name.split('_')[1] || 'MCP'})` : ''
}

// The questions Diya raises herself (docs/AUTO_MEMORY_DESIGN.md, D5 and unit A5), asked for when the chat opens and after each reply. They are built by code on the server
// (the words and the answers each question offers come from the API), shown as cards at the top of the chat, and answered with one press.
const QUESTIONS_AFTER_REPLY_MS = 20000
const NOTES_EVERY_MS = 60000

// What memory did with a message is looked up a few seconds after the reply, because memory reads the message once the reply is made (docs/AUTO_MEMORY_DESIGN.md,
// D7 and unit A4). The page asks every few seconds, for at most about two minutes, and says nothing if nothing was learned.
const LEARNED_EVERY_MS = 3000
const LEARNED_GIVE_UP_AFTER = 40

// The words of one thing memory did, and what undoing it is. The text of something left waiting is never in the line (the API does not send it): it may be private.
function describeLearned(item) {
  switch (item.kind) {
    case 'remembered':
      return `Noted: ${item.text}.`
    case 'replaced':
      return `Updated: ${item.text}. Was: ${item.old_text}.`
    case 'forgot':
      return `Forgot: ${item.text}.`
    case 'asked':
      return 'I wasn’t sure about something you said, so it is waiting for you on the Memory page.'
    case 'not_kept':
      return 'I did not keep something that looked like a secret.'
    default:
      return ''
  }
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
  // The reply as far as it has been written, while it is being written (docs/STREAMING_DESIGN.md); '' when none is coming. It becomes an ordinary message when it is whole.
  const [streamText, setStreamText] = useState('')
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
  // Which chat the page is showing: a look at what memory learned that finishes after the chat was changed must not be added to the new one.
  const chatEpochRef = useRef(0)
  // The questions Diya has for the person right now, and the answer being sent (a question id) or the one being typed (an edit).
  const [questions, setQuestions] = useState([])
  const [answering, setAnswering] = useState(null)
  const [editing, setEditing] = useState(null)
  const [questionProblem, setQuestionProblem] = useState('')
  // What Diya wrote first (docs/PROACTIVE_DESIGN.md) and the person has not looked at yet: shown as cards at the top, looked for when the page opens and once a minute while it is open.
  const [notes, setNotes] = useState([])
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
    loadQuestions()
    loadNotes()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') loadNotes()
    }, NOTES_EVERY_MS)
    return () => clearInterval(timer)
  }, [])

  // Fetch a saved chat's past messages. When that fails, say why and offer to try again: it used to
  // be swallowed, leaving an empty chat that looked as if the thread had nothing in it.
  function loadThread(threadId) {
    let status // stays undefined when the request never got an answer at all
    const seq = ++loadSeqRef.current
    chatEpochRef.current += 1
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
  }, [messages, streamText])

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

  // What Diya wrote first. A failed look shows nothing: the messages are also in the chat they were written in, which History lists.
  async function loadNotes() {
    try {
      const response = await fetch('/api/proactive')
      const body = response.ok ? await response.json() : null
      if (body && Array.isArray(body.messages)) setNotes(body.messages.filter((m) => Number.isInteger(m.id) && typeof m.text === 'string'))
    } catch {
      // nothing to show
    }
  }

  async function markNotesSeen(ids) {
    setNotes((shown) => shown.filter((m) => !ids.includes(m.id)))
    try {
      await fetch('/api/proactive/seen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) })
    } catch {
      // it will be offered again next time, which is the right way to fail
    }
  }

  async function openNote(note) {
    await markNotesSeen([note.id])
    window.location.assign(`/?thread=${note.thread_id}`) // her message is in that chat; a reply goes on from it
  }

  // Ask what Diya wants to ask, and say which she has now put in front of the person (an unanswered question left for a day counts as ignored).
  // A failed look shows nothing: this is a courtesy and the Memory page has everything.
  async function loadQuestions() {
    try {
      const response = await fetch('/api/questions')
      if (!response.ok) return
      const body = await response.json()
      if (!body || !Array.isArray(body.questions)) return
      setQuestions(body.questions)
      if (body.questions.length) {
        fetch('/api/questions/seen', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ids: body.questions.map((question) => question.id) }),
        }).catch(() => undefined)
      }
    } catch {
      // nothing to show
    }
  }

  async function answerQuestion(question, answer, text) {
    setAnswering(question.id)
    setQuestionProblem('')
    let response
    try {
      response = await fetch(`/api/questions/${question.id}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(text === undefined ? { answer } : { answer, text }),
      })
    } catch {
      setQuestionProblem(describeActionFailure())
      setAnswering(null)
      return
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      setQuestionProblem(describeActionFailure(response.status, detail?.detail))
      setAnswering(null)
      return
    }
    setEditing(null)
    setAnswering(null)
    await loadQuestions()
  }

  // Ask, a few seconds at a time, what memory made of one message, and put one quiet line under the reply when it made something. A failed look is
  // dropped without a word: this is a courtesy, and the Memory page has everything.
  async function watchLearned(messageId) {
    const epoch = chatEpochRef.current
    for (let attempt = 0; attempt < LEARNED_GIVE_UP_AFTER; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, LEARNED_EVERY_MS))
      if (epoch !== chatEpochRef.current) return
      let body
      try {
        const response = await fetch(`/api/memory/learned?message_id=${messageId}`)
        if (!response.ok) return
        body = await response.json()
      } catch {
        return
      }
      if (!body || !Array.isArray(body.items)) return
      if (body.reading) continue
      if (body.items.length && epoch === chatEpochRef.current) {
        setMessages((prev) => [...prev, { id: nextIdRef.current++, role: 'learned', items: body.items.map((item) => ({ ...item })) }])
      }
      return
    }
  }

  // Take one of those things back: a correction as one act, anything else the ordinary way (retire what was remembered, restore what was forgotten).
  async function undoLearned(messageKey, index) {
    const message = messages.find((m) => m.id === messageKey)
    const item = message?.items[index]
    if (!item || item.undone) return
    const mark = (changes) =>
      setMessages((prev) => prev.map((m) => (m.id === messageKey ? { ...m, items: m.items.map((it, i) => (i === index ? { ...it, ...changes } : it)) } : m)))
    mark({ busy: true, problem: '' })
    let response
    try {
      if (item.kind === 'replaced') response = await fetch(`/api/memory/${item.id}/undo-replace`, { method: 'POST' })
      else response = await fetch(`/api/memory/${item.id}/${item.kind === 'forgot' ? 'restore' : 'retire'}`, { method: 'POST' })
    } catch {
      mark({ busy: false, problem: describeActionFailure() })
      return
    }
    if (!response.ok) {
      const detail = await response.json().catch(() => null)
      mark({ busy: false, problem: describeActionFailure(response.status, detail?.detail) })
      return
    }
    mark({ busy: false, undone: true })
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
      let failure = {} // what the server said was wrong, if it said (its reason, and the chat it kept the message in)
      try {
        const request = {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ thread_id: threadIdRef.current, message: text }),
        }
        let res = await fetch('/api/chat/stream', request)
        if (res.status === 404) res = await fetch('/api/chat', request) // an API that has no streaming route yet (an older one still running): the whole reply at once
        status = res.status
        if (!res.ok) {
          failure = readFailure(await res.json().catch(() => null))
          throw new Error(`HTTP ${res.status}`)
        }
        if ((res.headers.get('content-type') || '').includes('ndjson')) {
          data = await readChatStream(res.body, {
            onStart: (event) => {
              // the chat the message is in is known from the first line, so a reply that fails half way still leaves the page knowing it
              if (Number.isInteger(event.thread_id)) {
                threadIdRef.current = event.thread_id
                localStorage.setItem('diya_thread_id', event.thread_id)
              }
            },
            onDelta: (piece) => setStreamText((shown) => shown + piece),
            onReset: () => setStreamText(''),
            onError: (event) => {
              status = event.status
              failure = readFailure({ detail: event.detail, thread_id: event.thread_id })
            },
          })
        } else {
          data = await res.json()
        }
        if (typeof data.answer !== 'string') throw new Error('not a reply')
      } catch {
        // The server keeps a message it could not answer, in a chat this page may not have heard of yet (the first message of
        // a new chat): remember that chat, so trying again goes to it and does not start a second one.
        if (failure.threadId !== undefined) {
          threadIdRef.current = failure.threadId
          localStorage.setItem('diya_thread_id', failure.threadId)
        }
        setStreamText('') // whatever had been written of a reply that did not finish is not shown as if it were one
        // the reason is stored on the message (a string, so still truthy) and shown as its error text
        setFailed(id, describeSendFailure(status, failure.detail))
        return
      }
      setFailed(id, false)
      if (data.thread_id != null) {
        threadIdRef.current = data.thread_id
        localStorage.setItem('diya_thread_id', data.thread_id)
      }
      const usedTools = [...new Set(data.tools_called || [])].filter((name) => toolLabel(name))
      if (usedTools.length) {
        setMessages((prev) => [...prev, { id: nextIdRef.current++, role: 'tools', tools: usedTools }])
      }
      setStreamText('')
      addMsg('assistant', data.answer)
      speak(data.answer)
      if (data.reading && Number.isInteger(data.message_id)) watchLearned(data.message_id)
      setTimeout(loadQuestions, QUESTIONS_AFTER_REPLY_MS) // what that message made may be a question; memory has had time to read it by then
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
    chatEpochRef.current += 1
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
        {notes.length > 0 && (
          <section className="question-cards note-cards" aria-label="Messages from Diya">
            {notes.map((note) => (
              <div key={note.id} className="question-card note-card">
                <p className="question-text">{note.text}</p>
                <div className="question-actions">
                  <button type="button" className="cta small" onClick={() => openNote(note)}>
                    Reply
                  </button>
                  <button type="button" className="quiet-btn" onClick={() => markNotesSeen([note.id])}>
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </section>
        )}
        {questions.length > 0 && (
          <section className="question-cards" aria-label="Questions from Diya">
            {questions.map((question) => (
              <div key={question.id} className="question-card">
                <p className="question-text">{question.text}</p>
                {editing && editing.id === question.id ? (
                  <form
                    className="question-edit"
                    onSubmit={(event) => {
                      event.preventDefault()
                      answerQuestion(question, 'edit', editing.text)
                    }}
                  >
                    <label className="memory-sr" htmlFor={`question-edit-${question.id}`}>
                      Reword it
                    </label>
                    <input
                      id={`question-edit-${question.id}`}
                      className="memory-input"
                      value={editing.text}
                      onChange={(event) => setEditing({ id: question.id, text: event.target.value })}
                      autoFocus
                    />
                    <button type="submit" className="cta small" disabled={answering === question.id || !editing.text.trim()}>
                      Save
                    </button>
                    <button type="button" className="quiet-btn" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <div className="question-actions">
                    {question.options.map((option) => (
                      <button
                        key={option.answer}
                        type="button"
                        className={option.answer === 'yes' ? 'cta small' : 'quiet-btn'}
                        disabled={answering === question.id}
                        onClick={() => (option.answer === 'edit' ? setEditing({ id: question.id, text: '' }) : answerQuestion(question, option.answer))}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {questionProblem && (
              <p className="learned-problem" role="alert">
                {questionProblem}
              </p>
            )}
          </section>
        )}
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
            <p>Type below, or tap the mic to talk.</p>
          </div>
        ))}
        {messages.map((m, i) => {
          if (m.role === 'tools') {
            return (
              <div key={m.id ?? 'h' + i} className="msg system tool-recap">
                {m.tools.map((name) => (
                  <span key={name} className="tool-recap-item">
                    {toolLabel(name)}
                  </span>
                ))}
              </div>
            )
          }
          if (m.role === 'learned') {
            return (
              <div key={m.id ?? 'h' + i} className="msg system learned-note" aria-label="What Diya learned from your message">
                {m.items.map((item, index) => (
                  <p key={`${item.kind}-${item.id}`} className="learned-line">
                    <span>{item.undone ? 'Undone.' : describeLearned(item)}</span>
                    {!item.undone && (item.kind === 'remembered' || item.kind === 'replaced' || item.kind === 'forgot') && (
                      <button type="button" className="learned-undo" disabled={item.busy} onClick={() => undoLearned(m.id, index)}>
                        Undo
                      </button>
                    )}
                    {!item.undone && item.kind === 'asked' && (
                      <Link href="/memory" className="learned-undo">
                        Open Memory
                      </Link>
                    )}
                    {item.problem && (
                      <span className="learned-problem" role="alert">
                        {item.problem}
                      </span>
                    )}
                  </p>
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
        {streamText && <div className="msg assistant streaming">{streamText}</div>}
        {((thinking && !streamText) || speaking) && (
          <div className="msg assistant thinking-row" role="status" aria-label={thinking ? 'Diya is working on it' : 'Diya is speaking'}>
            <Orb state={thinking ? 'thinking' : 'speaking'} />
            <span className="thinking-text">{thinking ? 'Thinking…' : 'Speaking…'}</span>
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
