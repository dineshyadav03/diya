// Test harness for frontend/lib/proxy.mjs and the route handlers in frontend/app/api.
// Reads one JSON scenario on stdin, prints one JSON result on stdout. Driven by
// tests/test_frontend_proxy.py; not part of the app.
//
// scenario = {
//   mode: 'route' | 'direct',
//   env: { DIYA_TOKEN, DIYA_PORT, DIYA_API_URL, ... },   // the UI server's environment
//   apiUrl: 'http://127.0.0.1:1234',   // route mode: a real API; omitted -> a capturing fake API
//   reply: { status, headers, bodyB64 },                 // what the capturing fake API answers
//   calls: [{ route, params, method, url, headers, bodyB64 }],   // requests as the browser sent them
//   direct: { path, error }              // direct mode: forward() with a spy instead of fetch
// }
// The route files are loaded from their real source (not re-implemented here): Node can't import a
// .js file that uses `export` without a package "type", so the source is read and imported as a
// data: URL with its one relative import pointed at the real proxy.mjs.
import http from 'node:http'
import { readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const proxyFile = join(root, 'frontend', 'lib', 'proxy.mjs')
const ROUTES = {
  chat: join(root, 'frontend', 'app', 'api', 'chat', 'route.js'),
  threads: join(root, 'frontend', 'app', 'api', 'threads', 'route.js'),
  transcribe: join(root, 'frontend', 'app', 'api', 'transcribe', 'route.js'),
  history: join(root, 'frontend', 'app', 'api', 'history', '[thread_id]', 'route.js'),
}

async function loadRoute(name) {
  const source = readFileSync(ROUTES[name], 'utf8').replace(
    /from\s+'[./]+lib\/proxy\.mjs'/,
    `from ${JSON.stringify(pathToFileURL(proxyFile).href)}`,
  )
  return import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'))
}

const stdin = await new Promise((done) => {
  let data = ''
  process.stdin.on('data', (chunk) => (data += chunk))
  process.stdin.on('end', () => done(data))
})
const scenario = JSON.parse(stdin)

const logs = []
console.error = (...args) => logs.push(args.join(' '))

const captured = []
let server = null
if (scenario.mode === 'route' && !scenario.apiUrl) {
  server = http.createServer((req, res) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      captured.push({
        method: req.method,
        url: req.url,
        headers: req.headers,
        rawHeaders: req.rawHeaders,
        bodyB64: Buffer.concat(chunks).toString('base64'),
      })
      const reply = scenario.reply || { status: 200, headers: { 'content-type': 'application/json' }, bodyB64: Buffer.from('{}').toString('base64') }
      res.writeHead(reply.status, reply.headers || {})
      res.end(Buffer.from(reply.bodyB64 || '', 'base64'))
    })
  })
  await new Promise((done) => server.listen(0, '127.0.0.1', done))
}

const env = { ...(scenario.env || {}) }
if (scenario.mode === 'route') {
  env.DIYA_API_URL = scenario.apiUrl || `http://127.0.0.1:${server.address().port}`
  // the route handlers read process.env, as they do inside Next
  for (const key of Object.keys(process.env)) if (key.startsWith('DIYA_')) delete process.env[key]
  Object.assign(process.env, env)
}

function browserRequest(call) {
  const init = { method: call.method || 'GET', headers: call.headers || {} }
  if (call.bodyB64 !== undefined) {
    init.body = Buffer.from(call.bodyB64, 'base64')
    init.duplex = 'half'
  }
  return new Request(call.url || 'https://localhost:3000/api/x', init)
}

async function describeResponse(response) {
  const headers = {}
  response.headers.forEach((value, key) => (headers[key] = value))
  return { status: response.status, headers, bodyB64: Buffer.from(await response.arrayBuffer()).toString('base64') }
}

const results = []
const spyCalls = []
if (scenario.mode === 'route') {
  for (const call of scenario.calls) {
    const module = await loadRoute(call.route)
    const handler = module[call.method || 'GET']
    if (!handler) {
      results.push({ noHandler: true })
      continue
    }
    const response = await handler(browserRequest(call), { params: Promise.resolve(call.params || {}) })
    results.push(await describeResponse(response))
  }
} else {
  const { forward } = await import(pathToFileURL(proxyFile).href)
  const fetchImpl = async (url, init) => {
    const headers = {}
    new Headers(init.headers).forEach((value, key) => (headers[key] = value))
    spyCalls.push({ url: String(url), method: init.method, headers, redirect: init.redirect, hasBody: init.body !== undefined })
    if (scenario.direct.error) {
      const error = new TypeError('fetch failed')
      error.cause = scenario.direct.error
      throw error
    }
    return new Response('{}', { status: scenario.direct.status || 200, headers: { 'content-type': 'application/json' } })
  }
  for (const call of scenario.calls) {
    const response = await forward(browserRequest(call), scenario.direct.path, { env, fetchImpl })
    results.push(await describeResponse(response))
  }
}

// Let the process end on its own: close the pooled keep-alive connections fetch left open (a
// process.exit() while sockets are closing trips a libuv assertion on Windows).
const pool = globalThis[Symbol.for('undici.globalDispatcher.1')]
if (pool?.close) await pool.close()
if (server) {
  server.closeAllConnections?.()
  await new Promise((done) => server.close(done))
}
process.stdout.write(JSON.stringify({ results, captured, spyCalls, logs }))
