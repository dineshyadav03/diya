'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { apiBase } from '../../lib/api'

export default function HistoryPage() {
  const [threads, setThreads] = useState(null)

  useEffect(() => {
    fetch(`${apiBase()}/api/threads`)
      .then((r) => r.json())
      .then((data) => setThreads(data.threads))
  }, [])

  return (
    <div className="history-page">
      <Link className="back" href="/">
        &larr; Back to chat
      </Link>
      <h2>Past chats</h2>
      {threads === null ? null : threads.length === 0 ? (
        <p>No conversations yet.</p>
      ) : (
        threads.map((t) => (
          <Link key={t.id} className="thread" href={`/?thread=${t.id}`}>
            <div className="preview">{t.preview.slice(0, 80)}</div>
            <div className="date">{t.created_at.slice(0, 16).replace('T', ' ')}</div>
          </Link>
        ))
      )}
    </div>
  )
}
