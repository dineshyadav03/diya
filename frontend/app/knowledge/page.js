'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { describeActionFailure, describeLoadFailure } from '../../lib/api-failure.mjs'

// Pages made from the person's own notes (docs/KNOWLEDGE_DESIGN.md): one page for each name that recurs, made only of sentences copied word for word
// from the notes, with the note each came from. Nothing here is a fact Diya has accepted. Everything shown comes from the API already made safe to show,
// and React renders it as text, never as markup. Hiding a name is one press because it is undone from the list of hidden names just below.

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function isList(body) {
  return body && Array.isArray(body.pages) && Array.isArray(body.hidden) && typeof body.built === 'boolean'
}

function said(report) {
  const parts = [`Read ${report.notes} ${report.notes === 1 ? 'note' : 'notes'}`, `${report.pages} ${report.pages === 1 ? 'page' : 'pages'}`]
  if (report.written) parts.push(`${report.written} made or changed`)
  if (report.removed) parts.push(`${report.removed} removed`)
  return `${parts.join(', ')}.`
}

export default function KnowledgePage() {
  // null = loading, false = couldn't be loaded, otherwise { notes_folder, demo, built, pages, hidden }.
  const [data, setData] = useState(null)
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('') // '', 'build', or the name being hidden or brought back
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [left, setLeft] = useState([]) // files the last build left out, and why
  const [chosen, setChosen] = useState('') // the stem of the page being read

  const load = useCallback(async (first) => {
    let status
    try {
      const response = await fetch('/api/knowledge') // same-origin: app/api/knowledge forwards it, with the token, from the server
      status = response.status
      const body = response.ok ? await readJson(response) : null
      if (isList(body)) {
        setData(body)
        setProblem('')
        return true
      }
    } catch {
      status = undefined
    }
    if (first) {
      setProblem(describeLoadFailure(status))
      setData(false)
    } else {
      setError(describeLoadFailure(status))
    }
    return false
  }, [])

  useEffect(() => {
    load(true)
  }, [load])

  // Run a request the person asked for: on success say what happened and use the list the API sent back; on a refusal say why, in the API's own words
  // when it gave them, and that nothing was changed.
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
      if (response.ok) await load(false)
      setBusy('')
      return false
    }
    setNotice(describe(body))
    if (isList(body)) setData(body)
    else await load(false)
    setBusy('')
    return true
  }

  const build = () =>
    settle(
      () => fetch('/api/knowledge/build', { method: 'POST' }),
      'build',
      (body) => {
        setLeft(Array.isArray(body.report?.left_out) ? body.report.left_out : [])
        return body.report ? said(body.report) : 'Done.'
      },
    )
  const change = (action, name, text) =>
    settle(
      () =>
        fetch(`/api/knowledge/${action}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        }),
      name,
      () => text,
    )
  const hide = (page) => {
    setChosen('')
    return change('hide', page.name, `Hidden. ${page.name} will not get a page again. You can bring it back below.`)
  }
  const unhide = (name) => change('unhide', name, `${name} will get a page again the next time Diya reads your notes.`)

  const pages = data ? data.pages : []
  const page = pages.find((p) => p.stem === chosen) || null

  return (
    <main className="history-page memory-page reminders-page scheduled-page">
      <div className="history-inner">
        <h1>Knowledge</h1>
        {data === null ? (
          <div role="status" aria-label="Loading your pages">
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
            <div className="thread-skeleton" />
          </div>
        ) : data === false ? (
          <div className="empty-state">
            <img src="/diya-flame.svg" alt="" className="empty-mark" />
            <h2>Couldn&rsquo;t load your pages</h2>
            <p>{problem}</p>
            <button type="button" className="cta" onClick={() => load(true).then(() => undefined)}>
              Try again
            </button>
          </div>
        ) : (
          <>
            <p className="memory-lede">
              Diya reads your notes and makes one page for each name that comes up again and again: a person, a place, a project. A page holds only
              sentences copied word for word from your notes, with the note each one came from, so nothing is invented. Reading your notes uses no
              model and sends nothing anywhere. None of it counts as something Diya knows about you: that is still decided on the{' '}
              <Link href="/memory">Memory</Link> page.
            </p>
            <p className="memory-dim">
              Notes read from: <code>{data.notes_folder}</code>
              {data.demo
                ? '. That is the folder of six demo notes that comes with Diya, so there is almost nothing to find. To use your own, set DIYA_NOTES_DIR to a folder of yours and restart Diya.'
                : '.'}
            </p>
            <div className="memory-actions">
              <button type="button" className="memory-btn memory-btn--primary" onClick={build} disabled={busy === 'build'}>
                {data.built ? 'Read my notes again' : 'Read my notes now'}
              </button>
            </div>
            {busy === 'build' && (
              <p className="memory-dim" role="status">
                Reading your notes.
              </p>
            )}
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
            {left.length > 0 && (
              <p className="memory-dim" role="status">
                Left out: {left.join('; ')}
              </p>
            )}

            <section aria-labelledby="knowledge-pages">
              <h2 id="knowledge-pages">Pages ({pages.length})</h2>
              {pages.length === 0 ? (
                <p className="memory-dim">
                  {data.built
                    ? 'No name comes up in two or more of your notes yet. A name needs a capital letter, or write it like [[this]] in a note.'
                    : 'Nothing yet. Press the button above to read your notes.'}
                </p>
              ) : (
                <ul className="knowledge-names">
                  {pages.map((p) => (
                    <li key={p.stem}>
                      <button
                        type="button"
                        className={`memory-btn${p.stem === chosen ? ' memory-btn--primary' : ''}`}
                        aria-pressed={p.stem === chosen}
                        onClick={() => setChosen(p.stem === chosen ? '' : p.stem)}
                      >
                        {p.name} <span className="knowledge-count">{p.sentences.length + p.omitted}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {page && (
              <section aria-labelledby="knowledge-page" className="knowledge-page">
                <h2 id="knowledge-page">{page.name}</h2>
                <p className="memory-dim">
                  {page.sentences.length + page.omitted} {page.sentences.length + page.omitted === 1 ? 'sentence' : 'sentences'} in {page.notes}{' '}
                  {page.notes === 1 ? 'note' : 'notes'}, newest note first. Your own words.
                </p>
                <ul className="memory-list">
                  {page.sentences.map((s, index) => (
                    <li key={index} className="memory-fact">
                      <p className="memory-text">{s.text}</p>
                      <p className="knowledge-source">{s.source}</p>
                    </li>
                  ))}
                </ul>
                {page.omitted > 0 && <p className="memory-dim">&hellip;and {page.omitted} more in your notes.</p>}
                {page.links.length > 0 && (
                  <p className="memory-dim">
                    Mentioned with:{' '}
                    {page.links.map((name, index) => {
                      const other = pages.find((p) => p.name === name || p.stem === name)
                      return (
                        <span key={name}>
                          {index > 0 ? ', ' : ''}
                          {other ? (
                            <button type="button" className="memory-btn memory-btn--quiet knowledge-link" onClick={() => setChosen(other.stem)}>
                              {name}
                            </button>
                          ) : (
                            name
                          )}
                        </span>
                      )
                    })}
                  </p>
                )}
                <div className="memory-actions">
                  <button type="button" className="memory-btn memory-btn--danger" onClick={() => hide(page)} disabled={busy === page.name} aria-label={`Hide ${page.name}: no page, ever`}>
                    Hide this name
                  </button>
                </div>
              </section>
            )}

            {data.hidden.length > 0 && (
              <section aria-labelledby="knowledge-hidden">
                <h2 id="knowledge-hidden">Hidden ({data.hidden.length})</h2>
                <ul className="memory-list">
                  {data.hidden.map((name) => (
                    <li key={name} className="memory-fact">
                      <p className="memory-text">{name}</p>
                      <div className="memory-actions">
                        <button type="button" className="memory-btn" onClick={() => unhide(name)} disabled={busy === name} aria-label={`Bring back ${name}`}>
                          Bring back
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>
    </main>
  )
}
