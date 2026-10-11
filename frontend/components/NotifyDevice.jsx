'use client'

import { useEffect, useState } from 'react'
import { describeLoadFailure } from '../lib/api-failure.mjs'

// Telling this device by Web Push (docs/PUSH_DESIGN.md, unit P2). The button asks the browser for permission, subscribes this device with the public key the API gives, and
// hands the subscription to the API through this app's own routes (the server side attaches the access token; none of it is here). What a notification says is the API's
// to decide (by default only that something is waiting, never what), and a tap on it opens this app and nothing else: the service worker (public/sw.js) ignores any address.

const JSON_HEADERS = { 'content-type': 'application/json' }

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

// The key the API gives is URL-safe base64; the browser wants the bytes.
function keyBytes(text) {
  const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4)
  return Uint8Array.from(atob(padded), (ch) => ch.charCodeAt(0))
}

function canPush() {
  return typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

async function thisDevice() {
  const registration = await navigator.serviceWorker.getRegistration('/')
  return registration ? registration.pushManager.getSubscription() : null
}

export default function NotifyDevice() {
  // 'loading' | 'off' (the server has it switched off) | 'unsupported' | 'denied' | 'ready' | 'on' | 'working'
  const [phase, setPhase] = useState('loading')
  const [serverProblem, setServerProblem] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    async function look() {
      let status
      try {
        const response = await fetch('/api/push/status')
        status = response.status
        const body = response.ok ? await readJson(response) : null
        if (cancelled) return
        if (!body || typeof body.enabled !== 'boolean') throw new Error('unreadable')
        if (!body.enabled) {
          setServerProblem(typeof body.problem === 'string' ? body.problem : '')
          setPhase('off')
        } else if (!canPush()) {
          setPhase('unsupported')
        } else if (Notification.permission === 'denied') {
          setPhase('denied')
        } else {
          setPhase((await thisDevice()) ? 'on' : 'ready')
        }
      } catch {
        if (!cancelled) {
          setMessage(describeLoadFailure(status))
          setPhase('off')
          setServerProblem('')
        }
      }
    }
    look()
    return () => {
      cancelled = true
    }
  }, [])

  async function turnOn() {
    setPhase('working')
    setMessage('')
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        setPhase(permission === 'denied' ? 'denied' : 'ready')
        return
      }
      const registration = await navigator.serviceWorker.register('/sw.js')
      await navigator.serviceWorker.ready
      const keyResponse = await fetch('/api/push/key')
      const keyBody = keyResponse.ok ? await readJson(keyResponse) : null
      if (!keyBody || typeof keyBody.key !== 'string') throw new Error(describeLoadFailure(keyResponse.status))
      const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(keyBody.key) })
      const saved = await fetch('/api/push/subscribe', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(subscription) })
      if (!saved.ok) {
        await subscription.unsubscribe()
        const refusal = await readJson(saved)
        throw new Error(typeof refusal?.detail === 'string' ? refusal.detail.slice(0, 200) : describeLoadFailure(saved.status))
      }
      setPhase('on')
    } catch (error) {
      setPhase('ready')
      setMessage(`Couldn’t turn notifications on for this device. ${error instanceof Error && error.message ? error.message : ''}`.trim())
    }
  }

  async function turnOff() {
    setPhase('working')
    setMessage('')
    try {
      const subscription = await thisDevice()
      if (subscription) {
        await fetch('/api/push/unsubscribe', { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ endpoint: subscription.endpoint }) })
        await subscription.unsubscribe()
      }
      setPhase('ready')
    } catch {
      setPhase('on')
      setMessage('Couldn’t turn notifications off for this device. Try again.')
    }
  }

  async function sendTest() {
    setMessage('')
    try {
      const response = await fetch('/api/push/test', { method: 'POST' })
      const body = response.ok ? await readJson(response) : null
      if (!body || !Number.isInteger(body.accepted)) throw new Error(describeLoadFailure(response.status))
      setMessage(
        body.accepted > 0
          ? `Sent a test to ${body.accepted} device${body.accepted === 1 ? '' : 's'}. It says nothing about you.${body.failed ? ` ${body.failed} did not take it.` : ''}`
          : 'No device took the test. Turn notifications off and on again for this device.',
      )
    } catch (error) {
      setMessage(`Couldn’t send a test. ${error instanceof Error ? error.message : ''}`.trim())
    }
  }

  return (
    <section aria-labelledby="notify-device" className="notify-device">
      <h2 id="notify-device">Notifications to this device</h2>
      {phase === 'loading' && <p className="memory-dim">Looking…</p>}
      {phase === 'off' && (
        <p className="memory-dim">
          {message || 'Notifications to the phone are switched off on this computer.'} {serverProblem}
        </p>
      )}
      {phase === 'unsupported' && (
        <p className="memory-dim">
          This browser can’t receive notifications here. On an iPhone, add Diya to the Home Screen first and open it from there.
        </p>
      )}
      {phase === 'denied' && <p className="memory-dim">Notifications are blocked for this site in the browser’s settings. Allow them there, then reload this page.</p>}
      {(phase === 'ready' || phase === 'working' || phase === 'on') && (
        <>
          <p className="memory-dim">
            Diya can tell this device when a reminder is due, a question is waiting or an action needs your approval, even with this page closed. The message is encrypted for
            this device. The push service run by the browser’s maker is told that a notification was sent, and when, and cannot read it. By default the notification says only
            that something is waiting, not what, and tapping it opens Diya.
          </p>
          <div className="memory-actions">
            {phase === 'on' ? (
              <>
                <button type="button" className="memory-btn" onClick={sendTest}>
                  Send a test
                </button>
                <button type="button" className="memory-btn memory-btn--quiet" onClick={turnOff}>
                  Turn off for this device
                </button>
              </>
            ) : (
              <button type="button" className="memory-btn memory-btn--primary" onClick={turnOn} disabled={phase === 'working'}>
                {phase === 'working' ? 'Working…' : 'Notify this device'}
              </button>
            )}
          </div>
        </>
      )}
      {message && phase !== 'off' && (
        <p className="memory-dim" role="status">
          {message}
        </p>
      )}
    </section>
  )
}
