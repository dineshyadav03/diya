'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

const SEARCH_DELAY_MS = 300
const MIN_SEARCH = 2

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

export default function HistoryPage() {
  // null = loading, false = the list couldn't be loaded, [] = no chats yet.
  const [threads, setThreads] = useState(null)
  // Why it couldn't be loaded (shown when `threads` is false): nothing answered, or the API refused
  // the UI's access token, or it reported an error -- each says something different to do.
  const [problem, setProblem] = useState('')
  const [query, setQuery] = useState('')
  const [found, setFound] = useState(null) // null = not searching (or still looking), otherwise the chats with a message that has the words
  const [searchProblem, setSearchProblem] = useState('')
  const [editing, setEditing] = useState(null) // the chat being renamed
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('') // what went wrong with a rename, and only that

  const load = useCallback(() => {
    function couldNotLoad(status) {
      setProblem(describeLoadFailure(status))
      setThreads(false)
    }
    return fetch('/api/threads') // same-origin: app/api/threads forwards it, with the access token, from the server
      .then((r) => {
        if (!r.ok) return couldNotLoad(r.status)
        return r.json().then((data) => (Array.isArray(data.threads) ? setThreads(data.threads) : couldNotLoad(r.status)))
      })
      .catch(() => couldNotLoad()) // no answer at all, or a reply that isn't JSON
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Looking inside the chats, a moment after the person stops typing. A newer search makes an older answer not matter.
  useEffect(() => {
    const words = query.trim()
    setSearchProblem('')
    if (words.length < MIN_SEARCH) {
      setFound(null)
      return undefined
    }
    let current = true
    const timer = setTimeout(() => {
      fetch(`/api/threads/search?q=${encodeURIComponent(words)}`)
        .then(async (r) => {
          const body = r.ok ? await readJson(r) : null
          if (!current) return
          if (body && Array.isArray(body.threads)) setFound(body.threads)
          else {
            setSearchProblem(describeLoadFailure(r.status))
            setFound(null)
          }
        })
        .catch(() => {
          if (!current) return
          setSearchProblem(describeLoadFailure())
          setFound(null)
        })
    }, SEARCH_DELAY_MS)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [query])

  async function rename(event, thread) {
    event.preventDefault()
    setError('')
    let response
    try {
      response = await fetch(`/api/threads/${thread.id}/rename`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: draft }),
      })
    } catch {
      setError(describeActionFailure())
      return
    }
    if (!response.ok) {
      const body = await readJson(response)
      setError(describeActionFailure(response.status, body?.detail))
      return
    }
    setEditing(null)
    await load()
  }

  const searching = query.trim().length >= MIN_SEARCH
  const shown = searching ? found : threads

  return (
    <main className="history-page">
      <div className="history-inner">
        <h1>Past chats</h1>
        <p className="memory-dim">Diya has one chat, on the Chat page. These are the chats from before that: you can read and search them here.</p>
        {threads === null ? (
          <div role="status" aria-label="Loading your chats">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : threads === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t load your chats</h2>
            <p>{problem}</p>
            <a className="cta" href="/history">
              Try again
            </a>
          </div>
        ) : threads.length === 0 ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>No conversations yet</h2>
            <p>Your past chats will show up here.</p>
            <Link className="cta" href="/">
              Start a chat
            </Link>
          </div>
        ) : (
          <>
            <div className="memory-add">
              <label className="memory-sr" htmlFor="chat-search">
                Search your chats
              </label>
              <input
                id="chat-search"
                type="search"
                className="memory-input"
                placeholder="Search inside your chats"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={100}
              />
            </div>
            {error && (
              <p className="memory-error" role="alert">
                {error}
              </p>
            )}
            {searchProblem && (
              <p className="memory-error" role="alert">
                {searchProblem}
              </p>
            )}
            {searching && found === null && !searchProblem && <p className="memory-dim">Looking&hellip;</p>}
            {searching && found !== null && found.length === 0 && <p className="memory-dim">No chat has those words in it.</p>}
            {(shown || []).map((t) => (
              <div key={t.id} className="thread-row">
                {editing === t.id ? (
                  <form className="memory-add" onSubmit={(e) => rename(e, t)}>
                    <label className="memory-sr" htmlFor={`rename-${t.id}`}>
                      Name for this chat
                    </label>
                    <input
                      id={`rename-${t.id}`}
                      className="memory-input"
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      maxLength={80}
                      placeholder="A name for this chat (empty to take it back)"
                      autoFocus
                    />
                    <button type="submit" className="memory-btn memory-btn--primary">
                      Save
                    </button>
                    <button type="button" className="memory-btn" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                  </form>
                ) : (
                  <>
                    <Link className="thread" href={`/?thread=${t.id}`}>
                      {/* CSS ellipsis, not a hard slice: it used to cut mid-word ("...from Bengalu"). */}
                      <div className="preview">{t.main && <strong>Your chat now &middot; </strong>}{t.preview}</div>
                      {t.match && t.match !== t.preview && <div className="date">{t.match}</div>}
                      <div className="date">{t.created_at.slice(0, 16).replace('T', ' ')}</div>
                    </Link>
                    <button
                      type="button"
                      className="memory-btn"
                      aria-label={`Rename: ${t.preview}`}
                      onClick={() => {
                        setError('')
                        setEditing(t.id)
                        setDraft('')
                      }}
                    >
                      Rename
                    </button>
                  </>
                )}
              </div>
            ))}
          </>
        )}
      </div>
    </main>
  )
}
