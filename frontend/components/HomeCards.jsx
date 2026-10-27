'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeLoadFailure } from '../lib/api-failure.mjs'
import { useWeather } from './WeatherProvider'

// Home's column: the things Diya found for today, one card each (docs/HOME_DESIGN.md; the look of docs/mockups/home-mockup.html, option A, in the shape of Hark's Home:
// cards at the left, the chat beside them). Every card comes from the API already made by code (reminders, tasks, a question about memory, an action waiting for your yes,
// the next calendar event); no model wrote any of it, and React renders every word as text. A button calls a route that already exists (the card names it, and only a path that
// starts with /api/ is ever called). An action that changes another service is never done from here: it is answered in the chat, under the message where Diya asks.
// "Not now" hides a card for the rest of the day in this browser only. The column looks again once a minute while it is open.

const REFRESH_MS = 60_000
const HIDDEN_KEY = 'diya_home_hidden'
const WORDS = ['Nothing', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']

const ICONS = {
  bell: <path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7zM10 20a2 2 0 0 0 4 0" />,
  check: <path d="m5 12 5 5 9-10" />,
  idea: <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.4 1 2.5h6c0-1.1.3-1.8 1-2.5A6 6 0 0 0 12 3z" />,
  doc: <path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6" />,
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </>
  ),
  calendar: <path d="M5 4h14a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM8 2v4M16 2v4M3 10h18" />,
}

function Icon({ name }) {
  return (
    <svg className="home-ico" viewBox="0 0 24 24" aria-hidden="true">
      {ICONS[name] || ICONS.check}
    </svg>
  )
}

function dayKey() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function readHidden() {
  try {
    const all = JSON.parse(localStorage.getItem(HIDDEN_KEY) || '{}')
    const out = {}
    for (const [id, day] of Object.entries(all)) if (day === dayKey()) out[id] = true
    return out
  } catch {
    return {}
  }
}

function writeHidden(map) {
  try {
    const all = {}
    for (const id of Object.keys(map)) all[id] = dayKey()
    localStorage.setItem(HIDDEN_KEY, JSON.stringify(all))
  } catch {}
}

// The same sentence the API makes, from what is still on the screen after a card was done or hidden.
function headlineOf(needs, upcoming) {
  if (needs) return `${needs < WORDS.length ? WORDS[needs] : needs} thing${needs > 1 ? 's' : ''} need${needs > 1 ? '' : 's'} you today.`
  return upcoming ? 'Nothing needs you right now.' : 'All clear for today.'
}

function isHome(body) {
  return body && typeof body.headline === 'string' && typeof body.date === 'string' && Array.isArray(body.cards) && Array.isArray(body.problems) && body.panel && Array.isArray(body.panel.tiles)
}

// The weather where the person shared their place (components/WeatherProvider.jsx). Without one: a button to share it, as Hark's. It is also what the colour of the sky follows.
function WeatherPanel() {
  const { weather, problem, share, forget } = useWeather()
  if (weather === null) return null
  const ready = weather.known && !weather.problem
  return (
    <section className="home-panel" aria-label="Weather">
      <h2>
        <Icon name="sun" />
        Weather
      </h2>
      {ready ? (
        <>
          <div className="home-tiles">
            <div className="home-tile">
              <small>{weather.label}</small>
              <b>{weather.temp}&deg;C</b>
            </div>
            <div className="home-tile">
              <small>Feels like</small>
              <b>{weather.feels}&deg;</b>
            </div>
            <div className="home-tile">
              <small>Sunset</small>
              <b>{weather.sunset || '-'}</b>
            </div>
          </div>
          <p className="home-detail">Where you shared. The place stays on this laptop; only the weather service is told it. The background follows this weather.</p>
          <div className="home-acts">
            <button type="button" className="home-btn quiet" onClick={forget}>
              Stop using my location
            </button>
          </div>
        </>
      ) : weather.known ? (
        <p className="home-detail" role="status">
          {weather.problem}
        </p>
      ) : (
        <>
          <p className="home-detail">Share your location to see the weather here and to let the background follow it. The place stays on this laptop; only the weather service is told it.</p>
          <div className="home-acts">
            <button type="button" className="home-btn primary" onClick={share}>
              Share your location
            </button>
          </div>
          {problem && (
            <p className="home-detail home-problem" role="alert">
              {problem}
            </p>
          )}
        </>
      )}
    </section>
  )
}

