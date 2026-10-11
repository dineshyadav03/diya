// The service worker for notifications (docs/PUSH_DESIGN.md, section 6). It does two things and nothing else: show a notification when a push arrives, and open Diya when one is tapped.
// It makes no network request, keeps no data, and ignores any address a message might carry: a tap always opens "/", so a message can never send the person anywhere.

const FALLBACK = { title: 'Diya', body: 'Diya has something for you', tag: 'diya' }
const TITLE_CHARS = 80
const BODY_CHARS = 240

function read(event) {
  try {
    const data = event.data ? event.data.json() : null
    if (!data || typeof data !== 'object') return FALLBACK
    const text = (value, limit, fallback) => (typeof value === 'string' && value.trim() ? value.slice(0, limit) : fallback)
    return { title: text(data.title, TITLE_CHARS, FALLBACK.title), body: text(data.body, BODY_CHARS, FALLBACK.body), tag: text(data.tag, 80, FALLBACK.tag) }
  } catch {
    return FALLBACK
  }
}

self.addEventListener('push', (event) => {
  const { title, body, tag } = read(event)
  // The same tag replaces the notification already on the screen for that thing, so a message that is sent twice shows once.
  event.waitUntil(self.registration.showNotification(title, { body, tag, icon: '/diya-flame.svg' }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((open) => {
      const diya = open.find((client) => 'focus' in client)
      return diya ? diya.focus() : self.clients.openWindow('/')
    }),
  )
})
