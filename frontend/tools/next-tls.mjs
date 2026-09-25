// Starts the Next.js UI the way the backend is started: loopback by default, HTTPS with the
// certificate the backend uses, nothing machine-specific written into package.json.
//
//   node tools/next-tls.mjs <dev|start> [--lan] [--dry-run]
//
// Certificate: DIYA_SSL_CERT and DIYA_SSL_KEY (both or neither; relative paths are taken from the
// repo root, where the backend is run), otherwise the single mkcert pair (<name>+N.pem and
// <name>+N-key.pem) in the repo root -- the same rule as diya_config.tls_files().
// Port: DIYA_FRONTEND_PORT (default 3000), the same setting the backend uses to allow this origin.
// Host: 127.0.0.1. --lan listens on every interface instead. The browser only ever talks to this
// server: its /api/* calls are forwarded to the Python API from here (app/api, lib/proxy.mjs), so
// the API stays on this computer and needs DIYA_LAN=1 only for a device that calls it directly.
// Trust: those forwarded calls are HTTPS to the API, and Node -- unlike a browser -- ignores the
// operating system's trust store, where `mkcert -install` puts its root CA. So the child is started
// with --use-system-ca (Node 22.15+/23.9+) unless it is already there.
// `next start` cannot serve TLS, so only `dev` is HTTPS; `start` is plain HTTP.
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { basename, dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = resolve(frontendDir, '..')

function fail(message) {
  console.error(`Couldn't start the Diya UI: ${message}`)
  process.exit(1)
}

function certificate(env) {
  const cert = (env.DIYA_SSL_CERT || '').trim()
  const key = (env.DIYA_SSL_KEY || '').trim()
  if (Boolean(cert) !== Boolean(key)) fail('DIYA_SSL_CERT and DIYA_SSL_KEY must be set together')
  if (cert) {
    const pair = [resolve(repoRoot, cert), resolve(repoRoot, key)]
    for (const file of pair) if (!existsSync(file)) fail(`TLS file not found: ${file}`)
    return pair
  }
  const pairs = readdirSync(repoRoot)
    .filter((name) => /\+.+-key\.pem$/.test(name))
    .map((name) => [join(repoRoot, name.slice(0, -'-key.pem'.length) + '.pem'), join(repoRoot, name)])
    .filter(([certFile]) => existsSync(certFile))
  if (pairs.length > 1) {
    fail(`more than one mkcert certificate found (${pairs.map(([c]) => basename(c)).join(', ')}); set DIYA_SSL_CERT and DIYA_SSL_KEY to choose one`)
  }
  if (pairs.length === 0) {
    fail('no TLS certificate found. Put an mkcert pair in the repo root (mkcert localhost 127.0.0.1 ::1), or set DIYA_SSL_CERT and DIYA_SSL_KEY')
  }
  return pairs[0]
}

// The API requires an access token by default and the UI's server is what sends it (lib/proxy.mjs,
// from DIYA_TOKEN). Whether it has one: in this environment, or in one of the .env files Next itself
// loads (frontend/.env.local is the documented place). Someone running the API with
// DIYA_REQUIRE_TOKEN=0 has opted out and needs none.
function uiHasToken(env) {
  if ((env.DIYA_TOKEN || '').trim()) return true
  for (const name of ['.env.local', '.env.development.local', '.env.development', '.env']) {
    try {
      if (/^\s*DIYA_TOKEN\s*=\s*\S/m.test(readFileSync(join(frontendDir, name), 'utf8'))) return true
    } catch {} // no such file
  }
  return false
}

function tokenOptedOut(env) {
  return ['0', 'false', 'no', 'off'].includes((env.DIYA_REQUIRE_TOKEN || '').trim().toLowerCase())
}

// The environment the UI server must be started with so that its own HTTPS calls to the API
// verify. `supported` says whether this Node has the flag at all (process.allowedNodeEnvironmentFlags
// lists exactly what NODE_OPTIONS may contain, so an older Node is never handed one it rejects).
function trustEnvironment(env) {
  const options = (env.NODE_OPTIONS || '').trim()
  const supported = process.allowedNodeEnvironmentFlags.has('--use-system-ca')
  if (!supported || options.includes('--use-system-ca')) return { supported, env: {} }
  return { supported, env: { NODE_OPTIONS: options ? `${options} --use-system-ca` : '--use-system-ca' } }
}

function plan(argv, env) {
  const mode = argv[0]
  if (mode !== 'dev' && mode !== 'start') fail('usage: next-tls.mjs <dev|start> [--lan] [--dry-run]')
  const lan = argv.includes('--lan')
  const port = (env.DIYA_FRONTEND_PORT || '').trim() || '3000'
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
    fail(`DIYA_FRONTEND_PORT must be a port number, got ${JSON.stringify(port)}`)
  }
  const args = [mode, '-H', lan ? '0.0.0.0' : '127.0.0.1', '-p', port]
  if (mode === 'dev') {
    const [certFile, keyFile] = certificate(env)
    args.push('--experimental-https', '--experimental-https-key', keyFile, '--experimental-https-cert', certFile)
  }
  const trust = trustEnvironment(env)
  return { mode, lan, host: args[2], port, args, env: trust.env, systemTrust: trust.supported }
}

const { lan, args, host, port, env: extraEnv, systemTrust } = plan(process.argv.slice(2), process.env)

if (process.argv.includes('--dry-run')) {
  console.log(JSON.stringify({ host, port, lan, args, env: extraEnv }))
} else {
  if (lan) {
    console.warn(
      `LAN mode: the UI is served on every interface. Its server forwards the browser's API calls to ` +
        `the API on this computer, so the API needs neither DIYA_LAN nor DIYA_ALLOWED_HOSTS for the UI; ` +
        `those only matter for another device that calls the API directly.`,
    )
  }
  if (!uiHasToken(process.env) && !tokenOptedOut(process.env)) {
    console.warn(
      `DIYA_TOKEN is not set for the UI. The API requires an access token by default, so every request ` +
        `from the UI will be refused (401) until it is: put the token the API printed at its first start in ` +
        `DIYA_TOKEN in this terminal, or in frontend/.env.local (a lost token: start the API once with ` +
        `--rotate-token). If the API runs with DIYA_REQUIRE_TOKEN=0, set that here too. See docs/lan.md.`,
    )
  }
  if (!systemTrust && !(process.env.NODE_EXTRA_CA_CERTS || '').trim()) {
    console.warn(
      `This Node (${process.version}) cannot read the system trust store, so the UI server may not ` +
        `trust the API's mkcert certificate. Set NODE_EXTRA_CA_CERTS to your mkcert root CA ` +
        `(rootCA.pem in the folder "mkcert -CAROOT" prints), or use Node 22.15 or newer.`,
    )
  }
  const nextBin = createRequire(import.meta.url).resolve('next/dist/bin/next')
  const child = spawn(process.execPath, [nextBin, ...args], {
    cwd: frontendDir,
    stdio: 'inherit',
    env: { ...process.env, ...extraEnv },
  })
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
}
