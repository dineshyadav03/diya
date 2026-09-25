'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// What Diya knows about you, and what it has found that is waiting for you to decide (docs/STAGE2_DESIGN.md,
// unit 6). Everything shown here comes from the API already made safe to show (control and direction-changing
// characters arrive as visible escapes), and React renders it as text, never as markup.

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function Flags({ flags }) {
  if (!flags.length) return null
  return (
    <ul className="memory-flags" aria-label="Notes from the checks">
      {flags.map((flag) => (
        <li key={flag.code} className={`memory-flag ${flag.code.startsWith('source_message') ? 'memory-flag--source' : ''}`}>
          {flag.label}
        </li>
      ))}
    </ul>
  )
}

function Why({ detail }) {
  if (detail === false) return <div className="memory-why" role="status">Loading…</div>
  if (detail?.failed) return <div className="memory-why" role="alert">{detail.failed}</div>
  return (
    <div className="memory-why">
      {detail.flag_details.length > 0 && (
        <ul className="memory-why-flags">
          {detail.flag_details.map((text) => (
            <li key={text}>{text}</li>
          ))}
        </ul>
      )}
      {detail.range ? (
        <>
          <h3>What you said</h3>
          {detail.sources.length === 0 ? (
            <p className="memory-dim">None of those messages are in the database any more.</p>
          ) : (
            <ul className="memory-sources">
              {detail.sources.map((source) => (
                <li key={source.id}>
                  <q>{source.text}</q>
                </li>
              ))}
            </ul>
          )}
          {detail.staged && (
            <p className="memory-dim">
              The model wrote: <code>{detail.staged}</code> ({detail.model})
            </p>
          )}
        </>
      ) : (
        <p className="memory-dim">You added this yourself, or it came from your old profile.</p>
      )}
      <h3>History</h3>
      <ul className="memory-history">
        {detail.events.map((event, i) => (
          <li key={i}>
            {event.at.slice(0, 16).replace('T', ' ')} · {event.event} · {event.actor}
          </li>
        ))}
      </ul>
    </div>
  )
}

