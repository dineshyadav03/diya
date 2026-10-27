'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import WeatherProvider from './WeatherProvider'

// The one navigation for every page (docs/UI_DESIGN.md, D2): a floating pill at the top with the three pages used most (Home, Chat, Memory) and a slider
// that glides under the one you are on, a round button at the left that opens a glass menu with every page (and the theme), and the brand mark at the right.
// A page says <AppShell> and puts its content inside; it carries no header of its own, so a link to every page from every page is one list, here.
// Every /api/... call is same-origin: this app's own route handlers (app/api) forward it to the Python API with the token, on the server.

export const NAV = [
  {
    label: 'Your day',
    items: [
      { href: '/home', name: 'Home' },
      { href: '/today', name: 'Today' },
      { href: '/reminders', name: 'Reminders', badge: 'due' },
      { href: '/scheduled', name: 'Scheduled' },
      { href: '/automations', name: 'Automations' },
      { href: '/tasks', name: 'Tasks' },
    ],
  },
  {
    label: 'Assistant',
    items: [
      { href: '/', name: 'Chat' },
      { href: '/history', name: 'History' },
      { href: '/memory', name: 'Memory' },
      { href: '/knowledge', name: 'Knowledge' },
      { href: '/playbooks', name: 'Playbooks' },
    ],
  },
  {
    label: 'System',
    items: [
      { href: '/connections', name: 'Connections' },
      { href: '/status', name: 'Status' },
      { href: '/activity', name: 'Activity' },
      { href: '/actions', name: 'Actions', badge: 'waiting' },
    ],
  },
]

// The pill: the pages used most. Everything else is in the menu, grouped as in NAV.
export const TABS = [
  { href: '/home', name: 'Home' },
  { href: '/', name: 'Chat' },
  { href: '/memory', name: 'Memory' },
]

const THEMES = [
  { value: 'system', name: 'System' },
  { value: 'light', name: 'Light' },
  { value: 'dark', name: 'Dark' },
]

// Counts for the two links that carry one, asked once a minute while the page is open. If a count cannot be asked nothing is shown: a
// badge that says 0 when it does not know would be a lie, and nobody asked for it, so there is nothing to explain.
function useCounts() {
  const [due, setDue] = useState(null) // reminders that have come due
  const [waiting, setWaiting] = useState(null) // actions waiting for the owner's decision, or whose outcome is unknown (docs/ACTIONS_DESIGN.md, A3)

  useEffect(() => {
    let cancelled = false
    async function checkActions() {
      try {
        const response = await fetch('/api/actions')
        const body = response.ok ? await response.json() : null
        const counts = body && body.counts
        const count = counts && Number.isInteger(counts.pending) && Number.isInteger(counts.unknown) ? counts.pending + counts.unknown : null
        if (!cancelled) setWaiting(count)
      } catch {
        if (!cancelled) setWaiting(null)
      }
    }
    async function checkReminders() {
      try {
        const response = await fetch('/api/reminders')
        const body = response.ok ? await response.json() : null
        if (!cancelled) setDue(body && body.counts && Number.isInteger(body.counts.due) ? body.counts.due : null)
      } catch {
        if (!cancelled) setDue(null)
      }
    }
    checkActions()
    checkReminders()
    window.addEventListener('diya-actions-changed', checkActions) // a decision made under the chat (components/WaitingActions.jsx)
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        checkActions()
        checkReminders()
      }
    }, 60_000)
    return () => {
      cancelled = true
      clearInterval(timer)
      window.removeEventListener('diya-actions-changed', checkActions)
    }
  }, [])

  return { due, waiting }
}

function ThemeToggle() {
  const [theme, setTheme] = useState('system') // the saved choice is read after mount, so the server render and the first client render agree

  useEffect(() => {
    try {
      const saved = localStorage.getItem('diya_theme')
      if (saved === 'light' || saved === 'dark') setTheme(saved)
    } catch {}
  }, [])

  function choose(value) {
    setTheme(value)
    try {
      if (value === 'system') localStorage.removeItem('diya_theme')
      else localStorage.setItem('diya_theme', value)
    } catch {}
    if (value === 'system') delete document.documentElement.dataset.theme
    else document.documentElement.dataset.theme = value
  }

  return (
    <div>
      <span className="theme-label" id="theme-label">
        Theme
      </span>
      <div className="theme-toggle" role="radiogroup" aria-labelledby="theme-label">
        {THEMES.map((option) => (
          <button key={option.value} type="button" role="radio" aria-checked={theme === option.value} onClick={() => choose(option.value)}>
            {option.name}
          </button>
        ))}
      </div>
    </div>
  )
}

