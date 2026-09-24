// The server side of the browser's /api/* calls (docs/STAGE1_DESIGN.md sections 3 and 6, step 4).
//
// The browser calls this app's own /api/* routes (same origin); those route handlers run on the
// Next.js server and call forward(), which sends the request on to the Python API and attaches the
// access token there. The token is read from DIYA_TOKEN in this server's environment and never
// reaches the browser: nothing in the browser bundle imports this file, and no response carries
// it. (Kept as .mjs so plain Node can import it -- the tests do.)
//
// Where requests go is fixed by configuration, never by the request. The API is on this computer,
// so the default is https://127.0.0.1:<DIYA_PORT or 8080>. It is NOT built from the incoming Host
// header: that header is chosen by whoever sends the request, so a URL derived from it would let
// them steer the bearer token to a host of their choosing.
//
//   DIYA_TOKEN     the API's access token (the one it printed once at first start). Optional while
//                  the API doesn't require one; without it no Authorization header is sent.
//   DIYA_PORT      the API's port (default 8080), the same setting the API itself uses.
//   DIYA_API_URL   overrides the address entirely (an origin, e.g. https://127.0.0.1:8443). The
//                  token is only ever sent over https, or to this computer's own loopback address.

const DEFAULT_PORT = '8080'
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])

// What Node reports when it can't verify the API's certificate. mkcert's root CA is in the
// system trust store but Node does not read that store, so this is the usual first-run failure.
const TLS_TRUST_ERRORS = new Set([
  'UNABLE_TO_VERIFY_LEAF_SIGNATURE',
  'SELF_SIGNED_CERT_IN_CHAIN',
  'DEPTH_ZERO_SELF_SIGNED_CERT',
  'UNABLE_TO_GET_ISSUER_CERT_LOCALLY',
  'CERT_UNTRUSTED',
])

export class ProxyConfigError extends Error {}

export function backendOrigin(env = process.env) {
  const configured = (env.DIYA_API_URL || '').trim()
  let url
  if (configured) {
    try {
      url = new URL(configured)
    } catch {
      throw new ProxyConfigError(`DIYA_API_URL must be an address like https://127.0.0.1:8080, got ${JSON.stringify(configured)}`)
    }
    if ((url.protocol !== 'https:' && url.protocol !== 'http:') || url.pathname !== '/' || url.search || url.hash || url.username || url.password) {
      throw new ProxyConfigError('DIYA_API_URL must be just an http(s) origin (no path, credentials, query or fragment)')
    }
    return url
  }
  const port = (env.DIYA_PORT || '').trim() || DEFAULT_PORT
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    throw new ProxyConfigError(`DIYA_PORT must be a port number, got ${JSON.stringify(port)}`)
  }
  return new URL(`https://127.0.0.1:${port}`)
}

function errorResponse(status, message) {
  return Response.json({ error: message }, { status, headers: { 'cache-control': 'no-store' } })
}

function describe(error) {
  return error?.cause?.code || error?.cause?.message || error?.message || String(error)
}

// Send `request` to `path` on the API and hand back its answer. Only the content type is copied
// from the browser's request (the JSON or multipart body needs it); everything else the browser
// sent -- including any Authorization or Cookie header -- is dropped, and the token, if there is
// one, is attached here.
export async function forward(request, path, { env = process.env, fetchImpl = fetch } = {}) {
  let target
  try {
    target = new URL(path, backendOrigin(env))
  } catch (error) {
    if (error instanceof ProxyConfigError) return errorResponse(500, error.message)
    throw error
  }
  const token = (env.DIYA_TOKEN || '').trim()
  if (token && target.protocol !== 'https:' && !LOOPBACK.has(target.hostname)) {
    return errorResponse(500, "Won't send the access token over plain http to an address that isn't this computer")
  }

  const headers = new Headers()
  const type = request.headers.get('content-type')
  if (type) headers.set('content-type', type)
  if (token) headers.set('authorization', `Bearer ${token}`)

  const init = { method: request.method, headers, redirect: 'manual' }
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = request.body // streamed through unchanged: JSON and multipart audio alike
    init.duplex = 'half'
  }

  let upstream
  try {
    upstream = await fetchImpl(target, init)
  } catch (error) {
    const code = describe(error)
    console.error(`Diya UI proxy: can't reach the API at ${target.origin}: ${code}`) // never the token
    const hint = TLS_TRUST_ERRORS.has(error?.cause?.code)
      ? " Node doesn't trust the API's certificate: start the UI with npm run dev (which turns on --use-system-ca), or set NODE_OPTIONS=--use-system-ca (Node 22.15+) or NODE_EXTRA_CA_CERTS to your mkcert root CA."
      : ''
    return errorResponse(502, `Couldn't reach Diya's API (${code}).${hint}`)
  }

  if (upstream.status === 401) {
    console.error(
      token
        ? "Diya UI proxy: the API rejected DIYA_TOKEN (it is wrong, or the API's token was rotated)."
        : 'Diya UI proxy: the API requires an access token and DIYA_TOKEN is not set for the UI.',
    )
  }
  const headersOut = new Headers({ 'cache-control': 'no-store' })
  const answerType = upstream.headers.get('content-type')
  if (answerType) headersOut.set('content-type', answerType)
  return new Response(upstream.body, { status: upstream.status, headers: headersOut })
}

// A thread id is a whole number; anything else (a path, a query, an encoded slash) is turned away
// here instead of being pasted into the URL of the API request.
export async function forwardHistory(request, context, options) {
  const { thread_id: threadId } = await context.params
  if (!/^[0-9]{1,18}$/.test(String(threadId))) return errorResponse(404, 'No such thread')
  return forward(request, `/api/history/${threadId}`, options)
}
