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

function isDreaming(body) {
  return body && Array.isArray(body.runs) && typeof body.idle_last_day === 'number'
}

function isReview(body) {
  return body && Array.isArray(body.items) && body.reasons && typeof body.reasons === 'object'
}

// One scheduled pass of Dreaming, in words: what it read and what it did with it (docs/DREAMING_RECEIPTS_DESIGN.md).
function describeRun(run) {
  const did = []
  if (run.messages_read) did.push(`read ${run.messages_read} of your message${run.messages_read === 1 ? '' : 's'}`)
  if (run.staged) did.push(`found ${run.staged} possible fact${run.staged === 1 ? '' : 's'}`)
  if (run.remembered) did.push(`remembered ${run.remembered}`)
  if (run.replaced) did.push(`replaced ${run.replaced} as correction${run.replaced === 1 ? '' : 's'}`)
  if (run.asked) did.push(`left ${run.asked} to ask you about`)
  if (run.not_kept) did.push(`did not keep ${run.not_kept}`)
  if (run.held) did.push(`held ${run.held} (memory full)`)
  if (run.questions) did.push(`made ${run.questions} new question${run.questions === 1 ? '' : 's'} for you`)
  if (run.categories_sorted) did.push(`sorted ${run.categories_sorted} message${run.categories_sorted === 1 ? '' : 's'} into categories`)
  return did.length ? did.join(', ') : run.outcome
}

export default function ActivityPage() {
  // null = loading, false = couldn't be loaded, otherwise { entries, last_day }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [stale, setStale] = useState('') // the once-a-minute look failed: kept apart so it never wipes what is shown
  const [dreaming, setDreaming] = useState(null) // Dreaming's receipts, or null when they could not be read (the rest of the page does not depend on them)
  const [notHelpful, setNotHelpful] = useState(null) // the replies the person marked not helpful (docs/FEEDBACK_DESIGN.md), or null when they could not be read

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

  const loadDreaming = useCallback(async () => {
    try {
      const response = await fetch('/api/dreaming')
      const body = response.ok ? await readJson(response) : null
      if (isDreaming(body)) setDreaming(body)
    } catch {
      // the receipts are an extra: if they cannot be read, what is already shown stays
    }
  }, [])

  const loadNotHelpful = useCallback(async () => {
    try {
      const response = await fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'negatives' }) })
      const body = response.ok ? await readJson(response) : null
      if (isReview(body)) setNotHelpful(body)
    } catch {
      // an extra, like the receipts: if it cannot be read, what is already shown stays
    }
  }, [])

  useEffect(() => {
    load(true)
    loadDreaming()
    loadNotHelpful()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        load(false)
        loadDreaming()
        loadNotHelpful()
      }
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load, loadDreaming, loadNotHelpful])

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
            {dreaming && (
              <section aria-label="What Dreaming did">
                <h2>What Dreaming did</h2>
                <p className="memory-dim">
                  Dreaming is the quiet pass that reads what you said since last time. One line for each pass that did something; a pass that found nothing is only counted ({dreaming.idle_last_day} in the
                  last 24 hours). {dreaming.last_run ? `The last pass started ${new Date(dreaming.last_run.started_at).toLocaleString()}.` : 'It has not run since this record began.'}
                </p>
                {dreaming.runs.length === 0 ? (
                  <p className="memory-dim">Nothing yet.</p>
                ) : (
                  <ul className="memory-list activity-list">
                    {dreaming.runs.map((run) => (
                      <li key={run.id} className="memory-fact activity-entry" data-status={run.errors.length ? 'error' : 'ok'}>
                        <p className="memory-text">
                          {describeRun(run)}
                          {run.errors.length > 0 && <span className="activity-status activity-status--error">went wrong</span>}
                        </p>
                        <p className="memory-dim">
                          {new Date(run.started_at).toLocaleString()} · pass {run.id}
                          {run.first_message_id != null ? ` · messages ${run.first_message_id} to ${run.last_message_id}` : ''} · {run.duration_ms < 1000 ? `${run.duration_ms} ms` : `${(run.duration_ms / 1000).toFixed(1)} s`}
                        </p>
                        {run.errors.map((error) => (
                          <p key={error} className="memory-dim">
                            {error}
                          </p>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
            {notHelpful && (
              <section aria-label="Replies you marked not helpful">
                <h2>Replies you marked not helpful</h2>
                <p className="memory-dim">
                  The ones you marked &ldquo;Not helpful&rdquo; under a reply in the chat, newest first, with the reason and note you gave. This is for you to read back: it is never shown to Diya, and nothing
                  here changes it.
                </p>
                {notHelpful.items.length === 0 ? (
                  <p className="memory-dim">None yet. When a reply is not what you wanted, press &ldquo;Not helpful&rdquo; under it and say why; it shows here.</p>
                ) : (
                  <ul className="memory-list activity-list">
                    {notHelpful.items.map((item) => (
                      <li key={item.message_id} className="memory-fact activity-entry">
                        <p className="memory-text">You said: {item.message}</p>
                        <p className="memory-dim">{item.reply === null ? 'Diya had not answered yet.' : `Diya said: ${item.reply}`}</p>
                        <p className="memory-dim">
                          {new Date(item.at).toLocaleString()} · {item.category ? notHelpful.reasons[item.category] || item.category : 'no reason given'}
                        </p>
                        {item.note && <p className="memory-dim">Your note: {item.note}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </main>
  )
}
