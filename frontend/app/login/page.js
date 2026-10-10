'use client'

import { useState } from 'react'

// The way in when the UI is protected with a passcode (docs/UI_LOGIN_DESIGN.md). The shell is not drawn round it (components/AppShell.jsx): none of
// the shell's calls would be answered before signing in.
export default function LoginPage() {
  const [passcode, setPasscode] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  async function signIn(event) {
    event.preventDefault()
    if (busy || !passcode) return
    setBusy(true)
    setProblem('')
    try {
      const next = new URLSearchParams(window.location.search).get('next') || '/'
      const res = await fetch('/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ passcode, next }),
      })
      let data = null
      try {
        data = await res.json()
      } catch {}
      if (res.ok && data && typeof data.next === 'string') {
        window.location.assign(data.next) // the server has checked that this is a place on this site
        return
      }
      setProblem(data && typeof data.error === 'string' ? data.error : 'Diya’s server sent back something this page couldn’t read.')
    } catch {
      setProblem('Diya’s server didn’t answer. Check that it’s running, then try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <form className="login-card" onSubmit={signIn}>
        <h1 className="login-title">Sign in to Diya</h1>
        <label className="login-label" htmlFor="passcode">
          Passcode
        </label>
        <input
          id="passcode"
          name="passcode"
          type="password"
          className="login-input"
          autoComplete="current-password"
          autoFocus
          value={passcode}
          onChange={(event) => setPasscode(event.target.value)}
          aria-invalid={problem ? 'true' : undefined}
          aria-describedby={problem ? 'login-problem' : undefined}
        />
        {problem && (
          <p className="login-problem" id="login-problem" role="alert">
            {problem}
          </p>
        )}
        <button type="submit" className="memory-btn memory-btn--primary login-submit" disabled={busy || !passcode}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}
