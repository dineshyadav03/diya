'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// Which outside accounts Diya can reach, and whether this install is connected to them
// (docs/CONNECTORS_DESIGN.md, unit C1). Every connector starts disconnected and read-only; nothing
// here is wired to any one person's account -- whoever owns this install picks what to turn on.
// Everything shown comes from the API already made safe to show, and a stored token is never sent
// back here: only whether one exists.

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

export default function ConnectionsPage() {
  // null = loading, false = couldn't be loaded, otherwise { connectors }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // '', or a connector name
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [tokenInputs, setTokenInputs] = useState({}) // name -> the pasted-token form's current text

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/connections')
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (body && Array.isArray(body.connectors)) {
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

  async function settle(request, name, describe) {
    setBusy(name)
    setError('')
    setNotice('')
    let response
    try {
      response = await request()
    } catch {
      setError(describeActionFailure())
      setBusy('')
      return
    }
    const body = await readJson(response)
    if (!response.ok || !body) {
      setError(describeActionFailure(response.ok ? undefined : response.status, body?.detail))
      if (response.ok) await load(false)
      setBusy('')
      return
    }
    setNotice(describe(body))
    setData(body)
    setBusy('')
  }

  function connectWithToken(event, connector) {
    event.preventDefault()
    const token = (tokenInputs[connector.name] || '').trim()
    if (!token) return
    settle(
      () =>
        fetch(`/api/connections/${connector.name}/connect`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token }),
        }),
      connector.name,
      () => `Connected to ${connector.label}.`,
    ).then(() => setTokenInputs((current) => ({ ...current, [connector.name]: '' })))
  }

  function connectOAuth(connector) {
    // No body: this opens the owner's own browser server-side and blocks until they finish there
    // (docs/CONNECTORS_DESIGN.md, D6) -- the button just waits longer than a token-kind Connect does.
    settle(
      () => fetch(`/api/connections/${connector.name}/connect`, { method: 'POST' }),
      connector.name,
      () => `Connected to ${connector.label}.`,
    )
  }

  function disconnect(connector) {
    settle(
      () => fetch(`/api/connections/${connector.name}/disconnect`, { method: 'POST' }),
      connector.name,
      () => `Disconnected from ${connector.label}.`,
    )
  }

  const connectors = data ? data.connectors : []

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
          <Link className="icon-btn" href="/actions">
            Actions
          </Link>
          <Link className="icon-btn" href="/">
            &larr; Back to chat
          </Link>
        </div>
      </header>
      <main className="history-page memory-page connections-page">
        <div className="history-inner">
          <h1>Connections</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your connections">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your connections</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-lede">
                Outside accounts Diya can reach, once you connect them. Nothing here is connected by default, and a
                connector only ever reads until you decide otherwise.
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
              {connectors.length === 0 ? (
                <p className="memory-dim">No connectors are available yet.</p>
              ) : (
                <ul className="memory-list">
                  {connectors.map((connector) => {
                    const isBusy = busy === connector.name
                    return (
                      <li key={connector.name} className="memory-fact" data-status={connector.connected ? 'accepted' : 'candidate'}>
                        <p className="memory-text">{connector.label}</p>
                        <p className="memory-dim">{connector.description}</p>
                        <p className="memory-person-tag">{connector.connected ? 'Connected' : 'Not connected'}</p>
                        {connector.connected ? (
                          <div className="memory-actions">
                            <button
                              type="button"
                              className="memory-btn memory-btn--danger"
                              onClick={() => disconnect(connector)}
                              disabled={isBusy}
                              aria-label={`Disconnect: ${connector.label}`}
                            >
                              Disconnect
                            </button>
                          </div>
                        ) : !connector.implemented ? (
                          <p className="memory-dim">Not available yet.</p>
                        ) : connector.auth_kind === 'token' ? (
                          <form className="memory-edit" onSubmit={(e) => connectWithToken(e, connector)}>
                            <label className="memory-sr" htmlFor={`token-${connector.name}`}>
                              {connector.label} token
                            </label>
                            <input
                              id={`token-${connector.name}`}
                              className="memory-input"
                              type="password"
                              placeholder="Paste your token…"
                              value={tokenInputs[connector.name] || ''}
                              onChange={(e) => setTokenInputs((current) => ({ ...current, [connector.name]: e.target.value }))}
                            />
                            <button
                              type="submit"
                              className="memory-btn memory-btn--primary"
                              disabled={isBusy || !(tokenInputs[connector.name] || '').trim()}
                            >
                              Connect
                            </button>
                          </form>
                        ) : (
                          <div className="memory-actions">
                            <button
                              type="button"
                              className="memory-btn memory-btn--primary"
                              onClick={() => connectOAuth(connector)}
                              disabled={isBusy}
                            >
                              {isBusy ? 'Waiting for your browser…' : 'Connect'}
                            </button>
                          </div>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}
