'use client'

import { Fragment, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import Orb from '../components/Orb'
import VoiceBar from '../components/VoiceBar'
import { readChatStream } from '../lib/chat-stream.mjs'
import { dayBreaks } from '../lib/day-labels.mjs'
import { inlineParts } from '../lib/markdown-lite.mjs'
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
  study_repo: 'studied a repository',
  read_mail: 'looked through your mail',
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

// The exchanges of one category: each of the person's messages that is in it, and everything after it up to the next message of theirs (the reply, the tools it used, what memory learned).
function inCategory(messages, tags, name) {
  const kept = []
  let inside = false
  for (const m of messages) {
    if (m.role === 'user') inside = Number.isInteger(m.serverId) && tags[m.serverId] === name
    if (inside) kept.push(m)
  }
  return kept
}

// Why a reply was not helpful: the same list, in the same words, as diya_feedback.CATEGORIES (a test keeps them equal).
const FEEDBACK_REASONS = {
  wrong: 'The answer was wrong',
  'made-up': 'It made something up',
  'not-what-i-asked': 'It did not do what I asked',
  slow: 'It was too slow',
  privacy: 'It showed or asked for something private or unsafe',
  other: 'Something else',
}

// A reply drawn with the bold, italic and code the model marked (lib/markdown-lite.mjs): each part is text inside its own element, so a reply can never become markup.
function Inline({ text }) {
  return inlineParts(text).map((part, i) => {
    if (part.kind === 'bold') return <strong key={i}>{part.text}</strong>
    if (part.kind === 'italic') return <em key={i}>{part.text}</em>
    if (part.kind === 'code') return <code key={i}>{part.text}</code>
    return part.text
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
  // True when the page is showing an EARLIER chat (opened from History): it can be read, not written in. Diya has one chat; this is where it was before.
  const [earlierChat, setEarlierChat] = useState(false)
  // True when the one chat has older messages than the page was given (it keeps the newest few hundred); History has the rest.
  const [olderLeft, setOlderLeft] = useState(false)
  // Diya sorts each message of the person's into a category after replying (docs/ONE_CHAT_DESIGN.md): the list of categories, where each message is (message id -> name), the category the chat is
  // being looked at by (null = all of it), and why a change of category did not happen.
  const [categories, setCategories] = useState([])
  const [ratings, setRatings] = useState({}) // the person's rating of Diya's reply to each of their messages: { message id: { rating, category, note, version } }
  const [tags, setTags] = useState({})
  const [lookingAt, setLookingAt] = useState(null)
  const [tagProblem, setTagProblem] = useState('')
  const [suggestions, setSuggestions] = useState(0) // how many new categories Diya has suggested and the person has not answered
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
    // Diya has ONE chat (docs/ONE_CHAT_DESIGN.md): the server knows which. An earlier chat is opened only by a link that names it (History), and is read, not written in.
    const urlThread = /^[0-9]{1,18}$/.test(params.get('thread') || '') ? params.get('thread') : null
    threadIdRef.current = urlThread
    loadThread(urlThread || 'main')
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
        if (Number.isInteger(data.thread_id)) threadIdRef.current = data.thread_id
        setEarlierChat(data.is_main === false) // an API that does not say (an older one) is taken to have given the chat that was asked for
        setOlderLeft(data.more_before === true)
        const loaded = data.messages
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({ role: m.role, text: m.content, serverId: Number.isInteger(m.id) ? m.id : undefined, at: typeof m.at === 'string' ? m.at : undefined }))
        const found = {}
        for (const m of data.messages) if (m.role === 'user' && Number.isInteger(m.id) && typeof m.category === 'string') found[m.id] = m.category
        setTags(found)
        loadRatings(data.messages.filter((m) => m.role === 'user' && Number.isInteger(m.id)).map((m) => m.id))
        setLookingAt(null)
        setMessages(loaded)
        loadCategories(data.is_main !== false) // an earlier chat's tags came with it; only the one chat's are looked for again
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
    setMessages((prev) => [...prev, { id, role, text, at: new Date().toISOString() }])
    return id
  }
  function setFailed(id, failed) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, failed } : m)))
  }

  // The categories, and where the newest messages are. A failed look shows nothing: the tags are a courtesy and the chat does not need them.
  async function loadCategories(withTags = true) {
    try {
      const response = await fetch('/api/categories')
      const body = response.ok ? await response.json() : null
      if (body && Array.isArray(body.categories)) {
        setCategories(body.categories.filter((c) => typeof c.name === 'string'))
        if (withTags && body.tags && typeof body.tags === 'object') setTags(body.tags)
        setSuggestions(Array.isArray(body.suggestions) ? body.suggestions.length : 0)
      }
    } catch {
      // nothing to show
    }
  }

  // What the person thinks of Diya's reply to one of their messages (docs/FEEDBACK_DESIGN.md). One place sends it; a change made from another page since they looked comes back as 409 with the item as it now is.
  function postFeedback(body) {
    return fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  }

  async function loadRatings(ids) {
    if (!ids.length) {
      setRatings({})
      return
    }
    try {
      const response = await postFeedback({ action: 'list', message_ids: ids })
      const body = response.ok ? await response.json() : null
      if (body && body.items && typeof body.items === 'object') {
        const found = {}
        for (const [id, item] of Object.entries(body.items)) found[Number(id)] = item
        setRatings(found)
      }
    } catch {
      // the buttons simply start empty: nothing depends on this
    }
  }

  async function rate(serverId, rating, category) {
    const current = ratings[serverId]
    setTagProblem('')
    try {
      if (current && current.rating === rating && category === undefined) {
        const response = await postFeedback({ action: 'delete', message_id: serverId, version: current.version }) // pressing the same one again takes it back
        if (response.ok) {
          setRatings((shown) => {
            const { [serverId]: _gone, ...rest } = shown
            return rest
          })
          return
        }
        return await refused(response, serverId)
      }
      const chosen = category === undefined ? (rating === 'negative' && current ? current.category || null : null) : category || null
      const response = await postFeedback({ action: 'put', message_id: serverId, rating, category: chosen, note: current ? current.note : null, version: current ? current.version : null })
      if (response.ok) {
        const body = await response.json()
        setRatings((shown) => ({ ...shown, [serverId]: body.item }))
        return
      }
      return await refused(response, serverId)
    } catch {
      setTagProblem('Couldn’t save that. Nothing was changed.')
    }
  }

  async function refused(response, serverId) {
    if (response.status === 409) {
      const body = await response.json().catch(() => null)
      setRatings((shown) => {
        const { [serverId]: _old, ...rest } = shown
        return body && body.current ? { ...rest, [serverId]: body.current } : rest
      })
      setTagProblem('That was changed from another page, so it is shown as it is now.')
      return
    }
    setTagProblem('Couldn’t save that. Nothing was changed.')
  }

  // The person says a message belongs elsewhere: shown at once, put back if it could not be kept.
  async function moveMessage(serverId, name) {
    const before = tags[serverId]
    setTagProblem('')
    setTags((shown) => ({ ...shown, [serverId]: name }))
    try {
      const response = await fetch('/api/categories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'assign', message_id: serverId, category: name }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
    } catch {
      setTags((shown) => ({ ...shown, [serverId]: before }))
      setTagProblem('Couldn’t change that category. Nothing was changed.')
    }
  }

  // "Forget this" on one of the person's messages (docs/FORGET_DESIGN.md): the message and Diya's reply are deleted, and with them what Diya learned from it. It asks first with the real numbers (a dry
  // run changes nothing), because nothing can bring them back.
  async function forgetMessage(serverId) {
    setTagProblem('')
    try {
      const preview = await fetch(`/api/messages/${serverId}/forget`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ also_learned: true, dry_run: true }) })
      const info = preview.ok ? await preview.json() : null
      if (!info) throw new Error(`HTTP ${preview.status}`)
      const learned = info.facts > 0 ? ` Diya will also forget the ${info.facts === 1 ? 'thing' : `${info.facts} things`} she learned from it.` : ''
      const kept = Object.values(info.kept_and_unlinked || {}).some((n) => n > 0) ? ' A task, reminder or approved action made from it stays.' : ''
      if (!window.confirm(`Delete this message${info.replies > 0 ? ' and Diya’s reply' : ''} for good?${learned}${kept} This cannot be undone. Backups made earlier may still hold the words until they are replaced.`)) return
      const done = await fetch(`/api/messages/${serverId}/forget`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ also_learned: true, dry_run: false }) })
      const report = done.ok ? await done.json() : null
      if (!report || !Array.isArray(report.message_ids)) throw new Error(`HTTP ${done.status}`)
      setMessages((prev) => prev.filter((m) => !report.message_ids.includes(m.serverId)))
      setTags((shown) => {
        const { [serverId]: _gone, ...rest } = shown
        return rest
      })
    } catch {
      setTagProblem('Couldn’t delete that. Nothing was changed.')
    }
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
        }
        setStreamText('') // whatever had been written of a reply that did not finish is not shown as if it were one
        // the reason is stored on the message (a string, so still truthy) and shown as its error text
        setFailed(id, describeSendFailure(status, failure.detail))
        return
      }
      setFailed(id, false)
      if (Number.isInteger(data.message_id)) {
        setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, serverId: data.message_id } : m)))
        setTimeout(loadCategories, 4000) // Diya sorts the message after replying; look for where it went, and again for a model that was busy
        setTimeout(loadCategories, 15000)
      }
      if (data.thread_id != null) {
        threadIdRef.current = data.thread_id
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
    if (loadingChat || loadProblem || earlierChat) return
    setLookingAt(null) // a new message is shown among everything, not hidden by the category being looked at
    const id = addMsg('user', text)
    await sendMessage(text, id)
  }

  function retrySend(id, text) {
    setFailed(id, false)
    sendMessage(text, id)
  }

  const shownMessages = lookingAt ? inCategory(messages, tags, lookingAt) : messages
  const breaks = dayBreaks(shownMessages) // the label of the day each message starts, or null: the chat is shown under the person's own days
  const counts = {}
  for (const name of Object.values(tags)) counts[name] = (counts[name] || 0) + 1
  const chips = categories.filter((c) => counts[c.name]).map((c) => [c.name, counts[c.name]])

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
      {chips.length > 0 && !earlierChat && (
        <div className="category-chips" role="group" aria-label="Look at the chat by category">
          <button type="button" className="chip" aria-pressed={lookingAt === null} onClick={() => setLookingAt(null)}>
            All
          </button>
          {chips.map(([name, count]) => (
            <button key={name} type="button" className="chip" aria-pressed={lookingAt === name} onClick={() => setLookingAt(name)}>
              {name} <span className="chip-count">{count}</span>
            </button>
          ))}
          {tagProblem && (
            <span className="learned-problem" role="alert">
              {tagProblem}
            </span>
          )}
          <Link href="/categories" className="chip chip-link">
            {suggestions > 0 ? 'A new category is suggested' : 'Edit categories'}
          </Link>
        </div>
      )}
      {earlierChat && (
        <div className="earlier-chat-bar" role="status">
          <span>This is an earlier chat. You can read it here; Diya&rsquo;s one chat is where you write.</span>
          <a className="cta small" href="/">
            Back to your chat
          </a>
        </div>
      )}
      <div id="log" ref={logRef}>
        {olderLeft && !earlierChat && (
          <p className="memory-dim older-left">Older messages are kept in <Link href="/history">History</Link>.</p>
        )}
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
            <button type="button" className="cta" onClick={() => loadThread(threadIdRef.current || 'main')}>
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
        {shownMessages.map((m, i) => {
          const dayLabel = breaks[i]
          const withDay = (node) =>
            dayLabel ? (
              <Fragment key={'day' + (m.id ?? 'h' + i)}>
                <div className="day-sep" role="separator" aria-label={dayLabel}>
                  <span>{dayLabel}</span>
                </div>
                {node}
              </Fragment>
            ) : (
              node
            )
          if (m.role === 'tools') {
            return withDay(
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
            return withDay(
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
            return withDay(
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
          if (m.role === 'user' && Number.isInteger(m.serverId)) {
            return withDay(
              <Fragment key={m.id ?? 'h' + i}>
                <div className="msg user">{m.text}</div>
                <div className="msg-tag-row">
                  {tags[m.serverId] && categories.length > 0 && (
                    <select className="msg-tag" aria-label="Category of this message" title="Change this message’s category" value={tags[m.serverId]} onChange={(e) => moveMessage(m.serverId, e.target.value)}>
                      {categories.some((c) => c.name === tags[m.serverId]) ? null : <option value={tags[m.serverId]}>{tags[m.serverId]}</option>}
                      {categories.map((c) => (
                        <option key={c.id} value={c.name}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  )}
                  <span className="msg-rate" role="group" aria-label="How was Diya’s reply to this message?">
                    <button type="button" className="msg-rate-btn" aria-pressed={!!ratings[m.serverId] && ratings[m.serverId].rating === 'positive'} onClick={() => rate(m.serverId, 'positive')}>
                      Helpful
                    </button>
                    <button type="button" className="msg-rate-btn" aria-pressed={!!ratings[m.serverId] && ratings[m.serverId].rating === 'negative'} onClick={() => rate(m.serverId, 'negative')}>
                      Not helpful
                    </button>
                    {ratings[m.serverId] && ratings[m.serverId].rating === 'negative' && (
                      <select className="msg-tag" aria-label="What was wrong with the reply" value={ratings[m.serverId].category || ''} onChange={(e) => rate(m.serverId, 'negative', e.target.value)}>
                        <option value="">What was wrong?</option>
                        {Object.entries(FEEDBACK_REASONS).map(([id, words]) => (
                          <option key={id} value={id}>
                            {words}
                          </option>
                        ))}
                      </select>
                    )}
                  </span>
                  <button type="button" className="msg-forget" title="Delete this message and Diya’s reply for good" aria-label="Forget this message for good" disabled={thinking} onClick={() => forgetMessage(m.serverId)}>
                    Forget this
                  </button>
                </div>
              </Fragment>
            )
          }
          return withDay(
            <div key={m.id ?? 'h' + i} className={'msg ' + m.role}>
              {m.role === 'assistant' ? <Inline text={m.text} /> : m.text}
            </div>
          )
        })}
        {streamText && (
          <div className="msg assistant streaming">
            <Inline text={streamText} />
          </div>
        )}
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
        processing={thinking || speaking}
        unavailable={
          loadingChat
            ? 'Loading this chat…'
            : loadProblem
              ? 'This chat didn’t load. Try again.'
              : earlierChat
                ? 'This is an earlier chat. Go back to your chat to write.'
                : ''
        }
      />
    </div>
  )
}
