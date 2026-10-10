'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// Reminders that come back on their own (docs/SCHEDULE_DESIGN.md, unit R4). Everything shown comes from the API already
// made safe to show (control and direction-changing characters arrive as visible escapes), and React renders it as text,
// never as markup. The page looks again once a minute while it is open, so what Diya sets up from the chat in another tab
// appears without a reload. Stopping is the one thing here that cannot be undone, so it takes two presses.

const REFRESH_MS = 60_000

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function when(stamp) {
  const date = new Date(stamp)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function isList(body) {
  return body && Array.isArray(body.series) && Array.isArray(body.events) && body.counts
}

export default function ScheduledPage() {
  // null = loading, false = couldn't be loaded, otherwise { series, events, counts }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // '', 'add', or a series id
  const [armed, setArmed] = useState(null) // the series whose Stop has been pressed once
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('') // the result of something the person just did, and only that
  const [refreshProblem, setRefreshProblem] = useState('') // the once-a-minute look failed; kept apart so it never stands in for, or wipes, an action's result
  const [text, setText] = useState('')
  const [repeat, setRepeat] = useState('')

  const load = useCallback(async (first, quiet = false) => {
    let status
    try {
      const response = await fetch('/api/scheduled') // same-origin: app/api/scheduled forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (isList(body)) {
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
    setArmed(null)
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
    if (isList(body)) setData(body)
    else await load(false)
    setBusy('')
    return true
  }

  function addSeries(event) {
    event.preventDefault()
    settle(
      () =>
        fetch('/api/scheduled', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, repeat }),
        }),
      'add',
      ({ created, assumed }) => {
        const first = `Set up. ${created.rule}. The first reminder is ${created.next}.`
        return Array.isArray(assumed) && assumed.length ? `${first} (${assumed.join('; ')})` : first
      },
    ).then((ok) => {
      if (ok) {
        setText('')
        setRepeat('')
      }
    })
  }

  const act = (series, action, said) => settle(() => fetch(`/api/scheduled/${series.id}/${action}`, { method: 'POST' }), String(series.id), () => said)
  const pause = (series) => act(series, 'pause', 'Paused. It will not make reminders until you resume it.')
  const resume = (series) => act(series, 'resume', 'Resumed. It will make its next reminder when its time comes.')
  const skip = (series) => act(series, 'skip', 'Skipped. That time will pass without a reminder.')
  const stop = (series) => act(series, 'stop', 'Stopped. It will not make any more reminders. One it already made stays until you mark it done.')

  const all = data ? data.series : []
  const running = all.filter((series) => series.state !== 'ended')
  const ended = all.filter((series) => series.state === 'ended')
  const events = data ? data.events : []

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
          <Link className="icon-btn" href="/reminders">
            Reminders
          </Link>
          <Link className="icon-btn" href="/today">
            Today
          </Link>
          <Link className="icon-btn" href="/tasks">
            Tasks
          </Link>
          <Link className="icon-btn" href="/connections">
            Connections
          </Link>
          <Link className="icon-btn" href="/actions">
            Actions
          </Link>
          <Link className="icon-btn" href="/">
            &larr; Back to chat
          </Link>
        </div>
      </header>
      <main className="history-page memory-page reminders-page scheduled-page">
        <div className="history-inner">
          <h1>Scheduled</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your repeating reminders">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your repeating reminders</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-lede">
                Reminders that come back on their own. Say &ldquo;remind me every Monday to&hellip;&rdquo; in the chat, or add one here.
                Each time one falls it becomes an ordinary reminder under Reminders. If you never get to it, it is closed when the next
                one arrives, not piled up.
              </p>
              <form className="memory-add reminder-add" onSubmit={addSeries}>
                <label className="memory-sr" htmlFor="scheduled-text">
                  What to be reminded of
                </label>
                <input
                  id="scheduled-text"
                  className="memory-input"
                  placeholder="Remind me to…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <label className="memory-sr" htmlFor="scheduled-repeat">
                  How often (for example every Monday at 9am, or every 2 weeks)
                </label>
                <input
                  id="scheduled-repeat"
                  className="memory-input reminder-when"
                  placeholder="How often, e.g. every Monday"
                  value={repeat}
                  onChange={(e) => setRepeat(e.target.value)}
                />
                <button type="submit" className="memory-btn memory-btn--primary" disabled={busy === 'add' || !text.trim() || !repeat.trim()}>
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

              <section aria-labelledby="scheduled-running">
                <h2 id="scheduled-running">Repeating ({running.length})</h2>
                {running.length === 0 ? (
                  <p className="memory-dim">Nothing repeats yet. Add one above, or ask Diya to in the chat.</p>
                ) : (
                  <ul className="memory-list">
                    {running.map((series) => {
                      const mine = busy === String(series.id)
                      return (
                        <li key={series.id} className="memory-fact scheduled" data-state={series.state}>
                          <p className="memory-text">{series.content}</p>
                          <p className="memory-dim reminder-when-line">
                            {series.state === 'paused' && <span className="scheduled-paused">Paused · </span>}
                            {series.rule}
                            {series.state === 'active' && series.next ? ` · Next: ${series.next}` : ''}
                            {series.from_chat ? ' · Set up from the chat' : ''}
                          </p>
                          <div className="memory-actions">
                            {series.state === 'active' ? (
                              <>
                                <button type="button" className="memory-btn" onClick={() => pause(series)} disabled={mine} aria-label={`Pause: ${series.content}`}>
                                  Pause
                                </button>
                                <button type="button" className="memory-btn" onClick={() => skip(series)} disabled={mine} aria-label={`Skip the next time of: ${series.content}`}>
                                  Skip next
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="memory-btn memory-btn--primary"
                                onClick={() => resume(series)}
                                disabled={mine}
                                aria-label={`Resume: ${series.content}`}
                              >
                                Resume
                              </button>
                            )}
                            {armed === series.id ? (
                              <>
                                <button
                                  type="button"
                                  className="memory-btn memory-btn--danger"
                                  onClick={() => stop(series)}
                                  disabled={mine}
                                  aria-label={`Stop for good: ${series.content}`}
                                >
                                  Stop for good
                                </button>
                                <button type="button" className="memory-btn" onClick={() => setArmed(null)} aria-label={`Keep: ${series.content}`}>
                                  Keep it
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="memory-btn memory-btn--danger"
                                onClick={() => setArmed(series.id)}
                                disabled={mine}
                                aria-label={`Stop: ${series.content}`}
                              >
                                Stop
                              </button>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>

              <details className="scheduled-ended">
                <summary>Stopped ({ended.length})</summary>
                {ended.length === 0 ? (
                  <p className="memory-dim">Nothing has been stopped.</p>
                ) : (
                  <ul className="memory-list">
                    {ended.map((series) => (
                      <li key={series.id} className="memory-fact scheduled" data-state="ended">
                        <p className="memory-text">{series.content}</p>
                        <p className="memory-dim reminder-when-line">
                          {series.rule}
                          {series.ended_at && when(series.ended_at) ? ` · Stopped ${when(series.ended_at)}` : ' · Stopped'}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </details>

              <section aria-labelledby="scheduled-events">
                <h2 id="scheduled-events">What happened lately</h2>
                {events.length === 0 ? (
                  <p className="memory-dim">Nothing yet.</p>
                ) : (
                  <ul className="scheduled-trail">
                    {events.map((item) => (
                      <li key={item.id}>
                        <span className="memory-dim">{when(item.at) || 'Some time ago'}</span> · {item.text}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
