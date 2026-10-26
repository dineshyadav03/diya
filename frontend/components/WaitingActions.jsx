'use client'

import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'
import { describeActionFailure } from '../lib/api-failure.mjs'
import { statusWords } from '../lib/actions-format.mjs'

// What Diya has lined up and is waiting for you to approve, shown under the chat so that one press is enough (the same approval as on the
// Actions page: it sends the hash of exactly what was shown, and the API refuses it if anything changed). Only a proposal that Diya made
// from your own message is decided here; one made after she read something that is not yours (a web page, a note, an email) is only
// pointed to, so that its details are checked on the Actions page first. After a decision the result is told in words, with the link
// to what was made when Google gave one.

const MAX_RISK_HERE = 2 // risk levels above this are decided on the Actions page, where the whole description is shown

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

// The addresses in a result that are Google's own are shown as a link; anything else stays plain text.
function Result({ text }) {
  const parts = String(text || '').split(/(\s+)/)
  return (
    <>
      {parts.map((part, index) => {
        let host = ''
        try {
          host = /^https:\/\//.test(part) ? new URL(part).hostname : ''
        } catch {
          host = ''
        }
        return host === 'google.com' || host.endsWith('.google.com') ? (
          <a key={index} href={part} target="_blank" rel="noopener noreferrer">
            Open it
          </a>
        ) : (
          <span key={index}>{part}</span>
        )
      })}
    </>
  )
}

export default function WaitingActions({ refreshKey }) {
  const [pending, setPending] = useState([])
  const [busy, setBusy] = useState(0) // 0, or the id of the action being decided
  const [outcome, setOutcome] = useState(null) // { ok, text } of the last decision made here
  const [problem, setProblem] = useState('')

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/actions')
      const body = response.ok ? await readJson(response) : null
      if (body && Array.isArray(body.pending)) setPending(body.pending)
    } catch {
      // an extra under the chat: if it cannot be read, nothing is shown, and the Actions page still has everything
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, 20_000)
    return () => clearInterval(timer)
  }, [load, refreshKey])

  async function decide(action, what) {
    setBusy(action.id)
    setProblem('')
    setOutcome(null)
    let response
    try {
      response =
        what === 'approve'
          ? await fetch(`/api/actions/${action.id}/approve`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ args_hash: action.args_hash }),
            })
          : await fetch(`/api/actions/${action.id}/reject`, { method: 'POST' })
    } catch {
      setProblem(describeActionFailure())
      setBusy(0)
      return
    }
    const body = await readJson(response)
    if (!response.ok || !body || !body.action) {
      setProblem(describeActionFailure(response.ok ? undefined : response.status, body?.detail))
    } else if (what === 'reject') {
      setOutcome({ ok: true, text: `Turned down: ${body.action.summary}. It will not be done.` })
    } else if (body.action.status === 'succeeded') {
      setOutcome({ ok: true, text: `Done: ${body.action.summary}.${body.action.result ? ` ${body.action.result}` : ''}` })
    } else if (body.action.status === 'unknown') {
      setOutcome({ ok: false, text: `Not sure it was done: ${body.action.summary}. ${body.action.result || 'What happened is not known.'} Look at the Actions page.` })
    } else {
      setOutcome({ ok: false, text: `Not done: ${body.action.summary}. ${body.action.result || statusWords(body.action.status)}` })
    }
    await load()
    window.dispatchEvent(new Event('diya-actions-changed')) // the count in the menu badge is read again at once, not within the minute
    setBusy(0)
  }

  if (pending.length === 0 && !outcome && !problem) return null

  return (
    <section className="waiting-strip" aria-label="Waiting for your OK">
      {outcome && (
        <p className={outcome.ok ? 'waiting-outcome' : 'waiting-outcome waiting-outcome--bad'} role="status">
          <Result text={outcome.text} />
        </p>
      )}
      {problem && (
        <p className="waiting-outcome waiting-outcome--bad" role="alert">
          {problem}
        </p>
      )}
      {pending.map((action) => {
        const here = !action.tainted && (!action.preview || action.preview.tier <= MAX_RISK_HERE)
        return (
          <div key={action.id} className="waiting-card">
            <p className="waiting-text">{action.summary}</p>
            {here ? (
              <div className="waiting-buttons">
                <button type="button" className="waiting-approve" onClick={() => decide(action, 'approve')} disabled={busy === action.id} aria-label={`Approve: ${action.summary}`}>
                  {busy === action.id ? 'Doing it…' : 'Approve'}
                </button>
                <button type="button" className="waiting-reject" onClick={() => decide(action, 'reject')} disabled={busy === action.id} aria-label={`Not now: ${action.summary}`}>
                  Not now
                </button>
              </div>
            ) : (
              <p className="waiting-note">
                Diya read something that is not yours before proposing this, or it needs a closer look. <Link href="/actions">Check it on the Actions page</Link>.
              </p>
            )}
          </div>
        )
      })}
    </section>
  )
}
