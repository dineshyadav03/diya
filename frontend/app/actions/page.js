'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'
import { sourceWords, statusWords, timeLeft } from '../../lib/actions-format.mjs'

// What Diya has asked to do outside this computer, and what you have decided (docs/ACTIONS_DESIGN.md, unit A3).
// Nothing here happens until you press Approve: the sentence on each card is built by the server from the
// arguments, never from what the model said, and Approve sends back the exact version you were looking at, so an
// action changed in the meantime is refused instead of run. Everything shown comes from the API already made safe
// to show, and an approval reaches no model at all.

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function Fields({ fields }) {
  if (!fields.length) return null
  return (
    <dl className="action-fields">
      {fields.map((field) => (
        <div key={field.name} className="action-field">
          <dt>{field.name}</dt>
          <dd>{field.value === null ? '(empty)' : field.value}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function ActionsPage() {
  // null = loading, false = couldn't be loaded, otherwise { pending, history, counts, kinds }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(0) // 0, or the id of the action being decided
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [notes, setNotes] = useState({}) // id -> the note typed for an unknown outcome
  const [now, setNow] = useState(() => Date.now()) // so "expires in" counts down while the page is open

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/actions')
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (body && Array.isArray(body.pending) && Array.isArray(body.history)) {
        setData(body)
        setProblem('')
        return true
      }
    } catch {
      status = undefined
    }
    if (first) {
      setProblem(describeLoadFailure(status))
      setData(false)
    } else {
      setError(describeLoadFailure(status))
    }
    return false
  }, [])

  useEffect(() => {
    load(true)
  }, [load])

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(timer)
  }, [])

  // Send one decision, then ask again for the whole list: the answer to a decision is only the one action.
  async function settle(request, id, describe) {
    setBusy(id)
    setError('')
    setNotice('')
    let response
    try {
      response = await request()
    } catch {
      setError(describeActionFailure())
      setBusy(0)
      return
    }
    const body = await readJson(response)
    if (!response.ok || !body || !body.action) {
      setError(describeActionFailure(response.ok ? undefined : response.status, body?.detail))
      await load(false)
      setBusy(0)
      return
    }
    const result = describe(body.action)
    if (result.ok) setNotice(result.text)
    else setError(result.text)
    await load(false)
    setBusy(0)
  }

  function approve(action) {
    settle(
      () =>
        fetch(`/api/actions/${action.id}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ args_hash: action.args_hash }),
        }),
      action.id,
      (done) =>
        done.status === 'succeeded'
          ? { ok: true, text: `Done: ${done.summary}.${done.result ? ` ${done.result}` : ''}` }
          : done.status === 'unknown'
            ? { ok: false, text: `Not sure it was done: ${done.summary}. ${done.result || 'What happened is not known.'}` }
            : { ok: false, text: `Not done: ${done.summary}. ${done.result || statusWords(done.status)}` },
    )
  }

  function reject(action) {
    settle(
      () => fetch(`/api/actions/${action.id}/reject`, { method: 'POST' }),
      action.id,
      (done) => ({ ok: true, text: `Turned down: ${done.summary}. It will not be done.` }),
    )
  }

  function resolve(action, happened) {
    settle(
      () =>
        fetch(`/api/actions/${action.id}/resolve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ happened, note: (notes[action.id] || '').trim() || null }),
        }),
      action.id,
      (done) => ({ ok: true, text: `Recorded: ${done.summary} — ${happened ? 'it happened' : 'it did not happen'}.` }),
    ).then(() => setNotes((current) => ({ ...current, [action.id]: '' })))
  }

  const pending = data ? data.pending : []
  const history = data ? data.history : []
  const unknown = history.filter((action) => action.status === 'unknown')
  const decided = history.filter((action) => action.status !== 'unknown')
  const kinds = data ? data.kinds : []

  return (
    <main className="history-page memory-page actions-page">
        <div className="history-inner">
          <h1>Actions</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your actions">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your actions</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-lede">
                Diya never changes anything outside this computer on its own. When it wants to, it asks here first, and
                nothing happens until you approve it.
              </p>
              <p className="memory-dim">
                {kinds.length === 0
                  ? 'Right now Diya has no way to propose any change: every connector is read-only.'
                  : `What Diya can propose: ${kinds
                      .map((kind) => `${kind.label}${kind.available ? '' : ' (needs its connection first)'}`)
                      .join(', ')}.`}
              </p>
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

              <h2 id="waiting">Waiting for you ({pending.length})</h2>
              {pending.length === 0 ? (
                <p className="memory-dim">Nothing is waiting for you.</p>
              ) : (
                <ul className="memory-list" aria-labelledby="waiting">
                  {pending.map((action) => {
                    const isBusy = busy === action.id
                    const left = timeLeft(action.expires_at, now)
                    return (
                      <li key={action.id} className="memory-fact" data-status="candidate">
                        <p className="memory-text">{action.summary}</p>
                        <p className="memory-dim">{action.label}</p>
                        <Fields fields={action.fields} />
                        {action.tainted && (
                          <p className="action-caution">
                            Diya read from {sourceWords(action.taint_sources)} before proposing this. That text is not
                            yours: check the details above are what you wanted.
                          </p>
                        )}
                        <p className="memory-person-tag">
                          {[left, action.thread_id !== null ? 'from a chat' : ''].filter(Boolean).join(' · ')}
                          {action.thread_id !== null && (
                            <>
                              {' '}
                              (<Link href={`/?thread=${action.thread_id}`}>open it</Link>)
                            </>
                          )}
                        </p>
                        <div className="memory-actions">
                          <button
                            type="button"
                            className="memory-btn memory-btn--primary"
                            onClick={() => approve(action)}
                            disabled={isBusy || left === 'expired'}
                            aria-label={`Approve: ${action.summary}`}
                          >
                            {isBusy ? 'Doing it…' : 'Approve'}
                          </button>
                          <button
                            type="button"
                            className="memory-btn memory-btn--danger"
                            onClick={() => reject(action)}
                            disabled={isBusy}
                            aria-label={`Turn down: ${action.summary}`}
                          >
                            Turn down
                          </button>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              )}

              {unknown.length > 0 && (
                <>
                  <h2 id="unknown">Needs a look ({unknown.length})</h2>
                  <ul className="memory-list" aria-labelledby="unknown">
                    {unknown.map((action) => {
                      const isBusy = busy === action.id
                      return (
                        <li key={action.id} className="memory-fact" data-status="unknown">
                          <p className="memory-text">{action.summary}</p>
                          <p className="memory-dim">
                            {action.result
                              ? `${action.result} It will not be done again.`
                              : 'Diya was interrupted while doing this, so what happened is not known. It will not be done again. Check the service yourself, then tell Diya what you found.'}
                          </p>
                          <Fields fields={action.fields} />
                          <form className="memory-edit" onSubmit={(e) => e.preventDefault()}>
                            <label className="memory-sr" htmlFor={`note-${action.id}`}>
                              A note about what you found
                            </label>
                            <input
                              id={`note-${action.id}`}
                              className="memory-input"
                              type="text"
                              maxLength={300}
                              placeholder="A note (optional)…"
                              value={notes[action.id] || ''}
                              onChange={(e) => setNotes((current) => ({ ...current, [action.id]: e.target.value }))}
                            />
                          </form>
                          <div className="memory-actions">
                            <button
                              type="button"
                              className="memory-btn memory-btn--primary"
                              onClick={() => resolve(action, true)}
                              disabled={isBusy}
                              aria-label={`It happened: ${action.summary}`}
                            >
                              It happened
                            </button>
                            <button
                              type="button"
                              className="memory-btn"
                              onClick={() => resolve(action, false)}
                              disabled={isBusy}
                              aria-label={`It did not happen: ${action.summary}`}
                            >
                              It did not happen
                            </button>
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                </>
              )}

              {decided.length > 0 && (
                <>
                  <h2 id="past">Decided before</h2>
                  <ul className="memory-list" aria-labelledby="past">
                    {decided.map((action) => (
                      <li key={action.id} className="memory-fact" data-status={action.status}>
                        <p className="memory-text">{action.summary}</p>
                        <p className="memory-person-tag">
                          {statusWords(action.status)}
                          {action.decided_at ? ` · decided ${action.decided_at.replace('T', ' ').replace('Z', ' UTC')}` : ''}
                        </p>
                        {action.result && <p className="memory-dim">{action.result}</p>}
                        {action.tainted && (
                          <p className="memory-dim">Proposed after Diya read from {sourceWords(action.taint_sources)}.</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      </main>
  )
}
