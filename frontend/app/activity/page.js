'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeLoadFailure } from '../../lib/api-failure.mjs'

// What Diya did with a tool or a connector (docs/ACTIVITY_JOURNAL_DESIGN.md): one row each, newest first, never changeable from here or anywhere. Everything shown comes from the API already made
// safe to show, and React renders it as text, never as markup. The page looks again once a minute while it is open.

const REFRESH_MS = 60_000

const WHAT = {
  web_search: 'searched the web',
  search_notes: 'looked in your notes',
  get_weather: 'checked the weather',
  read_mail: 'looked through your mail',
  mail_write_refused: 'refused to write mail',
  study_repo: 'studied a repository',
  add_reminder: 'saved a reminder',
  list_reminders: 'checked your reminders',
  add_task: 'added a task',
  list_tasks: 'checked your tasks',
  list_files: 'listed files',
  list_calendar_events: 'looked at your calendar',
}

function describe(entry) {
  if (WHAT[entry.tool]) return WHAT[entry.tool]
  if (entry.tool.startsWith('mcp_')) return `used a connected program (${entry.tool.split('_')[1] || 'MCP'})`
  if (entry.tool.startsWith('propose_')) return 'proposed an action for you to approve'
  return `used ${entry.tool}`
}

const OUTCOME = { ok: 'worked', error: 'did not work', refused: 'refused' }

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isData(body) {
  return body && Array.isArray(body.entries) && body.last_day && typeof body.last_day === 'object'
}

export default function ActivityPage() {
  // null = loading, false = couldn't be loaded, otherwise { entries, last_day }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [stale, setStale] = useState('') // the once-a-minute look failed: kept apart so it never wipes what is shown

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/journal') // same-origin: app/api/journal forwards it, with the token, from the server
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
    <main className="history-page memory-page activity-page">
      <div className="history-inner">
        <h1>Activity</h1>
        {data === null ? (
          <div role="status" aria-label="Loading what Diya did">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : data === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t load the activity</h2>
            <p>{problem}</p>
            <button type="button" className="cta" onClick={() => load(true)}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <p className="memory-lede">
              Everything Diya did with a tool or an account, one line each, newest first. It is a record: nothing here can be changed or deleted, by you, by Diya or by anything in a message. It
              keeps what was asked and how it came out, never the mail, page or answer itself. What she is waiting for you to approve is on the <Link href="/actions">Actions</Link> page.
            </p>
            <p className="memory-dim" role="status">
              Last 24 hours: {data.last_day.ok} worked · {data.last_day.error} did not work · {data.last_day.refused} refused
            </p>
            {stale && (
              <p className="memory-dim reminders-stale" role="status">
                Couldn&rsquo;t refresh just now, so this may be out of date. {stale}
              </p>
            )}
            {data.entries.length === 0 ? (
              <p className="memory-dim">Nothing yet. When Diya searches, reads your notes or mail, or uses a tool, it shows here.</p>
            ) : (
              <ul className="memory-list activity-list">
                {data.entries.map((entry) => (
                  <li key={entry.id} className="memory-fact activity-entry" data-status={entry.status}>
                    <p className="memory-text">
                      {describe(entry)} <span className={`activity-status activity-status--${entry.status}`}>{OUTCOME[entry.status] || entry.status}</span>
                    </p>
                    <p className="memory-dim">
                      {new Date(entry.at).toLocaleString()} · {entry.kind === 'flow' ? 'because of what you said' : 'chosen by the model'}
                      {entry.origin === 'unattended' ? ' · while you were away' : ''}
                      {entry.duration_ms != null ? ` · ${entry.duration_ms < 1000 ? `${entry.duration_ms} ms` : `${(entry.duration_ms / 1000).toFixed(1)} s`}` : ''}
                    </p>
                    {entry.args_preview && <p className="memory-dim activity-args">{entry.args_preview}</p>}
                    {entry.note && <p className="memory-dim">{entry.note}</p>}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </main>
  )
}
