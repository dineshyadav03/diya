// Starts the Next.js UI the way the backend is started: loopback by default, HTTPS with the
// certificate the backend uses, nothing machine-specific written into package.json.
//
//   node tools/next-tls.mjs <dev|start> [--lan] [--dry-run]
//
// Certificate: DIYA_SSL_CERT and DIYA_SSL_KEY (both or neither; relative paths are taken from the
// repo root, where the backend is run), otherwise the single mkcert pair (<name>+N.pem and
// <name>+N-key.pem) in the repo root -- the same rule as diya_config.tls_files().
// Port: DIYA_FRONTEND_PORT (default 3000), the same setting the backend uses to allow this origin.
// Host: 127.0.0.1. --lan listens on every interface instead; the backend must then also run with
// DIYA_LAN=1 and DIYA_ALLOWED_HOSTS set to the name or address the other device uses.
// `next start` cannot serve TLS, so only `dev` is HTTPS; `start` is plain HTTP.
import { spawn } from 'node:child_process'
import { existsSync, readdirSync } from 'node:fs'
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
  return { mode, lan, host: args[2], port, args }
}

const { lan, args, host, port } = plan(process.argv.slice(2), process.env)

if (process.argv.includes('--dry-run')) {
  console.log(JSON.stringify({ host, port, lan, args }))
} else {
  if (lan) {
    console.warn(
      `LAN mode: the UI is served on every interface. The API must also run with DIYA_LAN=1 and ` +
        `DIYA_ALLOWED_HOSTS=<the name or address the other device uses>, or it will refuse that device.`,
    )
  }
  const nextBin = createRequire(import.meta.url).resolve('next/dist/bin/next')
  const child = spawn(process.execPath, [nextBin, ...args], { cwd: frontendDir, stdio: 'inherit' })
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)))
}