// Only shown when the UI is protected with a passcode (docs/UI_LOGIN_DESIGN.md) and this browser has signed in; otherwise there is nothing to sign out of.
function SignOut() {
  const [signedIn, setSignedIn] = useState(false)

  useEffect(() => {
    let alive = true
    fetch('/session')
      .then((response) => response.json())
      .then((data) => {
        if (alive) setSignedIn(Boolean(data.required && data.signedIn))
      })
      .catch(() => {
        if (alive) setSignedIn(false)
      })
    return () => {
      alive = false
    }
  }, [])

  async function signOut() {
    try {
      await fetch('/session', { method: 'DELETE' })
    } finally {
      window.location.assign('/login')
    }
  }

  if (!signedIn) return null
  return (
    <button type="button" className="signout" onClick={signOut}>
      Sign out
    </button>
  )
}

// The sign-in page is drawn without the shell: its navigation and counts all ask the API, and none of that is answered before signing in.
export default function AppShell({ children }) {
  const pathname = usePathname() || '/'
  if (pathname === '/login') return <>{children}</>
  return (
    <WeatherProvider>
      <Shell pathname={pathname}>{children}</Shell>
    </WeatherProvider>
  )
}

function Shell({ children, pathname }) {
  const [open, setOpen] = useState(false)
  const hubRef = useRef(null)
  const counts = useCounts()

  // A new page closes the menu (a tap on a link navigates; the shell itself stays mounted only within one page).
  useEffect(() => setOpen(false), [pathname])

  useEffect(() => {
    if (!open) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  // The menu sits just under the bar at the top, whatever height the bar has (a notch, a larger text size).
  const placeMenu = useCallback((el) => {
    hubRef.current = el
    if (el) el.closest('.shell')?.style.setProperty('--hub-h', `${el.offsetHeight}px`)
  }, [])

  const isCurrent = (href) => (href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(href + '/'))
  const badgeFor = (kind) => (kind === 'due' ? counts.due : kind === 'waiting' ? counts.waiting : null)
  const badgeLabel = (kind, n) => (kind === 'due' ? `${n} due` : `${n} waiting for you`)
  const menuCount = (counts.due || 0) + (counts.waiting || 0)
  const tab = TABS.findIndex((t) => isCurrent(t.href)) // which of the three the slider is under; -1 on any other page (the slider hides)

  return (
    <div className="shell" data-nav-open={open ? 'true' : 'false'}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="hub" ref={placeMenu}>
        <div className="hub-left">
          <button type="button" className="hub-btn" aria-label={open ? 'Close the menu' : 'Open the menu'} aria-expanded={open} aria-controls="site-nav" onClick={() => setOpen((o) => !o)}>
            <span className="hub-bars" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            {!open && menuCount > 0 && (
              <span className="due-badge" aria-label={`${menuCount} need you`}>
                {menuCount}
              </span>
            )}
          </button>
        </div>
        <nav className="hub-pill" aria-label="Main pages" data-tab={tab >= 0 ? tab : undefined} style={tab >= 0 ? { '--tab': tab } : undefined}>
          <span className="hub-slider" aria-hidden="true" />
          {TABS.map((item) => (
            <Link key={item.href} className="hub-tab" href={item.href} aria-current={isCurrent(item.href) ? 'page' : undefined}>
              {item.name}
            </Link>
          ))}
        </nav>
        <div className="hub-right">
          <Link className="hub-btn" href="/home" aria-label="Diya: Home">
            <img src="/diya-flame.svg" alt="" className="hub-mark" />
          </Link>
        </div>
      </header>
      {open && <div className="menu-scrim" onClick={() => setOpen(false)} aria-hidden="true" />}
      <nav className="menu-sheet" id="site-nav" aria-label="All pages">
        {NAV.map((group) => (
          <div key={group.label}>
            <div className="nav-label" id={`nav-${group.label.replace(/\s+/g, '-').toLowerCase()}`}>
              {group.label}
            </div>
            <ul className="nav-group" aria-labelledby={`nav-${group.label.replace(/\s+/g, '-').toLowerCase()}`}>
              {group.items.map((item) => {
                const n = badgeFor(item.badge)
                return (
                  <li key={item.href}>
                    <Link className="nav-link" href={item.href} aria-current={isCurrent(item.href) ? 'page' : undefined}>
                      {item.name}
                      {n > 0 && (
                        <span className="due-badge" aria-label={badgeLabel(item.badge, n)}>
                          {n}
                        </span>
                      )}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
        <div className="menu-foot">
          <ThemeToggle />
          <SignOut />
        </div>
      </nav>
      <div className="shell-main" id="main">
        {children}
      </div>
    </div>
  )
}
