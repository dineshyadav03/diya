'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeLoadFailure } from '../../lib/api-failure.mjs'

// The day at a glance (docs/SCHEDULE_DESIGN.md, D8 and unit R5). Nothing here is written by a model: it is the owner's own
// reminders, tasks and repeating reminders, sorted by the clock, with one sentence made from the counts. Everything shown comes
// from the API already made safe to show (control and direction-changing characters arrive as visible escapes), and React renders
// it as text, never as markup. It only shows: ticking off, pushing back and stopping are done on the page each thing lives on.
// The page looks again once a minute while it is open, so a reminder that comes due moves up without a reload.

const REFRESH_MS = 60_000

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isBrief(body) {
  return (
    body &&
    typeof body.headline === 'string' &&
    typeof body.date === 'string' &&
    Array.isArray(body.due_now) &&
    Array.isArray(body.later_today) &&
    Array.isArray(body.tasks_overdue) &&
    Array.isArray(body.tasks_today) &&
    Array.isArray(body.repeating) &&
    body.counts
  )
}

export default function TodayPage() {
  // null = loading, false = couldn't be loaded, otherwise the brief.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [refreshProblem, setRefreshProblem] = useState('') // the once-a-minute look failed; the brief on screen may be out of date

  const load = useCallback(async (first, quiet = false) => {
    let status
    try {
      const response = await fetch('/api/today') // same-origin: app/api/today forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (isBrief(body)) {
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
    } else {
      setRefreshProblem(describeLoadFailure(status))
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

  const counts = data ? data.counts : null
  const nothingDated = data && !data.due_now.length && !data.later_today.length && !data.tasks_overdue.length && !data.tasks_today.length

  return (
    <main className="history-page memory-page reminders-page today-page">
        <div className="history-inner">
          <h1>Today</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your day">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your day</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-dim today-date">{data.date}</p>
              <p className="today-headline" role="status">
                {data.headline}
              </p>
              <p className="memory-lede">
                Your own reminders, tasks and repeating reminders for today, in time order. Nothing here is written by Diya&rsquo;s model.
                To tick something off or push it back, open the page it lives on.
              </p>
              {refreshProblem && (
                <p className="memory-dim reminders-stale" role="status">
                  Couldn&rsquo;t refresh just now, so this may be out of date. {refreshProblem}
                </p>
              )}

              <section aria-labelledby="today-due-now">
                <h2 id="today-due-now">
                  Due now ({data.due_now.length}) <Link href="/reminders">Open Reminders</Link>
                </h2>
                {data.due_now.length === 0 ? (
                  <p className="memory-dim">Nothing is due right now.</p>
                ) : (
                  <ul className="memory-list">
                    {data.due_now.map((reminder) => (
                      <li key={reminder.id} className="memory-fact reminder" data-state="due">
                        <p className="memory-text">{reminder.content}</p>
                        <p className="memory-dim reminder-when-line">
                          {reminder.due_text}
                          {reminder.told ? ' · You were told' : ''}
                          {reminder.repeats ? ' · Repeats' : ''}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-labelledby="today-later">
                <h2 id="today-later">Later today ({data.later_today.length})</h2>
                {data.later_today.length === 0 ? (
                  <p className="memory-dim">Nothing else is due today.</p>
                ) : (
                  <ul className="memory-list">
                    {data.later_today.map((reminder) => (
                      <li key={reminder.id} className="memory-fact reminder" data-state="upcoming">
                        <p className="memory-text">{reminder.content}</p>
                        <p className="memory-dim reminder-when-line">
                          {reminder.due_text}
                          {reminder.repeats ? ' · Repeats' : ''}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-labelledby="today-tasks">
                <h2 id="today-tasks">
                  Tasks ({data.tasks_overdue.length + data.tasks_today.length}) <Link href="/tasks">Open Tasks</Link>
                </h2>
                {data.tasks_overdue.length + data.tasks_today.length === 0 ? (
                  <p className="memory-dim">No task is overdue or due today.</p>
                ) : (
                  <ul className="memory-list">
                    {[...data.tasks_overdue, ...data.tasks_today].map((task) => (
                      <li key={task.id} className="memory-fact task" data-state={task.overdue ? 'overdue' : 'open'}>
                        <p className="memory-text">{task.content}</p>
                        <p className="memory-dim reminder-when-line">
                          {task.overdue && <span className="task-overdue">Overdue · </span>}
                          {task.due_text ? `Due ${task.due_text}` : ''}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <section aria-labelledby="today-repeating">
                <h2 id="today-repeating">
                  Coming from repeating reminders ({counts.repeating}) <Link href="/scheduled">Open Scheduled</Link>
                </h2>
                {data.repeating.length === 0 ? (
                  <p className="memory-dim">No repeating reminder is running.</p>
                ) : (
                  <>
                    <ul className="memory-list">
                      {data.repeating.map((series) => (
                        <li key={series.id} className="memory-fact scheduled" data-state="active">
                          <p className="memory-text">{series.content}</p>
                          <p className="memory-dim reminder-when-line">
                            {series.today ? <span className="today-mark">Today · </span> : ''}
                            {series.rule} · Next: {series.next}
                          </p>
                        </li>
                      ))}
                    </ul>
                    {counts.repeating > data.repeating.length && (
                      <p className="memory-dim">
                        Showing the soonest {data.repeating.length} of {counts.repeating}.
                      </p>
                    )}
                  </>
                )}
              </section>

              {(counts.no_time > 0 || counts.tasks_undated > 0) && (
                <p className="memory-dim today-undated">
                  Not part of the day, because they have no time or date:{' '}
                  {[
                    counts.no_time > 0 && `${counts.no_time} reminder${counts.no_time === 1 ? '' : 's'}`,
                    counts.tasks_undated > 0 && `${counts.tasks_undated} task${counts.tasks_undated === 1 ? '' : 's'}`,
                  ]
                    .filter(Boolean)
                    .join(' and ')}
                  .
                </p>
              )}
              {nothingDated && counts.repeating === 0 && counts.no_time === 0 && counts.tasks_undated === 0 && (
                <p className="memory-dim">Nothing is set up yet. Ask Diya in the chat to remind you of something, or add a task.</p>
              )}
            </>
          )}
        </div>
      </main>
  )
}
