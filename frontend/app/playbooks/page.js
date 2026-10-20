'use client'

import { useCallback, useEffect, useState } from 'react'
import { describeLoadFailure } from '../../lib/api-failure.mjs'

// Your playbooks (docs/PLAYBOOKS_DESIGN.md): the steps you wrote, in files, for a kind of request. This page only SHOWS them: a playbook is written in an editor, never here, and nothing Diya does can write
// one. It lists what is used, what each is for and how it starts, and any file that cannot be used with the reason. Everything shown comes from the API already made safe to show, and React renders it as text.

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isData(body) {
  return body && Array.isArray(body.playbooks) && Array.isArray(body.problems)
}

const STARTS = { user: 'when you write its name', model: 'when a request is close to what it is for' }

export default function PlaybooksPage() {
  // null = loading, false = couldn't be loaded, otherwise the API's answer.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')

  const load = useCallback(async () => {
    let status
    try {
      const response = await fetch('/api/playbooks') // same-origin: app/api/playbooks forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (isData(body)) {
        setData(body)
        setProblem('')
        return
      }
    } catch {
      status = undefined
    }
    setProblem(describeLoadFailure(status))
    setData(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <main className="history-page memory-page">
      <div className="history-inner">
        <h1>Playbooks</h1>
        {data === null ? (
          <div role="status" aria-label="Loading your playbooks">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : data === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t load your playbooks</h2>
            <p>{problem}</p>
            <button type="button" className="cta" onClick={load}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <p className="memory-lede">
              A playbook is how you want a kind of request done, written once. When you write <code>@name</code> in a message, or a request is close to what a playbook is for, Diya hands its steps to the model for
              that one message as your instructions. A playbook changes nothing about what Diya may do: tools and approvals stay as they are. They are files you write yourself, in <code>{data.folder}</code>, one folder each
              with a <code>SKILL.md</code> inside; Diya never writes one.
            </p>
            {!data.enabled && (
              <p className="memory-dim" role="status">
                Playbooks are switched off (DIYA_PLAYBOOKS=0), so none is used.
              </p>
            )}
            {data.enabled && !data.exists && (
              <div className="empty-state">
                <img src="/diya-flame.svg" alt="" className="empty-mark" />
                <h2>No playbooks yet</h2>
                <p>
                  Make the folder <code>{data.folder}</code> and, inside it, a folder with a <code>SKILL.md</code>. The examples in <code>sample_playbooks</code> show the layout.
                </p>
              </div>
            )}
            {data.enabled && data.exists && data.playbooks.length === 0 && data.problems.length === 0 && (
              <p className="memory-dim">The folder is empty. Add a folder with a SKILL.md inside it.</p>
            )}
            {data.playbooks.length > 0 && (
              <ul className="memory-list">
                {data.playbooks.map((p) => (
                  <li key={p.name} className="memory-fact">
                    <p className="memory-text">@{p.name}</p>
                    <p className="memory-dim">{p.description}</p>
                    <p className="memory-dim">
                      Starts: {p.triggers.map((t) => STARTS[t] || t).join('; ')}.{p.hint ? ` Write after the name: ${p.hint}.` : ''}
                    </p>
                    <details>
                      <summary>The steps ({p.chars} of {data.limits.steps_chars} characters)</summary>
                      <pre className="memory-pre">{p.steps}</pre>
                    </details>
                  </li>
                ))}
              </ul>
            )}
            {data.problems.length > 0 && (
              <>
                <h2>Not used</h2>
                <ul className="memory-list">
                  {data.problems.map((p) => (
                    <li key={p.file} className="memory-fact" data-status="failed">
                      <p className="memory-text">{p.file}</p>
                      <p className="memory-dim">{p.reason}</p>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        )}
      </div>
    </main>
  )
}
