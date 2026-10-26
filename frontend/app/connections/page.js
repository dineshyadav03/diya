'use client'

import { useCallback, useEffect, useState } from 'react'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// Which outside accounts Diya can reach, and whether this install is connected to them
// (docs/CONNECTORS_DESIGN.md, unit C1). Every connector starts disconnected and read-only; nothing
// here is wired to any one person's account -- whoever owns this install picks what to turn on.
// Everything shown comes from the API already made safe to show, and a stored token is never sent
// back here: only whether one exists.

// Google's cards. One sign-in on Google's screen can connect all of them (the "Connect all Google" button); each still connects, and disconnects, on its own.
const GOOGLE_CARDS = ['google_calendar', 'google_mail', 'google_calendar_edit', 'google_tasks', 'google_drive_files']

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
  const [setupInputs, setSetupInputs] = useState({}) // name -> { field name -> what has been typed in that box of the one-time setup form }
  const [permissions, setPermissions] = useState({}) // name -> what that connection can do, since when, when last used (docs/PERMISSIONS_DESIGN.md); empty if it could not be read: the page works without it

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

  const loadPermissions = useCallback(async () => {
    try {
      const response = await fetch('/api/permissions')
      const body = response.ok ? await readJson(response) : null
      if (body && Array.isArray(body.connectors)) setPermissions(Object.fromEntries(body.connectors.map((item) => [item.name, item])))
    } catch {
      // an extra: if it cannot be read, the cards show what they always showed
    }
  }, [])

  useEffect(() => {
    load(true)
    loadPermissions()
  }, [load, loadPermissions])

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
    loadPermissions()
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

  // One trip to Google's screen for every Google card. The call waits for the owner to finish there; the answer says which cards were connected and which were left out (a permission unticked on Google's screen).
  function connectAllGoogle() {
    settle(
      () => fetch('/api/connections/connect-google', { method: 'POST' }),
      'google-all',
      (body) =>
        body.left_out && body.left_out.length
          ? `Connected: ${body.connected.join(', ')}. Left off, because the permission was not allowed on Google's screen: ${body.left_out.join(', ')}.`
          : `Connected: ${body.connected.join(', ')}.`,
    )
  }

  // The one-time setup of a connector that needs something given once (Google's client ID and secret). What was typed is sent, and then forgotten here: it is never shown again.
  function saveSetup(event, connector) {
    event.preventDefault()
    const values = setupInputs[connector.name] || {}
    settle(
      () =>
        fetch(`/api/connections/${connector.name}/setup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ values }),
        }),
      connector.name,
      () => `${connector.label} is set up. Press Connect to sign in.`,
    ).then(() => setSetupInputs((current) => ({ ...current, [connector.name]: {} })))
  }

  function clearSetup(connector) {
    settle(
      () => fetch(`/api/connections/${connector.name}/clear-setup`, { method: 'POST' }),
      connector.name,
      () => `${connector.label}'s app was forgotten, and it was disconnected. Paste a new one to set it up again.`,
    )
  }

  function disconnect(connector) {
    settle(
      () => fetch(`/api/connections/${connector.name}/disconnect`, { method: 'POST' }),
      connector.name,
      (body) =>
        body.revoked === true
          ? `Disconnected from ${connector.label}, and Google was told to forget the permission.`
          : body.revoked === false
            ? `Disconnected from ${connector.label} here. Google did not confirm that it forgot the permission: you can remove Diya at myaccount.google.com/permissions.`
            : `Disconnected from ${connector.label}.`,
    )
  }

  const connectors = data ? data.connectors : []
  const googleCards = connectors.filter((connector) => GOOGLE_CARDS.includes(connector.name) && connector.implemented)
  // Offered once Google's app is set up (its id and secret are shared by every Google card) and while some Google card is still off.
  const canConnectAllGoogle = googleCards.length > 1 && googleCards.some((connector) => connector.setup && connector.setup.done) && googleCards.some((connector) => !connector.connected)

  return (
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
                Outside accounts Diya can reach, once you connect them. Nothing here is connected by default. Diya reads
                from a connected account on its own; anything that would change one waits for your approval, one action
                at a time, on the Actions page or right under the chat. The only exception is an addition that touches
                just you (an event, a task, a folder, a document) which you have switched to &ldquo;do straight away&rdquo; on the
                Actions page.
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
                  {canConnectAllGoogle && (
                    <li className="memory-fact" data-status="candidate">
                      <p className="memory-text">Connect all of Google at once</p>
                      <p className="memory-dim">
                        One Google screen, one Allow. It connects Calendar (reading), Gmail (reading), adding events, Tasks, and Drive and Docs (new things only). On Google&rsquo;s screen you can untick any of
                        them: that card just stays off. You can still disconnect any card on its own afterwards, and every change Diya makes still waits for your approval.
                      </p>
                      <div className="memory-actions">
                        <button type="button" className="memory-btn memory-btn--primary" onClick={connectAllGoogle} disabled={busy !== ''}>
                          {busy === 'google-all' ? 'Waiting for your browser…' : 'Connect all Google'}
                        </button>
                      </div>
                    </li>
                  )}
                  {connectors.map((connector) => {
                    const isBusy = busy === connector.name || (busy === 'google-all' && GOOGLE_CARDS.includes(connector.name))
                    return (
                      <li key={connector.name} className="memory-fact" data-status={connector.connected ? 'accepted' : 'candidate'}>
                        <p className="memory-text">{connector.label}</p>
                        <p className="memory-dim">{connector.description}</p>
                        {permissions[connector.name] && (
                          <div className="connection-access">
                            <p className="memory-dim">What this connection can do:</p>
                            <ul>
                              {permissions[connector.name].access.map((line) => (
                                <li key={line} className="memory-dim">
                                  {line}
                                </li>
                              ))}
                            </ul>
                            {permissions[connector.name].scope && (
                              <p className="memory-dim">
                                The permission it asks the service for: <code>{permissions[connector.name].scope}</code>
                              </p>
                            )}
                            {connector.connected && permissions[connector.name].granted && (
                              <p className="memory-dim">
                                {permissions[connector.name].granted_matches === false
                                  ? 'Google says it granted something different from what was asked: '
                                  : 'Google confirmed it granted: '}
                                <code>{permissions[connector.name].granted.join(' ')}</code>
                              </p>
                            )}
                            {connector.connected && permissions[connector.name].together && (
                              <p className="memory-dim">
                                Connected in one sign-in with the other Google cards. Disconnecting this one stops Diya using it; Google is told to forget the permission when the last Google card is disconnected.
                              </p>
                            )}
                            {connector.connected && permissions[connector.name].signed_out && (
                              <p className="memory-dim" role="alert">
                                Google signed Diya out of this account (it was removed at Google, or it ran out), so Diya cannot use it until you connect again. Nothing keeps asking Google in the meantime.
                              </p>
                            )}
                            {connector.connected && permissions[connector.name].since && (
                              <p className="memory-dim">Connected since {new Date(permissions[connector.name].since).toLocaleString()}.</p>
                            )}
                            {connector.connected && (
                              <p className="memory-dim">
                                {permissions[connector.name].last_used
                                  ? `Last used ${new Date(permissions[connector.name].last_used.at).toLocaleString()}: ${permissions[connector.name].last_used.what}${permissions[connector.name].last_used.ok ? '' : ' (did not work)'}.`
                                  : 'Not used yet.'}
                                {permissions[connector.name].last_action
                                  ? ` Last approved action: ${permissions[connector.name].last_action.summary} (${permissions[connector.name].last_action.status}, ${new Date(permissions[connector.name].last_action.at).toLocaleString()}).`
                                  : ''}
                              </p>
                            )}
                          </div>
                        )}
                        <p className="memory-person-tag">{connector.connected ? (permissions[connector.name] && permissions[connector.name].signed_out ? 'Signed out by Google' : 'Connected') : 'Not connected'}</p>
                        {connector.connected ? (
                          <div className="memory-actions">
                            {permissions[connector.name] && permissions[connector.name].signed_out && connector.auth_kind === 'oauth' && (
                              <button type="button" className="memory-btn memory-btn--primary" onClick={() => connectOAuth(connector)} disabled={isBusy}>
                                Connect again
                              </button>
                            )}
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
                        ) : connector.setup && !connector.setup.done ? (
                          <div className="connection-setup">
                            <p className="memory-dim">One-time setup first: {connector.label} needs an app of your own, made once in Google Cloud (free).</p>
                            <details open>
                              <summary>How to get these two (about ten minutes)</summary>
                              <ol>
                                {connector.setup.steps.map((step) => (
                                  <li key={step}>{step}</li>
                                ))}
                              </ol>
                            </details>
                            <form className="memory-edit" onSubmit={(e) => saveSetup(e, connector)}>
                              {connector.setup.fields.map((field) => (
                                <div key={field.name}>
                                  <label className="memory-sr" htmlFor={`setup-${connector.name}-${field.name}`}>
                                    {field.label}
                                  </label>
                                  <input
                                    id={`setup-${connector.name}-${field.name}`}
                                    className="memory-input"
                                    type={field.secret ? 'password' : 'text'}
                                    autoComplete="off"
                                    spellCheck={false}
                                    placeholder={field.label}
                                    value={(setupInputs[connector.name] || {})[field.name] || ''}
                                    onChange={(e) =>
                                      setSetupInputs((current) => ({ ...current, [connector.name]: { ...(current[connector.name] || {}), [field.name]: e.target.value } }))
                                    }
                                  />
                                </div>
                              ))}
                              <button
                                type="submit"
                                className="memory-btn memory-btn--primary"
                                disabled={isBusy || connector.setup.fields.some((field) => !((setupInputs[connector.name] || {})[field.name] || '').trim())}
                              >
                                Save
                              </button>
                            </form>
                          </div>
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
                            {connector.setup && connector.setup.from === 'file' && (
                              <button
                                type="button"
                                className="memory-btn"
                                onClick={() => clearSetup(connector)}
                                disabled={isBusy}
                                aria-label={`Use a different app for ${connector.label}`}
                              >
                                Use a different app
                              </button>
                            )}
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
  )
}
