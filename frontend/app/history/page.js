'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { apiBase } from '../../lib/api'

export default function HistoryPage() {
  // null = loading, false = the server couldn't be reached, [] = no chats yet.
  const [threads, setThreads] = useState(null)

  useEffect(() => {
    fetch(`${apiBase()}/api/threads`)
      .then((r) => r.json())
      .then((data) => setThreads(data.threads))
      .catch(() => setThreads(false))
  }, [])

  return (
    <div className="app">
      {/* The same header as the chat, so the two screens read as one app. */}
      <header>
        <div className="title">
          <img src="/diya-flame.svg" alt="" className="brand-mark" />
          Diya
        </div>
        <div className="controls">
          <Link className="icon-btn" href="/">
            &larr; Back to chat
          </Link>
        </div>
      </header>
      <main className="history-page">
        <div className="history-inner">
          <h1>Past chats</h1>
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
              <p>Diya&rsquo;s server didn&rsquo;t answer. Check that it&rsquo;s running, then try again.</p>
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
            threads.map((t) => (
              <Link key={t.id} className="thread" href={`/?thread=${t.id}`}>
                {/* CSS ellipsis, not a hard slice: it used to cut mid-word ("...from Bengalu"). */}
                <div className="preview">{t.preview}</div>
                <div className="date">{t.created_at.slice(0, 16).replace('T', ' ')}</div>
              </Link>
            ))
          )}
        </div>
      </main>
    </div>
  )
}
