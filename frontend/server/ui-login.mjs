// The login in front of the UI (docs/UI_LOGIN_DESIGN.md; audit finding F1). Server-side only, and written against web standards
// (Request, Response, Web Crypto, no Node-only imports) so the same code runs in Next's middleware, in a route handler, and
// under plain Node in the tests. Nothing here knows about Next.js: middleware.js and app/session/route.js are thin adapters.
//
// A passcode (DIYA_UI_PASSCODE) turns it on. Signing in with it sets a signed cookie; the middleware lets a request through only
// with a good cookie. The key that signs the cookie is derived from the passcode, so changing the passcode ends every session.

export const COOKIE = 'diya_session'
export const MIN_PASSCODE = 12 // the launcher refuses a shorter one in LAN mode (tools/next-tls.mjs, which repeats this number; a test pins both)
export const SESSION_MS = 30 * 24 * 60 * 60 * 1000
export const FAILURE_DELAY_MS = 400
export const MAX_FAILURES = 5
export const FIRST_LOCK_MS = 5 * 60 * 1000
export const MAX_LOCK_MS = 60 * 60 * 1000
const MAX_BODY_CHARS = 4096

const encoder = new TextEncoder()

// The passcode the UI is protected with, or '' when it is not turned on.
export function passcodeFrom(env) {
  return String(env?.DIYA_UI_PASSCODE ?? '').trim()
}

async function sha256(text) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', encoder.encode(text)))
}

// Constant time for two byte strings of one length (both callers compare digests or fixed-length hex).
function sameBytes(a, b) {
  if (a.length !== b.length) return false
  let difference = 0
  for (let i = 0; i < a.length; i += 1) difference |= a[i] ^ b[i]
  return difference === 0
}

const hex = (bytes) => [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')

// Both sides are hashed first, so the comparison is always between two 32-byte values whatever was typed.
export async function passcodeMatches(passcode, attempt) {
  if (!passcode || typeof attempt !== 'string') return false
  const expected = await sha256(`diya-ui-passcode-v1:${passcode}`)
  const given = await sha256(`diya-ui-passcode-v1:${attempt.trim()}`)
  return sameBytes(expected, given)
}

async function sign(passcode, message) {
  const key = await crypto.subtle.importKey('raw', await sha256(`diya-ui-session-v1:${passcode}`), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  return hex(new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(message))))
}

// A session: "v1.<expiry in ms>.<hex HMAC-SHA256 of v1.<expiry>>".
export async function makeSession(passcode, now) {
  const expires = now + SESSION_MS
  return `v1.${expires}.${await sign(passcode, `v1.${expires}`)}`
}

export async function sessionValid(passcode, token, now) {
  if (!passcode || typeof token !== 'string') return false
  const parts = /^v1\.(\d{1,15})\.([0-9a-f]{64})$/.exec(token)
  if (!parts) return false
  if (!(Number(parts[1]) > now)) return false
  return sameBytes(encoder.encode(await sign(passcode, `v1.${parts[1]}`)), encoder.encode(parts[2]))
}

export function readCookie(header, name) {
  if (!header) return null
  for (const part of header.split(';')) {
    const at = part.indexOf('=')
    if (at !== -1 && part.slice(0, at).trim() === name) return part.slice(at + 1).trim()
  }
  return null
}

// HttpOnly: no script can read it. SameSite=Strict: another site cannot make the browser send it. Secure whenever the page is HTTPS.
function cookieHeader(value, { secure, maxAgeSeconds }) {
  return `${COOKIE}=${value}; Path=/; Max-Age=${maxAgeSeconds}; HttpOnly; SameSite=Strict${secure ? '; Secure' : ''}`
}

// Where to go after signing in: a path on this site and nothing else, so a link cannot send a person elsewhere once they have signed in.
export function safeNext(value) {
  if (typeof value !== 'string' || value.length > 2000) return '/'
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\') || /[\u0000-\u001f\u007f]/.test(value)) return '/'
  if (value === '/login' || value.startsWith('/login?') || value === '/session' || value.startsWith('/session')) return '/'
  return value
}

function json(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', 'cache-control': 'no-store', ...headers },
  })
}

// A request that changes something and says it came from another site is refused (the second guard, after SameSite=Strict).
function crossOrigin(request, url) {
  const origin = request.headers.get('origin')
  if (origin === null) return false // not a browser's cross-site request: a script, or the same page's own GET
  const own = `${url.protocol}//${(request.headers.get('host') || url.host).toLowerCase()}`
  try {
    return new URL(origin).origin.toLowerCase() !== own // the scheme counts too: a plain-HTTP page is not this HTTPS site
  } catch {
    return true // "null" and anything else that is not an address
  }
}

