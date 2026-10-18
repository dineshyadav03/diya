'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeLoadFailure } from '../../lib/api-failure.mjs'

// Is Diya well? (docs/HEALTH_DESIGN.md) One line per part, each saying what was actually looked at. Everything shown comes from the API already made safe to show, and React renders it as text, never as
// markup. The page looks again once a minute while it is open.

const REFRESH_MS = 60_000

const WORDS = { ok: 'working', warn: 'needs a look', bad: 'not working', off: 'switched off' }
const OVERALL = {
  ok: 'Everything Diya checked is working.',
  warn: 'Diya is working, but something needs a look.',
  bad: 'Something is not working.',
}

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isData(body) {
  return body && typeof body.overall === 'string' && Array.isArray(body.items)
}

export default function StatusPage() {
  // null = loading, false = couldn't be loaded, otherwise { overall, items }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [stale, setStale] = useState('') // the once-a-minute look failed: kept apart so it never wipes what is shown

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/health') // same-origin: app/api/health forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (isData(body)) {
        setData(body)
        setProblem('')
        setStale('')
        return
      }
    } catch {
      status = undefined
    }
    if (first) {
      setProblem(describeLoadFailure(status))
      setData(false)
    } else {
      setStale(describeLoadFailure(status))
    }
  }, [])

  useEffect(() => {
    load(true)
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load(false)
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  return (
    <main className="history-page memory-page status-page">
      <div className="history-inner">
        <h1>Status</h1>
        {data === null ? (
          <div role="status" aria-label="Checking on Diya">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : data === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t check on Diya</h2>
            <p>{problem}</p>
            <button type="button" className="cta" onClick={() => load(true)}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <p className="memory-lede" role="status">
              {OVERALL[data.overall] || 'Diya looked at each part below.'} Each line says what was actually looked at just now. What she did is on the <Link href="/activity">Activity</Link> page.
            </p>
            {stale && (
              <p className="memory-dim reminders-stale" role="status">
                Couldn&rsquo;t refresh just now, so this may be out of date. {stale}
              </p>
            )}
            <ul className="memory-list status-list">
              {data.items.map((item) => (
                <li key={item.name} className="memory-fact status-item" data-status={item.status}>
                  <p className="memory-text">
                    {item.label} <span className={`status-state status-state--${item.status}`}>{WORDS[item.status] || item.status}</span>
                  </p>
                  <p className="memory-dim">{item.text}</p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </main>
  )
}