export default function HomeCards() {
  const [data, setData] = useState(null) // null = loading, false = couldn't be loaded
  const [problem, setProblem] = useState('')
  const [fin, setFin] = useState({}) // card id -> { card, text }: done in this session, kept on screen until the page is left
  const [hiddenBefore, setHiddenBefore] = useState({}) // hidden earlier today: not shown at all
  const [hiddenNow, setHiddenNow] = useState({}) // hidden just now: shown as one line with Undo
  const [failed, setFailed] = useState({}) // card id -> why the last button did nothing
  const [busy, setBusy] = useState('')

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/home') // same-origin: app/api/home forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await response.json().catch(() => null) : null
      if (isHome(body)) {
        setData(body)
        setProblem('')
        if (Array.isArray(body.looking) && body.looking.length) setTimeout(() => load(false), 4000) // an account is still being read: look again soon
        return
      }
    } catch {
      status = undefined
    }
    if (first) {
      setProblem(describeLoadFailure(status))
      setData(false)
    }
  }, [])

  useEffect(() => {
    setHiddenBefore(readHidden())
    load(true)
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load(false)
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  // No fetch is ever made to an address built from what the API sent: a button's path is matched against the few routes Home may call, and the fetch is made to a fixed shape of address.
  function callRoute(post, body) {
    const init = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }
    const found = /^\/api\/(reminders|tasks|questions)\/(\d{1,18})\/(done|snooze|answer)$/.exec(post)
    if (found) return fetch(`/api/${found[1]}/${found[2]}/${found[3]}`, init)
    if (post === '/api/reminders') return fetch('/api/reminders', init)
    return Promise.resolve(null)
  }

  async function run(card, action) {
    if (typeof action.post !== 'string' || busy) return
    setBusy(card.id)
    try {
      const response = await callRoute(action.post, action.body)
      if (!response) {
        setFailed((f) => ({ ...f, [card.id]: 'That button is not one Home can press.' }))
      } else if (response.ok) {
        setFailed((f) => ({ ...f, [card.id]: '' }))
        setFin((f) => ({ ...f, [card.id]: { card, text: action.done } }))
        load(false)
      } else {
        setFailed((f) => ({ ...f, [card.id]: describeLoadFailure(response.status) }))
      }
    } catch {
      setFailed((f) => ({ ...f, [card.id]: describeLoadFailure(undefined) }))
    } finally {
      setBusy('')
    }
  }

  // "Draft a reply" and the like: the card asks Diya in the chat, as the person's own message, and Diya asks before anything is saved or sent. The words are made by code in the API from a
  // name with everything but letters, spaces and . ' - taken out: never from the subject or the text of a mail, which a stranger wrote.
  function askChat(card, action) {
    const text = typeof action.ask === 'string' ? action.ask.trim() : ''
    if (!text || busy) return
    if (window.matchMedia('(min-width: 900px)').matches) {
      const detail = { text, handled: false }
      window.dispatchEvent(new CustomEvent('diya-ask', { detail }))
      if (!detail.handled) {
        setFailed((f) => ({ ...f, [card.id]: 'Diya is busy with something else. Try again in a moment.' }))
        return
      }
    } else {
      window.location.assign('/?ask=' + encodeURIComponent(text))
    }
    setFailed((f) => ({ ...f, [card.id]: '' }))
    setFin((f) => ({ ...f, [card.id]: { card, text: action.done || 'Asked in the chat.' } }))
  }

  function hide(card) {
    setHiddenNow((h) => ({ ...h, [card.id]: true }))
    writeHidden({ ...hiddenBefore, ...hiddenNow, [card.id]: true })
  }

  function undo(card) {
    const next = { ...hiddenNow }
    delete next[card.id]
    setHiddenNow(next)
    writeHidden({ ...hiddenBefore, ...next })
  }

  const cards = data ? data.cards.filter((c) => !hiddenBefore[c.id]) : []
  const present = new Set(cards.map((c) => c.id))
  const gone = Object.entries(fin).filter(([id]) => !present.has(id)).map(([, f]) => f.card) // done, so the API no longer lists them
  const rows = [...cards, ...gone]
  const open = rows.filter((c) => !fin[c.id] && !hiddenNow[c.id])
  const needs = open.filter((c) => c.needs).length

  return (
    <aside className="home-col" aria-label="Home">
      {data === null ? (
        <div role="status" aria-label="Loading your day">
          <div className="thread-skeleton" />
          <div className="thread-skeleton" />
          <div className="thread-skeleton" />
        </div>
      ) : data === false ? (
        <div className="home-fail-box">
          <h1 className="home-head">Couldn&rsquo;t load Home</h1>
          <p className="home-sub">{problem}</p>
          <button type="button" className="home-btn primary" onClick={() => load(true)}>
            Try again
          </button>
        </div>
      ) : (
        <>
          <h1 className="home-head" role="status">
            {rows.length === 0 && Array.isArray(data.looking) && data.looking.length > 0 ? 'Looking at your day.' : headlineOf(needs, open.length - needs)}
          </h1>
          <p className="home-sub">
            {data.date}. {data.looked}
          </p>
          {Array.isArray(data.looking) && data.looking.length > 0 && (
            <p className="home-sub" role="status">
              Still looking at your {data.looking.join(' and ')}.
            </p>
          )}
          {data.problems.length > 0 && (
            <p className="home-sub" role="status">
              {data.problems.join(' ')}
            </p>
          )}
          {rows.length === 0 && Array.isArray(data.looking) && data.looking.length > 0 ? null : rows.length === 0 ? (
            <p className="home-empty">Nothing is waiting for you. Ask Diya anything in the chat.</p>
          ) : (
            <ul className="home-cards">
              {rows.map((card) => {
                if (fin[card.id]) {
                  return (
                    <li key={card.id} className="home-card fin">
                      <Icon name="check" />
                      <span>{fin[card.id].text}</span>
                    </li>
                  )
                }
                if (hiddenNow[card.id]) {
                  return (
                    <li key={card.id} className="home-card fin">
                      <Icon name="check" />
                      <span>Hidden until tomorrow.</span>
                      <button type="button" className="home-btn quiet" onClick={() => undo(card)}>
                        Undo
                      </button>
                    </li>
                  )
                }
                return (
                  <li key={card.id} className={'home-card' + (card.ask ? ' ask' : '')}>
                    <p className="home-line">
                      <span className="home-chip">{card.verb}</span>
                      <Icon name={card.icon} />
                      {card.title}
                    </p>
                    <p className="home-detail">
                      {card.source}
                      {card.detail ? `. ${card.detail}` : ''}
                    </p>
                    <div className="home-acts">
                      {card.actions.map((action, i) =>
                        action.href ? (
                          <Link key={action.label} className={'home-btn' + (i === 0 ? ' primary' : '')} href={action.href}>
                            {action.label}
                          </Link>
                        ) : (
                          <button key={action.label} type="button" className={'home-btn' + (i === 0 ? ' primary' : '')} disabled={busy === card.id} onClick={() => (action.ask ? askChat(card, action) : run(card, action))}>
                            {action.label}
                          </button>
                        )
                      )}
                      <button type="button" className="home-btn quiet" onClick={() => hide(card)}>
                        Not now
                      </button>
                    </div>
                    {failed[card.id] && (
                      <p className="home-detail home-problem" role="alert">
                        {failed[card.id]}
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          <WeatherPanel />
          <section className="home-panel" aria-label="Today at a glance">
            <h2>
              <Icon name="calendar" />
              Today
            </h2>
            <div className="home-tiles">
              {data.panel.tiles.map((tile) => (
                <div key={tile.label} className="home-tile">
                  <small>{tile.label}</small>
                  <b>{tile.value}</b>
                </div>
              ))}
            </div>
            <p className="home-detail">Counted from your reminders, tasks and calendar.</p>
          </section>
        </>
      )}
    </aside>
  )
}