const READ_ONLY = new Set(['GET', 'HEAD', 'OPTIONS'])

// What the middleware does with a request: null to let it through, or the Response that turns it away.
export async function guard(request, env, now = Date.now()) {
  const passcode = passcodeFrom(env)
  if (!passcode) return null // not turned on
  const url = new URL(request.url)
  if (!READ_ONLY.has(request.method.toUpperCase()) && crossOrigin(request, url)) return json(403, { error: 'A request from another site was refused.' })
  if (url.pathname === '/login' || url.pathname === '/session') return null // the way in, and the way to ask and to leave
  if (await sessionValid(passcode, readCookie(request.headers.get('cookie'), COOKIE), now)) return null
  if (url.pathname.startsWith('/api/')) return json(511, { error: 'Sign in again: this browser is not signed in to Diya.' })
  // Sent to the name the browser used (its Host header), not the one the server calls itself: a phone that reached this computer by
  // its address must not be sent to its own "localhost". (Next's middleware needs an absolute address in a redirect, so not a relative one.)
  const own = `${url.protocol}//${request.headers.get('host') || url.host}`
  return new Response(null, {
    status: 307,
    headers: { location: new URL(`/login?next=${encodeURIComponent(url.pathname + url.search)}`, own).toString(), 'cache-control': 'no-store' },
  })
}

// The counter that slows guessing, kept by whoever serves /session. `sleep` is a parameter so a test need not wait.
export function newLoginState(sleep = (ms) => new Promise((done) => setTimeout(done, ms))) {
  return { failures: 0, locks: 0, lockedUntil: 0, sleep }
}

function minutesWords(ms) {
  const minutes = Math.ceil(ms / 60000) // only asked while a lock has time left, so at least one
  return minutes === 1 ? 'about a minute' : `about ${minutes} minutes`
}

// /session: GET says whether sign-in is on and whether this browser is signed in; POST signs in; DELETE signs out.
export async function handleSession(request, env, state, now = Date.now()) {
  const passcode = passcodeFrom(env)
  const url = new URL(request.url)
  const method = request.method.toUpperCase()
  const secure = url.protocol === 'https:'
  if (method === 'GET') {
    const signedIn = passcode ? await sessionValid(passcode, readCookie(request.headers.get('cookie'), COOKIE), now) : false
    return json(200, { required: Boolean(passcode), signedIn })
  }
  if (!passcode) return json(404, { error: 'Sign-in is not turned on.' })
  if (method !== 'POST' && method !== 'DELETE') return json(405, { error: 'Not allowed.' }, { allow: 'GET, POST, DELETE' })
  if (crossOrigin(request, url)) return json(403, { error: 'A request from another site was refused.' })
  if (method === 'DELETE') return json(200, { ok: true }, { 'set-cookie': cookieHeader('', { secure, maxAgeSeconds: 0 }) })

  if (state.lockedUntil > now) {
    const wait = state.lockedUntil - now
    return json(429, { error: `Too many wrong passcodes. Try again in ${minutesWords(wait)}.` }, { 'retry-after': String(Math.ceil(wait / 1000)) })
  }
  if (Number(request.headers.get('content-length')) > MAX_BODY_CHARS) return json(413, { error: 'That is too much to send.' })
  let body
  try {
    const text = await request.text()
    if (text.length > MAX_BODY_CHARS) return json(413, { error: 'That is too much to send.' })
    body = JSON.parse(text)
  } catch {
    return json(400, { error: 'Send the passcode as JSON.' })
  }

  if (await passcodeMatches(passcode, body?.passcode)) {
    state.failures = 0
    state.locks = 0
    state.lockedUntil = 0
    const token = await makeSession(passcode, now)
    return json(200, { ok: true, next: safeNext(body?.next) }, { 'set-cookie': cookieHeader(token, { secure, maxAgeSeconds: Math.floor(SESSION_MS / 1000) }) })
  }
  state.failures += 1
  let locked = false
  if (state.failures >= MAX_FAILURES) {
    state.locks += 1
    state.failures = 0
    state.lockedUntil = now + Math.min(FIRST_LOCK_MS * 2 ** (state.locks - 1), MAX_LOCK_MS)
    locked = true
  }
  await state.sleep(FAILURE_DELAY_MS)
  if (locked) return json(429, { error: `Too many wrong passcodes. Try again in ${minutesWords(state.lockedUntil - now)}.` }, { 'retry-after': String(Math.ceil((state.lockedUntil - now) / 1000)) })
  return json(401, { error: 'That passcode is not right.' })
}
