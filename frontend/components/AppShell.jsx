'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

// The one navigation for every page (docs/UI_DESIGN.md, D2): a sidebar on a laptop, a top bar with a Menu button on a phone. A page says
// <AppShell> and puts its content inside; it carries no header of its own, so a link to every page from every page is one list, here.
// Every /api/... call is same-origin: this app's own route handlers (app/api) forward it to the Python API with the token, on the server.

export const NAV = [
  {
    label: 'Your day',
    items: [
      { href: '/today', name: 'Today' },
      { href: '/reminders', name: 'Reminders', badge: 'due' },
      { href: '/scheduled', name: 'Scheduled' },
      { href: '/tasks', name: 'Tasks' },
    ],
  },
  {
    label: 'Assistant',
    items: [
      { href: '/', name: 'Chat' },
      { href: '/history', name: 'History' },
      { href: '/memory', name: 'Memory' },
    ],
  },
  {
    label: 'System',
    items: [
      { href: '/connections', name: 'Connections' },
      { href: '/actions', name: 'Actions', badge: 'waiting' },
    ],
  },
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
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') {
        checkActions()
        checkReminders()
      }
    }, 60_000)
    return () => {
      cancelled = true
      clearInterval(timer)
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

export default function AppShell({ children }) {
  const pathname = usePathname() || '/'
  const [open, setOpen] = useState(false)
  const topbarRef = useRef(null)
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

  // The menu panel sits just under the top bar, whatever height the bar has (a notch, a larger text size).
  const placeMenu = useCallback((el) => {
    topbarRef.current = el
    if (el) el.closest('.shell')?.style.setProperty('--topbar-h', `${el.offsetHeight}px`)
  }, [])

  const isCurrent = (href) => (href === '/' ? pathname === '/' : pathname === href || pathname.startsWith(href + '/'))
  const badgeFor = (kind) => (kind === 'due' ? counts.due : kind === 'waiting' ? counts.waiting : null)
  const badgeLabel = (kind, n) => (kind === 'due' ? `${n} due` : `${n} waiting for you`)
  const menuCount = (counts.due || 0) + (counts.waiting || 0)

  return (
    <div className="shell" data-nav-open={open ? 'true' : 'false'}>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar" ref={placeMenu}>
        <Link className="brand" href="/">
          <img src="/diya-flame.svg" alt="" className="brand-mark" />
          Diya
        </Link>
        <button type="button" className="menu-btn" aria-expanded={open} aria-controls="site-nav" onClick={() => setOpen((o) => !o)}>
          {open ? 'Close' : 'Menu'}
          {!open && menuCount > 0 && (
            <span className="due-badge" aria-label={`${menuCount} need you`}>
              {menuCount}
            </span>
          )}
        </button>
      </header>
      <nav className="sidebar" id="site-nav" aria-label="Main">
        <Link className="brand" href="/">
          <img src="/diya-flame.svg" alt="" className="brand-mark" />
          Diya
        </Link>
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
        <div className="sidebar-foot">
          <ThemeToggle />
        </div>
      </nav>
      <div className="shell-main" id="main">
        {children}
      </div>
    </div>
  )
}
