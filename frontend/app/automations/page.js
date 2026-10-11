'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// Things Diya does on a schedule and writes you the answer of (docs/AUTOMATIONS_DESIGN.md). Everything shown comes from the API already made
// safe to show, and React renders it as text, never as markup. The page looks again once a minute while it is open. Deleting is the one thing
// here that cannot be undone, so it takes two presses; Run now can take a minute (the model is looking things up), so it says it is working.

const REFRESH_MS = 60_000
const EXAMPLE = 'every morning at 8am tell me the weather in Pune'

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isList(body) {
  return body && Array.isArray(body.automations) && typeof body.enabled === 'boolean'
}

export default function AutomationsPage() {
  // null = loading, false = couldn't be loaded, otherwise { enabled, max, automations }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // '', 'add', or an automation's id
  const [armed, setArmed] = useState(null) // the automation whose Delete has been pressed once
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('') // the result of something the person just did, and only that
  const [refreshProblem, setRefreshProblem] = useState('') // the once-a-minute look failed; kept apart so it never stands in for, or wipes, an action's result
  const [text, setText] = useState('')

  const load = useCallback(async (first, quiet = false) => {
    let status
    try {
      const response = await fetch('/api/automations') // same-origin: app/api/automations forwards it, with the token, from the server
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

  // Run a request the person asked for. On success say what happened (and use the list the API sent back); on a refusal say why, in the API's
  // own words when it gave them, and that nothing was changed.
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

  function add(event) {
    event.preventDefault()
    settle(
      () =>
        fetch('/api/automations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        }),
      'add',
      ({ created }) => `Set up. ${created.rule}. The first one is ${created.next}.`,
    ).then((ok) => {
      if (ok) setText('')
    })
  }

  const act = (item, action, said) => settle(() => fetch(`/api/automations/${item.id}/${action}`, { method: 'POST' }), String(item.id), said)
  const pause = (item) => act(item, 'pause', () => 'Paused. It will not run until you resume it.')
  const resume = (item) => act(item, 'resume', () => 'Resumed. It will run next time its time comes.')
  const remove = (item) => act(item, 'delete', () => 'Deleted.')
  const runNow = (item) =>
    act(item, 'run', (body) => (body.wrote ? 'Done. What it found is in your chat.' : 'It ran but had nothing to say.'))

  const items = data ? data.automations : []

  return (
    <main className="history-page memory-page reminders-page scheduled-page">
      <div className="history-inner">
        <h1>Automations</h1>
        {data === null ? (
          <div role="status" aria-label="Loading your automations">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : data === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t load your automations</h2>
            <p>{problem}</p>
            <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <p className="memory-lede">
              Tell Diya once what to do and when, and she does it on her own and writes you the answer in your chat. For example:
              &ldquo;{EXAMPLE}&rdquo;. She can look up the weather and the web and read your notes, reminders and tasks, and only read:
              an automation can&rsquo;t save, send or change anything. You can say it here or in the chat.
            </p>
            {!data.enabled && (
              <p className="memory-dim" role="status">
                Automations are switched off (DIYA_AUTOMATIONS=0), so nothing here will run until they are switched on again.
              </p>
            )}
            <form className="memory-add reminder-add" onSubmit={add}>
              <label className="memory-sr" htmlFor="automation-text">
                What Diya should do, and when
              </label>
              <input
                id="automation-text"
                className="memory-input"
                placeholder={`Say it, e.g. ${EXAMPLE}`}
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
              <button type="submit" className="memory-btn memory-btn--primary" disabled={busy === 'add' || !text.trim() || !data.enabled}>
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

            <section aria-labelledby="automations-list">
              <h2 id="automations-list">
                Yours ({items.length} of {data.max})
              </h2>
              {items.length === 0 ? (
                <p className="memory-dim">Nothing yet. Add one above, or ask Diya in the <Link href="/">chat</Link>.</p>
              ) : (
                <ul className="memory-list">
                  {items.map((item) => {
                    const mine = busy === String(item.id)
                    return (
                      <li key={item.id} className="memory-fact scheduled" data-state={item.state}>
                        <p className="memory-text">{item.instruction}</p>
                        <p className="memory-dim reminder-when-line">
                          {item.state === 'paused' && <span className="scheduled-paused">Paused · </span>}
                          {item.rule}
                          {item.state === 'active' && item.next ? ` · Next: ${item.next}` : ''}
                          {item.last_run ? ` · Last run: ${item.last_run}${item.last_status ? ` (${item.last_status})` : ''}` : ' · Has not run yet'}
                        </p>
                        {mine && <p className="memory-dim" role="status">Working on it. This can take a minute.</p>}
                        <div className="memory-actions">
                          <button type="button" className="memory-btn memory-btn--primary" onClick={() => runNow(item)} disabled={mine || !data.enabled} aria-label={`Run now: ${item.instruction}`}>
                            Run now
                          </button>
                          {item.state === 'active' ? (
                            <button type="button" className="memory-btn" onClick={() => pause(item)} disabled={mine} aria-label={`Pause: ${item.instruction}`}>
                              Pause
                            </button>
                          ) : (
                            <button type="button" className="memory-btn" onClick={() => resume(item)} disabled={mine} aria-label={`Resume: ${item.instruction}`}>
                              Resume
                            </button>
                          )}
                          {armed === item.id ? (
                            <>
                              <button type="button" className="memory-btn memory-btn--danger" onClick={() => remove(item)} disabled={mine} aria-label={`Delete for good: ${item.instruction}`}>
                                Delete for good
                              </button>
                              <button type="button" className="memory-btn" onClick={() => setArmed(null)} aria-label={`Keep: ${item.instruction}`}>
                                Keep it
                              </button>
                            </>
                          ) : (
                            <button type="button" className="memory-btn memory-btn--danger" onClick={() => setArmed(item.id)} disabled={mine} aria-label={`Delete: ${item.instruction}`}>
                              Delete
                            </button>
                          )}
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </main>
  )
}
