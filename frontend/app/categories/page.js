'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// The categories Diya sorts what you say into (docs/ONE_CHAT_DESIGN.md): rename, add and merge them, look inside one (your messages from every chat),
// sort the messages from before sorting existed, and answer the new categories Diya suggests. Everything shown comes from the API already made safe to
// show, and React renders it as text, never as markup. While a background job runs (sorting the earlier chats, looking for a suggestion) the page looks
// again every second and a half and says how far it is.

const POLL_MS = 1500

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isData(body) {
  return body && Array.isArray(body.categories) && Array.isArray(body.suggestions) && body.job && typeof body.job === 'object'
}

const SORTED_BY = { person: 'moved by you', code: 'sorted by Diya', model: 'sorted by Diya', continued: 'sorted by Diya' }

export default function CategoriesPage() {
  // null = loading, false = couldn't be loaded, otherwise { categories, suggestions, job, unsorted, tags }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('') // the result of something the person just did, and only that
  const [name, setName] = useState('') // a new category being typed
  const [renaming, setRenaming] = useState(null) // { id, draft }
  const [merging, setMerging] = useState(null) // { id, into } : the category being folded into another, and which
  const [inside, setInside] = useState(null) // { id, messages } : the category being looked into; messages is null while they are fetched
  const [unticked, setUnticked] = useState({}) // suggestion id -> the message ids the person took the tick off

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/categories') // same-origin: app/api/categories forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (isData(body)) {
        setData(body)
        setProblem('')
        return body
      }
    } catch {
      status = undefined
    }
    if (first) {
      setProblem(describeLoadFailure(status))
      setData(false)
    }
    return null
  }, [])

  useEffect(() => {
    load(true)
  }, [load])

  const running = data && data.job.running
  useEffect(() => {
    if (!running) return undefined
    const timer = setInterval(() => load(false), POLL_MS)
    return () => clearInterval(timer)
  }, [running, load])

  // One call for every change. What the API answers is the new state of the page, so nothing is guessed on this side.
  async function act(body, { keepInside = true } = {}) {
    setBusy(true)
    setError('')
    let response
    try {
      response = await fetch('/api/categories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    } catch {
      setError(describeActionFailure())
      setBusy(false)
      return null
    }
    const answer = await readJson(response)
    setBusy(false)
    if (!response.ok) {
      setError(describeActionFailure(response.status, answer?.detail))
      return null
    }
    if (isData(answer)) {
      setData(answer)
      if (!keepInside) setInside(null)
    }
    return answer
  }

  async function add(event) {
    event.preventDefault()
    if (await act({ action: 'add', name })) setName('')
  }

  async function rename(event) {
    event.preventDefault()
    if (await act({ action: 'rename', category_id: renaming.id, name: renaming.draft })) setRenaming(null)
  }

  async function merge(event) {
    event.preventDefault()
    if (await act({ action: 'merge', category_id: merging.id, into_id: Number(merging.into) }, { keepInside: false })) setMerging(null)
  }

  async function lookInside(category) {
    if (inside && inside.id === category.id) {
      setInside(null)
      return
    }
    setInside({ id: category.id, messages: null })
    setError('')
    let response
    try {
      response = await fetch('/api/categories', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'browse', category_id: category.id, limit: 30 }) })
    } catch {
      setInside(null)
      setError(describeActionFailure())
      return
    }
    const answer = await readJson(response)
    if (!response.ok || !answer || !Array.isArray(answer.messages)) {
      setInside(null)
      setError(describeActionFailure(response.ok ? undefined : response.status, answer?.detail))
      return
    }
    setInside({ id: category.id, messages: answer.messages })
  }

  function answerSuggestion(suggestion, accept) {
    const off = unticked[suggestion.id] || []
    const message_ids = suggestion.messages.map((m) => m.id).filter((id) => !off.includes(id))
    return act({ action: 'answer_suggestion', suggestion_id: suggestion.id, accept, message_ids }, { keepInside: false })
  }

  function toggle(suggestion, id) {
    setUnticked((shown) => {
      const off = shown[suggestion.id] || []
      return { ...shown, [suggestion.id]: off.includes(id) ? off.filter((x) => x !== id) : [...off, id] }
    })
  }

  const job = data ? data.job : null

  return (
    <main className="history-page memory-page categories-page">
      <div className="history-inner">
        <h1>Categories</h1>
        {data === null ? (
          <div role="status" aria-label="Loading your categories">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : data === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t load your categories</h2>
            <p>{problem}</p>
            <button type="button" className="cta" onClick={() => load(true)}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <p className="memory-lede">
              Diya puts each thing you say in exactly one category, a few seconds after she answers, so you can look at your <Link href="/">chat</Link> by category. Nothing here changes what she
              says or remembers. Rename, add or merge them to suit you; a category you merge away is not lost, its messages move to the one you pick.
            </p>

            {job.running && (
              <p className="memory-notice" role="status">
                {job.kind === 'sort_earlier'
                  ? `Sorting your earlier chats… ${job.done} of ${job.total || '?'}`
                  : job.note || 'Looking through your messages for something none of the categories covers…'}
              </p>
            )}
            {!job.running && job.note && (
              <p className="memory-dim" role="status">
                {job.note}
              </p>
            )}
            {error && (
              <p className="memory-error" role="alert">
                {error}
              </p>
            )}

            {data.suggestions.map((suggestion) => (
              <section key={suggestion.id} className="question-card category-suggestion" aria-label={`A new category Diya suggests: ${suggestion.name}`}>
                <p className="question-text">
                  Diya suggests a new category: <strong>{suggestion.name}</strong>. These messages look like they belong in it. Take the tick off any that don&rsquo;t.
                </p>
                <ul className="category-suggestion-list">
                  {suggestion.messages.map((m) => (
                    <li key={m.id}>
                      <label>
                        <input type="checkbox" checked={!(unticked[suggestion.id] || []).includes(m.id)} onChange={() => toggle(suggestion, m.id)} /> {m.text}
                      </label>
                    </li>
                  ))}
                </ul>
                <div className="question-actions">
                  <button type="button" className="cta small" disabled={busy} onClick={() => answerSuggestion(suggestion, true)}>
                    Make the category
                  </button>
                  <button type="button" className="quiet-btn" disabled={busy} onClick={() => answerSuggestion(suggestion, false)}>
                    No thanks
                  </button>
                </div>
              </section>
            ))}

            <div className="memory-actions category-jobs">
              <button type="button" className="memory-btn" disabled={busy || job.running || data.unsorted === 0} onClick={() => act({ action: 'sort_earlier' })}>
                {data.unsorted === 0 ? 'Every message is in a category' : `Sort my earlier chats (${data.unsorted} message${data.unsorted === 1 ? '' : 's'} in none)`}
              </button>
              <button type="button" className="memory-btn" disabled={busy || job.running || data.suggestions.length > 0} onClick={() => act({ action: 'suggest' })}>
                Look for a new category
              </button>
            </div>

            <form className="memory-add" onSubmit={add}>
              <label className="memory-sr" htmlFor="category-name">
                Name for a new category
              </label>
              <input id="category-name" className="memory-input" placeholder="A new category, e.g. School" value={name} maxLength={30} onChange={(e) => setName(e.target.value)} />
              <button type="submit" className="memory-btn memory-btn--primary" disabled={busy || !name.trim()}>
                Add
              </button>
            </form>

            <section aria-labelledby="category-list">
              <h2 id="category-list">Yours ({data.categories.length})</h2>
              <ul className="memory-list">
                {data.categories.map((category) => (
                  <li key={category.id} className="memory-fact category">
                    {renaming && renaming.id === category.id ? (
                      <form className="memory-add" onSubmit={rename}>
                        <label className="memory-sr" htmlFor={`rename-${category.id}`}>
                          New name for {category.name}
                        </label>
                        <input id={`rename-${category.id}`} className="memory-input" value={renaming.draft} maxLength={30} autoFocus onChange={(e) => setRenaming({ id: category.id, draft: e.target.value })} />
                        <button type="submit" className="memory-btn memory-btn--primary" disabled={busy || !renaming.draft.trim()}>
                          Save
                        </button>
                        <button type="button" className="memory-btn" onClick={() => setRenaming(null)}>
                          Cancel
                        </button>
                      </form>
                    ) : (
                      <p className="memory-text">
                        {category.name} <span className="memory-dim">· {category.count} message{category.count === 1 ? '' : 's'}</span>
                      </p>
                    )}
                    {category.meaning && !(renaming && renaming.id === category.id) && <p className="memory-dim">{category.meaning}</p>}
                    <div className="memory-actions">
                      <button type="button" className="memory-btn" aria-expanded={inside !== null && inside.id === category.id} onClick={() => lookInside(category)} aria-label={`Look inside: ${category.name}`}>
                        {inside && inside.id === category.id ? 'Hide' : 'Look inside'}
                      </button>
                      <button
                        type="button"
                        className="memory-btn"
                        disabled={busy}
                        onClick={() => {
                          setMerging(null)
                          setRenaming({ id: category.id, draft: category.name })
                        }}
                        aria-label={`Rename: ${category.name}`}
                      >
                        Rename
                      </button>
                      <button
                        type="button"
                        className="memory-btn"
                        disabled={busy || data.categories.length < 2}
                        onClick={() => {
                          setRenaming(null)
                          setMerging({ id: category.id, into: String((data.categories.find((c) => c.id !== category.id) || {}).id || '') })
                        }}
                        aria-label={`Merge into another: ${category.name}`}
                      >
                        Merge into…
                      </button>
                    </div>
                    {merging && merging.id === category.id && (
                      <form className="memory-add category-merge" onSubmit={merge}>
                        <label htmlFor={`merge-${category.id}`}>
                          Move all of {category.name}&rsquo;s messages into
                        </label>
                        <select id={`merge-${category.id}`} className="memory-input" value={merging.into} onChange={(e) => setMerging({ id: category.id, into: e.target.value })}>
                          {data.categories
                            .filter((c) => c.id !== category.id)
                            .map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                        </select>
                        <button type="submit" className="memory-btn memory-btn--danger" disabled={busy || !merging.into}>
                          Merge
                        </button>
                        <button type="button" className="memory-btn" onClick={() => setMerging(null)}>
                          Cancel
                        </button>
                      </form>
                    )}
                    {inside && inside.id === category.id && (
                      <div className="category-inside">
                        {inside.messages === null ? (
                          <p className="memory-dim" role="status">
                            Looking…
                          </p>
                        ) : inside.messages.length === 0 ? (
                          <p className="memory-dim">Nothing in it yet.</p>
                        ) : (
                          <ul className="category-messages">
                            {inside.messages.map((m) => (
                              <li key={m.id}>
                                <Link href={`/?thread=${m.thread_id}`}>{m.text}</Link>
                                <span className="memory-dim">
                                  {' '}
                                  · {m.at.slice(0, 16).replace('T', ' ')} · {SORTED_BY[m.source] || 'sorted by Diya'}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </main>
  )
}