export default function MemoryPage() {
  // null = loading, false = couldn't be loaded, otherwise { summary, facts }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // what is being done right now: '', 'page', or a fact id
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [open, setOpen] = useState({}) // fact id -> its detail (false while it loads), for the "Why?" panels
  const [editing, setEditing] = useState(null) // { id, text }
  const [typed, setTyped] = useState('')

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/memory') // same-origin: app/api/memory forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (body && Array.isArray(body.facts) && body.summary) {
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

  async function loadDetail(id) {
    try {
      const response = await fetch(`/api/memory/${id}`)
      const body = response.ok ? await readJson(response) : null
      if (body && body.fact && Array.isArray(body.events)) return body
      return { failed: describeLoadFailure(response.status) }
    } catch {
      return { failed: describeLoadFailure() }
    }
  }

  async function toggleWhy(id) {
    if (open[id] !== undefined) {
      setOpen(({ [id]: _closed, ...rest }) => rest)
      return
    }
    setOpen((current) => ({ ...current, [id]: false }))
    const detail = await loadDetail(id)
    setOpen((current) => (id in current ? { ...current, [id]: detail } : current))
  }

  // Run a request the person asked for. On success say what happened and re-read the whole list (the
  // checks depend on the other facts, so a change to one can change what another says); on a refusal say
  // why, in the API's own words when it gave them.
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
    await load(false)
    const shown = Object.keys(open).filter((key) => open[key] !== undefined)
    const fresh = await Promise.all(shown.map((key) => loadDetail(key)))
    setOpen((current) => {
      const next = { ...current }
      shown.forEach((key, i) => {
        if (key in next) next[key] = fresh[i]
      })
      return next
    })
    setBusy('')
    return true
  }

  const decide = (fact, action, note) =>
    settle(() => fetch(`/api/memory/${fact.id}/${action}`, { method: 'POST' }), String(fact.id), () => note)

  function saveEdit(event) {
    event.preventDefault()
    const { id, text } = editing
    settle(
      () =>
        fetch(`/api/memory/${id}/edit`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        }),
      String(id),
      () => 'Reworded.',
    ).then((ok) => ok && setEditing(null))
  }

  function addFact(event) {
    event.preventDefault()
    settle(
      () =>
        fetch('/api/memory/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: typed }),
        }),
      'page',
      () => 'Added. Diya will know it from the next message.',
    ).then((ok) => ok && setTyped(''))
  }

  function checkForNew() {
    settle(
      () => fetch('/api/memory/ingest', { method: 'POST' }),
      'page',
      ({ report }) =>
        report.new > 0
          ? `Found ${report.new} new ${report.new === 1 ? 'fact' : 'facts'} to review.`
          : 'Nothing new since the last check.',
    )
  }

  const facts = data ? data.facts : []
  const withStatus = (status) => facts.filter((fact) => fact.status === status)
  const candidates = withStatus('candidate')
  const accepted = withStatus('accepted')
  const rejected = withStatus('rejected')
  const retired = withStatus('retired')
  const summary = data ? data.summary : null

  // A plain function that returns the row, NOT a component: a component defined here would be a new type on
  // every render and would remount the edit box (and drop its focus) at every keystroke.
  function factRow(fact, actions) {
    const isBusy = busy === String(fact.id)
    const isEditing = editing && editing.id === fact.id
    return (
      <li key={fact.id} className="memory-fact" data-status={fact.status}>
        {isEditing ? (
          <form className="memory-edit" onSubmit={saveEdit}>
            <label className="memory-sr" htmlFor={`edit-${fact.id}`}>
              Reword this fact
            </label>
            <input
              id={`edit-${fact.id}`}
              className="memory-input"
              value={editing.text}
              onChange={(e) => setEditing({ id: fact.id, text: e.target.value })}
              autoFocus
            />
            <button type="submit" className="memory-btn memory-btn--primary" disabled={isBusy || !editing.text.trim()}>
              Save
            </button>
            <button type="button" className="memory-btn" onClick={() => setEditing(null)}>
              Cancel
            </button>
          </form>
        ) : (
          <p className="memory-text">{fact.text}</p>
        )}
        <Flags flags={fact.flags} />
        {!isEditing && (
          <div className="memory-actions">
            {actions({ fact, isBusy })}
            <button
              type="button"
              className="memory-btn memory-btn--quiet"
              aria-expanded={open[fact.id] !== undefined}
              onClick={() => toggleWhy(fact.id)}
            >
              {open[fact.id] !== undefined ? 'Hide' : 'Why?'}
            </button>
          </div>
        )}
        {open[fact.id] !== undefined && <Why detail={open[fact.id]} />}
      </li>
    )
  }

  const button = (label, className, onClick, disabled, fact) => (
    <button type="button" className={`memory-btn ${className}`} onClick={onClick} disabled={disabled} aria-label={`${label}: ${fact.text}`}>
      {label}
    </button>
  )

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
          <Link className="icon-btn" href="/">
            &larr; Back to chat
          </Link>
        </div>
      </header>
      <main className="history-page memory-page">
        <div className="history-inner">
          <h1>Memory</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your memory">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your memory</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-lede">
                What Diya knows about you. Facts it finds in your conversations wait here until you accept them; only
                accepted facts are ever told to the model.
              </p>
              <div className="memory-summary">
                <div className="memory-meter" aria-hidden="true">
                  <div style={{ width: `${Math.min(100, (summary.used / summary.limit) * 100)}%` }} />
                </div>
                <span>
                  {summary.used} of {summary.limit} characters used
                </span>
                <button type="button" className="memory-btn" onClick={checkForNew} disabled={busy === 'page'}>
                  Check for new facts
                </button>
              </div>
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

              <section aria-labelledby="waiting">
                <h2 id="waiting">Waiting for you ({candidates.length})</h2>
                {candidates.length === 0 ? (
                  <p className="memory-dim">Nothing is waiting for review.</p>
                ) : (
                  <ul className="memory-list">
                    {candidates.map((fact) =>
                      factRow(fact, ({ isBusy }) => (
                        <>
                          {button('Accept', 'memory-btn--primary', () => decide(fact, 'accept', 'Accepted. Diya will know it from the next message.'), isBusy, fact)}
                          {button('Edit', '', () => setEditing({ id: fact.id, text: fact.text }), isBusy, fact)}
                          {button('Reject', 'memory-btn--danger', () => decide(fact, 'reject', 'Rejected.'), isBusy, fact)}
                        </>
                      )),
                    )}
                  </ul>
                )}
              </section>

              <section aria-labelledby="known">
                <h2 id="known">What Diya knows ({accepted.length})</h2>
                {accepted.length === 0 ? (
                  <p className="memory-dim">Nothing yet.</p>
                ) : (
                  <ul className="memory-list">
                    {accepted.map((fact) =>
                      factRow(fact, ({ isBusy }) =>
                        button('Forget', 'memory-btn--danger', () => decide(fact, 'retire', 'Forgotten: Diya will not use it from the next message.'), isBusy, fact),
                      ),
                    )}
                  </ul>
                )}
                <form className="memory-add" onSubmit={addFact}>
                  <label className="memory-sr" htmlFor="new-fact">
                    Add something Diya should know
                  </label>
                  <input
                    id="new-fact"
                    className="memory-input"
                    placeholder="Add something Diya should know…"
                    value={typed}
                    onChange={(e) => setTyped(e.target.value)}
                  />
                  <button type="submit" className="memory-btn memory-btn--primary" disabled={busy === 'page' || !typed.trim()}>
                    Add
                  </button>
                </form>
              </section>

              {(rejected.length > 0 || retired.length > 0) && (
                <section aria-labelledby="past">
                  <h2 id="past">Decided before</h2>
                  {retired.length > 0 && (
                    <details>
                      <summary>Forgotten ({retired.length})</summary>
                      <ul className="memory-list">
                        {retired.map((fact) =>
                          factRow(fact, ({ isBusy }) => button('Remember again', '', () => decide(fact, 'restore', 'Remembered again.'), isBusy, fact)),
                        )}
                      </ul>
                    </details>
                  )}
                  {rejected.length > 0 && (
                    <details>
                      <summary>Rejected ({rejected.length})</summary>
                      <ul className="memory-list">
                        {rejected.map((fact) =>
                          factRow(fact, ({ isBusy }) => button('Reconsider', '', () => decide(fact, 'reopen', 'Back in the list to review.'), isBusy, fact)),
                        )}
                      </ul>
                    </details>
                  )}
                </section>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}
