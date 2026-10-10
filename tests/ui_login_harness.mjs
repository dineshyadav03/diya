// Test harness for frontend/server/ui-login.mjs. Reads one JSON list of operations on stdin and prints the list of their results on stdout.
// Driven by tests/test_ui_login.py; not part of the app. Operations run in order, so a later one can use the state an earlier one left.
//
//   { op: 'passcodeMatches', passcode, attempt }
//   { op: 'makeSession', passcode, now }
//   { op: 'sessionValid', passcode, token, now }
//   { op: 'safeNext', value }
//   { op: 'readCookie', header, name }
//   { op: 'guard', url, method, headers, env, now }
//   { op: 'session', url, method, headers, body, env, state, now }     state: a name; the login state of that name (made on first use)
//   { op: 'state', state }                                              the named state, as it is now (failures, locks, lockedUntil, sleeps)
// A Response comes back as { status, headers, body }; "body" is the text.
import { dirname, join, resolve } from 'node:path'
import { pathToFileURL, fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const login = await import(pathToFileURL(join(root, 'frontend', 'server', 'ui-login.mjs')).href)

const states = {}
const stateFor = (name) => {
  if (!states[name]) {
    const state = login.newLoginState(async (ms) => {
      state.sleeps.push(ms)
    })
    state.sleeps = []
    states[name] = state
  }
  return states[name]
}

async function describe(response) {
  if (response === null) return null
  return { status: response.status, headers: Object.fromEntries(response.headers), body: await response.text() }
}

const requestFrom = (step) =>
  new Request(step.url, { method: step.method || 'GET', headers: step.headers || {}, body: step.body === undefined ? undefined : step.body })

let input = ''
for await (const chunk of process.stdin) input += chunk
const results = []
for (const step of JSON.parse(input)) {
  switch (step.op) {
    case 'passcodeMatches':
      results.push(await login.passcodeMatches(step.passcode, step.attempt))
      break
    case 'makeSession':
      results.push(await login.makeSession(step.passcode, step.now))
      break
    case 'sessionValid':
      results.push(await login.sessionValid(step.passcode, step.token, step.now))
      break
    case 'safeNext':
      results.push(login.safeNext(step.value))
      break
    case 'readCookie':
      results.push(login.readCookie(step.header, step.name))
      break
    case 'guard':
      results.push(await describe(await login.guard(requestFrom(step), step.env || {}, step.now)))
      break
    case 'session':
      results.push(await describe(await login.handleSession(requestFrom(step), step.env || {}, stateFor(step.state || 'default'), step.now)))
      break
    case 'state': {
      const { failures, locks, lockedUntil, sleeps } = stateFor(step.state || 'default')
      results.push({ failures, locks, lockedUntil, sleeps })
      break
    }
    default:
      throw new Error(`unknown op ${step.op}`)
  }
}
process.stdout.write(JSON.stringify(results))
