'use client'

import { useCallback, useEffect, useState } from 'react'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// Your to-do list, kept inside Diya (docs/TASKS_DESIGN.md, unit T2): nothing here goes to another service. Everything
// shown comes from the API already made safe to show (control and direction-changing characters arrive as visible
// escapes), and React renders it as text, never as markup. The page looks again once a minute while it is open, so a task
// Diya adds from the chat in another tab appears without a reload.

const REFRESH_MS = 60_000

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function finishedAt(stamp) {
  const date = new Date(stamp)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function isList(body) {
  return body && Array.isArray(body.tasks) && Array.isArray(body.done) && body.counts
}

export default function TasksPage() {
  // null = loading, false = couldn't be loaded, otherwise { tasks, done, counts }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // '', 'add', or a task id
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('') // the result of something the person just did, and only that
  const [refreshProblem, setRefreshProblem] = useState('') // the once-a-minute look failed; kept apart so it never stands in for, or wipes, an action's result
  const [text, setText] = useState('')
  const [when, setWhen] = useState('')

  const load = useCallback(async (first, quiet = false) => {
    let status
    try {
      const response = await fetch('/api/tasks') // same-origin: app/api/tasks forwards it, with the token, from the server
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

  // Run a request the person asked for. On success say what happened (and use the list the API sent back); on a
  // refusal say why, in the API's own words when it gave them, and that nothing was changed.
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
    if (isList(body)) setData(body)
    else await load(false)
    setBusy('')
    return true
  }

  function addTask(event) {
    event.preventDefault()
    settle(
      () =>
        fetch('/api/tasks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, when }),
        }),
      'add',
      ({ task }) => {
        if (task.due_text) return `Added. Due ${task.due_text}.`
        if (task.said) return `Added. “${task.said}” was not read as a date, so it is kept as you wrote it.`
        return 'Added.'
      },
    ).then((ok) => {
      if (ok) {
        setText('')
        setWhen('')
      }
    })
  }

  const markDone = (task) => settle(() => fetch(`/api/tasks/${task.id}/done`, { method: 'POST' }), String(task.id), () => 'Marked done.')
  const putBack = (task) => settle(() => fetch(`/api/tasks/${task.id}/reopen`, { method: 'POST' }), String(task.id), () => 'Put back on the list.')

  const tasks = data ? data.tasks : []
  const done = data ? data.done : []

  return (
    <main className="history-page memory-page reminders-page tasks-page">
        <div className="history-inner">
          <h1>Tasks</h1>
          {data === null ? (
            <div role="status" aria-label="Loading your tasks">
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
              <div className="thread-skeleton" />
            </div>
          ) : data === false ? (
            <div className="empty-state">
              <img src="/diya-flame.svg" alt="" className="empty-mark" />
              <h2>Couldn&rsquo;t load your tasks</h2>
              <p>{problem}</p>
              <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
                Try again
              </button>
            </div>
          ) : (
            <>
              <p className="memory-lede">
                Your to-do list. It is kept inside Diya and goes nowhere else. Say &ldquo;add a task to&hellip;&rdquo; in the chat, or add
                one here, and tick it off when it is done.
              </p>
              <form className="memory-add reminder-add" onSubmit={addTask}>
                <label className="memory-sr" htmlFor="task-text">
                  What the task is
                </label>
                <input
                  id="task-text"
                  className="memory-input"
                  placeholder="Add a task…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <label className="memory-sr" htmlFor="task-when">
                  When it is due (optional, for example Friday, or tomorrow at 5pm)
                </label>
                <input
                  id="task-when"
                  className="memory-input reminder-when"
                  placeholder="Due, e.g. Friday (optional)"
                  value={when}
                  onChange={(e) => setWhen(e.target.value)}
                />
                <button type="submit" className="memory-btn memory-btn--primary" disabled={busy === 'add' || !text.trim()}>
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

              <section aria-labelledby="tasks-open">
                <h2 id="tasks-open">
                  To do ({tasks.length}
                  {data.counts.overdue > 0 ? `, ${data.counts.overdue} overdue` : ''})
                </h2>
                {tasks.length === 0 ? (
                  <p className="memory-dim">Nothing to do. Add a task above, or ask Diya to in the chat.</p>
                ) : (
                  <ul className="memory-list">
                    {tasks.map((task) => (
                      <li key={task.id} className="memory-fact task" data-state={task.overdue ? 'overdue' : 'open'}>
                        <p className="memory-text">{task.content}</p>
                        <p className="memory-dim reminder-when-line">
                          {task.overdue && <span className="task-overdue">Overdue · </span>}
                          {task.due_text
                            ? `Due ${task.due_text}`
                            : task.said
                              ? `You said “${task.said}”, which was not read as a date.`
                              : 'No due date.'}
                          {task.from_chat ? ' · Added from the chat' : ''}
                        </p>
                        <div className="memory-actions">
                          <button
                            type="button"
                            className="memory-btn memory-btn--primary"
                            onClick={() => markDone(task)}
                            disabled={busy === String(task.id)}
                            aria-label={`Done: ${task.content}`}
                          >
                            Done
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              <details className="tasks-done">
                <summary>Done ({data.counts.done})</summary>
                {done.length === 0 ? (
                  <p className="memory-dim">Nothing is done yet.</p>
                ) : (
                  <>
                    {data.counts.done > done.length && (
                      <p className="memory-dim">
                        Showing the latest {done.length} of {data.counts.done}.
                      </p>
                    )}
                    <ul className="memory-list">
                      {done.map((task) => (
                        <li key={task.id} className="memory-fact task" data-state="done">
                          <p className="memory-text">{task.content}</p>
                          <p className="memory-dim reminder-when-line">
                            {task.completed && finishedAt(task.completed) ? `Finished ${finishedAt(task.completed)}` : 'Finished'}
                          </p>
                          <div className="memory-actions">
                            <button
                              type="button"
                              className="memory-btn"
                              onClick={() => putBack(task)}
                              disabled={busy === String(task.id)}
                              aria-label={`Put back: ${task.content}`}
                            >
                              Put back
                            </button>
                          </div>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </details>
            </>
          )}
        </div>
      </main>
  )
}
