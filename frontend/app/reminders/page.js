'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// What Diya will tell you, and when (docs/PROACTIVITY_DESIGN.md, unit P3). Everything shown here comes from the API
// already made safe to show (control and direction-changing characters arrive as visible escapes), and React
// renders it as text, never as markup. The page looks again once a minute while it is open, so a reminder that
// comes due appears without a reload; nothing pushes to a closed tab (that is the desktop notifier's job).

const REFRESH_MS = 60_000

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

const SECTIONS = [
  { state: 'due', title: 'Due now', empty: 'Nothing is due.' },
  { state: 'upcoming', title: 'Coming up', empty: 'Nothing is coming up.' },
  { state: 'no_time', title: 'No time set', empty: 'Every reminder has a time.' },
]

export default function RemindersPage() {
  // null = loading, false = couldn't be loaded, otherwise { reminders, counts }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // '', 'add', or a reminder id
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('') // the result of something the person just did, and only that
  const [refreshProblem, setRefreshProblem] = useState('') // the once-a-minute look failed; kept apart so it never stands in for, or wipes, an action's result
  const [text, setText] = useState('')
  const [when, setWhen] = useState('')

  const load = useCallback(async (first, quiet = false) => {
    let status
    try {
      const response = await fetch('/api/reminders') // same-origin: app/api/reminders forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (body && Array.isArray(body.reminders) && body.counts) {
        setData(body)
        setProblem('')
        if (quiet) setRefreshProblem('')
        return true
      }
    } catch {
      status = undefined
    }
    if (first) {
      setProblem(describeLoadFailure(status))
      setData(false)
    } else if (quiet) {
      setRefreshProblem(describeLoadFailure(status))
    } else {
      setError(describeLoadFailure(status))
    }
    return false
  }, [])

  useEffect(() => {
    load(true)
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load(false, true)
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  // Run a request the person asked for. On success say what happened (and use the list the API sent back); on a
  // refusal say why, in the API's own words when it gave them, and that nothing was changed.
  async function settle(request, id, describe) {
    setBusy(id)
    setError('')
    setNotice('')
    let response
    try {
      response = await request()
    } catch {
      setError(describeActionFailure())
      setBusy('')
      return false
    }
    const body = await readJson(response)
    if (!response.ok || !body) {
      setError(describeActionFailure(response.ok ? undefined : response.status, body?.detail))
      if (response.ok) await load(false) // it did something we could not read: show what it did
      setBusy('')
      return false
    }
    setNotice(describe(body))
    if (Array.isArray(body.reminders) && body.counts) setData(body)
    else await load(false)
    setBusy('')
    return true
  }

  function addReminder(event) {
    event.preventDefault()
    settle(
      () =>
        fetch('/api/reminders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, when }),
        }),
      'add',
      ({ reminder, assumed }) => {
        const at = reminder.due_text ? `Saved for ${reminder.due_text}.` : 'Saved, with no time, so it will not fire.'
        return assumed.length ? `${at} (${assumed.join('; ')})` : at
      },
    ).then((ok) => {
      if (ok) {
        setText('')
        setWhen('')
      }
    })
  }

  const markDone = (reminder) =>
    settle(() => fetch(`/api/reminders/${reminder.id}/done`, { method: 'POST' }), String(reminder.id), () => 'Marked done.')

  const reminders = data ? data.reminders : []

  return (
    <div className="app">
      <header>
        <div className="title">
          <img src="/diya-flame.svg" alt="" className="brand-mark" />
          Diya
        </div>
        <div className="controls">
          <Link className="icon-btn" href="/history">
            History
          </Link>
          <Link className="icon-btn" href="/memory">
            Memory
          </Link>
          <Link className="icon-btn" href="/connections">
            Connections
          </Link>
          <Link className="icon-btn" href="/">
            &larr; Back to chat
          </Link>
        </div>
      </header>
      <main className="history-page memory-page reminders-page">
        <div className="history-inner">
          <h1>Reminders</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your reminders">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your reminders</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-lede">
                What Diya will tell you, and when. Say &ldquo;remind me to&hellip;&rdquo; in the chat, or add one here. A reminder
                appears under &ldquo;Due now&rdquo; when its time comes.
              </p>
              <form className="memory-add reminder-add" onSubmit={addReminder}>
                <label className="memory-sr" htmlFor="reminder-text">
                  What to be reminded of
                </label>
                <input
                  id="reminder-text"
                  className="memory-input"
                  placeholder="Remind me to…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <label className="memory-sr" htmlFor="reminder-when">
                  When (for example Friday 5pm, or in 2 hours)
                </label>
                <input
                  id="reminder-when"
                  className="memory-input reminder-when"
                  placeholder="When, e.g. Friday 5pm"
                  value={when}
                  onChange={(e) => setWhen(e.target.value)}
                />
                <button type="submit" className="memory-btn memory-btn--primary" disabled={busy === 'add' || !text.trim()}>
                  Add
                </button>
              </form>
              {notice && (
                <p className="memory-notice" role="status">
                  {notice}
                </p>
              )}
              {error && (
                <p className="memory-error" role="alert">
                  {error}
                </p>
              )}
              {refreshProblem && (
                <p className="memory-dim reminders-stale" role="status">
                  Couldn&rsquo;t refresh just now, so this may be out of date. {refreshProblem}
                </p>
              )}

              {SECTIONS.map(({ state, title, empty }) => {
                const rows = reminders.filter((reminder) => reminder.state === state)
                return (
                  <section key={state} aria-labelledby={`reminders-${state}`}>
                    <h2 id={`reminders-${state}`}>
                      {title} ({rows.length})
                    </h2>
                    {rows.length === 0 ? (
                      <p className="memory-dim">{empty}</p>
                    ) : (
                      <ul className="memory-list">
                        {rows.map((reminder) => (
                          <li key={reminder.id} className="memory-fact reminder" data-state={reminder.state}>
                            <p className="memory-text">{reminder.content}</p>
                            <p className="memory-dim reminder-when-line">
                              {reminder.due_text
                                ? reminder.due_text
                                : reminder.said
                                  ? `You asked for “${reminder.said}”, which was not read as a time.`
                                  : 'No time was given.'}
                              {reminder.state === 'due' && reminder.told ? ' · You were told' : ''}
                            </p>
                            <div className="memory-actions">
                              <button
                                type="button"
                                className="memory-btn memory-btn--primary"
                                onClick={() => markDone(reminder)}
                                disabled={busy === String(reminder.id)}
                                aria-label={`Done: ${reminder.content}`}
                              >
                                Done
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                )
              })}
            </>
          )}
        </div>
      </main>
    </div>
  )
}
