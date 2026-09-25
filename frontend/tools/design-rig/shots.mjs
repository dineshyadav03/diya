// Visual + contrast rig for Diya's frontend.
//
//   node shots.mjs <outDir> [scenarioNameFilter]
//
// Drives headless Edge over the DevTools protocol against the running dev server
// (default https://127.0.0.1:3000) with FIXED stub data, so runs are comparable and never
// touch the real backend, database or microphone. For every scenario and viewport it saves a
// PNG, audits the WCAG contrast of every visible text run, records page errors and horizontal
// overflow, and evaluates the scenario's `checks` (DOM assertions).
//
// Environment: BASE_URL, EDGE_PATH, CDP_PORT, VP=desktop,mobile,narrow (default desktop,mobile),
// VARIANT=flat (injects CSS that removes the elevation tokens, to compare against the shipped
// look), EXPECT_FAIL=1 (don't exit non-zero when a check fails -- for capturing a "before").
//
// Needs Node >= 22 (global WebSocket) and Microsoft Edge. Uses a throwaway browser profile.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const outDir = process.argv[2]
const only = process.argv[3]
if (!outDir) {
  console.error('usage: node shots.mjs <outDir> [scenarioNameFilter]')
  process.exit(2)
}
const BASE = process.env.BASE_URL || 'https://127.0.0.1:3000'
const EDGE = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const PORT = Number(process.env.CDP_PORT || 9333)
const VARIANT_CSS = { flat: ':root{--elev-1:transparent!important;--elev-2:transparent!important;--border:transparent!important}' }[process.env.VARIANT] || ''
fs.mkdirSync(outDir, { recursive: true })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const VIEWPORTS = {
  desktop: { w: 1280, h: 800, dsf: 1, mobile: false },
  mobile: { w: 375, h: 812, dsf: 2, mobile: true },
  narrow: { w: 320, h: 568, dsf: 2, mobile: true }, // smallest phones
}

// Sample data only -- nothing here is real user data.
const THREADS = [
  { id: 6, created_at: '2026-03-14T09:33:54+00:00', preview: 'Help me draft a polite email to my landlord about the broken heater and ask when it can be repaired' },
  { id: 5, created_at: '2026-03-12T14:36:01+00:00', preview: 'What did I say about my dentist?' },
  { id: 4, created_at: '2026-03-12T14:35:07+00:00', preview: "What's the weather in London?" },
  { id: 3, created_at: '2026-03-12T14:08:36+00:00', preview: 'Remind me to call mom tomorrow' },
  { id: 2, created_at: '2026-03-11T17:12:19+00:00', preview: '(empty thread)' },
  { id: 1, created_at: '2026-03-11T13:30:39+00:00', preview: 'hey' },
]

const CONVO = {
  'What did I say about my dentist?': { answer: 'You moved your dentist appointment to Thursday at 3pm, because the original slot conflicted with work.', tools_called: ['search_notes'] },
  "What's the weather in London?": { answer: 'London, England, United Kingdom: 14.2°C, light rain, wind 18 km/h.\n\nTake an umbrella.', tools_called: ['get_weather', 'add_reminder'] },
}

const LOAD_FAIL_CHECKS = [
  { name: 'the list is replaced by a "couldn\'t load" state', js: `/couldn.t load your chats/i.test(document.querySelector('.empty-state h2').textContent)` },
  { name: 'a "Try again" link is offered', js: `!!Array.from(document.querySelectorAll('.empty-state a')).find((a) => /try again/i.test(a.textContent))` },
  { name: 'no thread rows are shown', js: `document.querySelectorAll('.thread').length === 0` },
]

const FAIL_CHECKS = [
  { name: 'the failed message is marked as failed', js: `document.querySelectorAll('.msg.user.failed').length === 1` },
  { name: 'an alert explains it was not sent', js: `!!document.querySelector('.send-error[role="alert"]') && /didn.t send/i.test(document.querySelector('.send-error').textContent)` },
  { name: 'a "Try again" button is offered', js: `!!Array.from(document.querySelectorAll('.send-error button')).find((b) => /try again/i.test(b.textContent))` },
  { name: 'the thinking indicator is gone', js: `!document.querySelector('.thinking-row')` },
]

// name, path, stub config, steps (run in the page after hydration), checks (DOM assertions)
const SCENARIOS = [
  { name: 'chat-empty', path: '/', stub: {}, steps: [] },
  {
    name: 'chat-conversation', path: '/', stub: { replies: CONVO, mic: 'denied' },
    steps: [`await __send("What did I say about my dentist?")`, `await __send("What's the weather in London?")`, `await __micDown()`],
  },
  { name: 'chat-thinking', path: '/', stub: { chat: 'pending' }, steps: [`await __send("What's the weather in London?", 300)`] },
  { name: 'chat-typing', path: '/', stub: {}, steps: [`await __type("Remind me to call the dentist on Monday")`] },
  { name: 'chat-menu-open', path: '/', stub: {}, steps: [`document.querySelector('.mock-vchat-btn--liquid').click(); await __wait(900)`] },
  { name: 'chat-listening', path: '/', stub: { mic: 'ok' }, steps: [`await __micDown(700)`] },
  { name: 'chat-transcribing', path: '/', stub: { mic: 'ok' }, steps: [`await __micDown(700); await __micUp(600)`] },
  {
    name: 'chat-resume', path: '/',
    stub: { thread: '55', historyDelay: 1500, history: [{ role: 'user', content: 'earlier question' }, { role: 'assistant', content: 'earlier answer' }] },
    steps: [],
    checks: [
      { name: 'the empty state never flashed while the thread loaded', js: `window.__emptySeen === 0` },
      { name: 'the past messages are shown', js: `document.querySelectorAll('#log .msg').length === 2` },
    ],
  },
  { name: 'history-list', path: '/history', stub: { threads: THREADS }, steps: [] },
  { name: 'history-empty', path: '/history', stub: { threads: [] }, steps: [] },
  { name: 'history-loading', path: '/history', stub: { threads: 'pending' }, steps: [] },
  { name: 'history-error', path: '/history', stub: { threads: 'error' }, steps: [], checks: [...LOAD_FAIL_CHECKS, { name: 'nothing answered: it says the server did not answer', js: `/didn.t answer/i.test(document.querySelector('.empty-state p').textContent)` }] },
  // The API refuses the access token the UI sends: not "the server didn't answer", which is what
  // this page used to say for every failure.
  { name: 'history-unauthorized', path: '/history', stub: { threads: '401' }, steps: [], checks: [...LOAD_FAIL_CHECKS,
    { name: 'it says the access token is the problem', js: `/access token/i.test(document.querySelector('.empty-state p').textContent)` },
    { name: 'it does not claim the server did not answer', js: `!/didn.t answer/i.test(document.querySelector('.empty-state p').textContent)` }] },
  { name: 'history-server-error', path: '/history', stub: { threads: '500' }, steps: [], checks: [...LOAD_FAIL_CHECKS,
    { name: 'an error status is reported as an error, with its number', js: `/HTTP 500/.test(document.querySelector('.empty-state p').textContent)` }] },

  // ---- send failures ----
  {
    name: 'chat-send-failed', path: '/', stub: { replies: CONVO },
    steps: [`await __send("What did I say about my dentist?")`, `window.__chatMode = 'down'`, `await __send("Remind me to call the dentist on Monday")`],
    checks: [
      ...FAIL_CHECKS,
      { name: 'the earlier successful exchange is untouched', js: `document.querySelectorAll('.msg.assistant:not(.thinking-row)').length === 1` },
      { name: 'a request that got no answer says the server did not answer', js: `/didn.t answer/i.test(document.querySelector('.send-error').textContent)` },
    ],
  },
  {
    // The API refuses the access token the UI sends (missing or wrong): that is not "the server
    // didn't answer", and used to be reported as if it were.
    name: 'chat-send-failed-401', path: '/', stub: {},
    steps: [`window.__chatMode = '401'`, `await __send("Remind me to call the dentist on Monday")`],
    checks: [
      ...FAIL_CHECKS,
      { name: 'it says the access token is the problem', js: `/access token/i.test(document.querySelector('.send-error').textContent)` },
      { name: 'it does not claim the server did not answer', js: `!/didn.t answer/i.test(document.querySelector('.send-error').textContent)` },
    ],
  },
  {
    name: 'chat-send-failed-500', path: '/', stub: {},
    steps: [`window.__chatMode = '500'`, `await __send("Remind me to call the dentist on Monday")`],
    checks: [
      ...FAIL_CHECKS,
      { name: 'an error status is reported as an error, with its number', js: `/HTTP 500/.test(document.querySelector('.send-error').textContent)` },
      { name: 'no empty assistant bubble is shown', js: `!Array.from(document.querySelectorAll('.msg.assistant:not(.thinking-row)')).some((m) => !m.textContent.trim())` },
      { name: 'the saved thread id is not corrupted ("undefined")', js: `localStorage.getItem('diya_thread_id') !== 'undefined'` },
    ],
  },
  {
    name: 'chat-send-retry', path: '/', stub: { replies: CONVO },
    steps: [
      `window.__chatMode = 'down'`, `await __send("What did I say about my dentist?")`,
      `window.__chatMode = 'ok'`, `document.querySelector('.send-error button').click(); await __wait(1300)`,
    ],
    checks: [
      { name: 'no message is left marked failed', js: `document.querySelectorAll('.msg.failed').length === 0` },
      { name: 'the error row is gone', js: `!document.querySelector('.send-error')` },
      { name: 'the answer arrived', js: `Array.from(document.querySelectorAll('.msg.assistant')).some((m) => /Thursday at 3pm/.test(m.textContent))` },
      { name: 'the message was not duplicated', js: `document.querySelectorAll('.msg.user').length === 1` },
    ],
  },
  {
    name: 'chat-send-retry-still-down', path: '/', stub: {},
    steps: [`window.__chatMode = 'down'`, `await __send("Remind me to call the dentist on Monday")`, `document.querySelector('.send-error button').click(); await __wait(900)`],
    checks: [
      { name: 'the message is failed again', js: `document.querySelectorAll('.msg.user.failed').length === 1` },
      { name: 'exactly one error row (not stacked)', js: `document.querySelectorAll('.send-error').length === 1` },
      { name: 'the message was not duplicated', js: `document.querySelectorAll('.msg.user').length === 1` },
    ],
  },
  {
    name: 'chat-transcribe-failed', path: '/', stub: { mic: 'ok', tx: 'down' },
    steps: [`await __micDown(700); await __micUp(1500)`],
    checks: [
      { name: 'the mic button is usable again (not stuck disabled)', js: `!document.querySelector('button[aria-label="Hold to talk"]').disabled` },
      { name: 'the "Transcribing..." chip is gone', js: `!document.querySelector('.mic-status')` },
      { name: 'a message says the server could not be reached', js: `Array.from(document.querySelectorAll('.msg.system')).some((m) => /couldn.t reach diya.s server/i.test(m.textContent))` },
    ],
  },
  {
    // The API refuses the access token: the microphone must not say the server couldn't be reached.
    name: 'chat-transcribe-unauthorized', path: '/', stub: { mic: 'ok', tx: '401' },
    steps: [`await __micDown(700); await __micUp(1500)`],
    checks: [
      { name: 'the mic button is usable again (not stuck disabled)', js: `!document.querySelector('button[aria-label="Hold to talk"]').disabled` },
      { name: 'the "Transcribing..." chip is gone', js: `!document.querySelector('.mic-status')` },
      { name: 'a message says the access token is the problem', js: `Array.from(document.querySelectorAll('.msg.system')).some((m) => /access token/i.test(m.textContent))` },
      { name: 'no message claims the server could not be reached', js: `!Array.from(document.querySelectorAll('.msg.system')).some((m) => /couldn.t reach/i.test(m.textContent))` },
    ],
  },
  {
    name: 'chat-transcribe-server-error', path: '/', stub: { mic: 'ok', tx: '500' },
    steps: [`await __micDown(700); await __micUp(1500)`],
    checks: [
      { name: 'the mic button is usable again (not stuck disabled)', js: `!document.querySelector('button[aria-label="Hold to talk"]').disabled` },
      { name: 'an error status is reported as an error, with its number', js: `Array.from(document.querySelectorAll('.msg.system')).some((m) => /HTTP 500/.test(m.textContent))` },
    ],
  },
]

// ---- injected before the app runs: stub the network + microphone, define helpers ----
const stubSource = (stub) => `(() => {
  const sc = ${JSON.stringify(stub)};
  window.__chatMode = sc.chat || 'ok';   // ok | pending | down (network error) | 500
  window.__txMode = sc.tx || 'pending';  // pending | down | ok
  const rf = window.fetch.bind(window);
  const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'Content-Type': 'application/json' } });
  window.fetch = (url, opts) => {
    const u = String(url);
    const refused = () => new Response('Missing or invalid access token', { status: 401, headers: { 'Content-Type': 'text/plain' } });
    if (u.includes('/api/threads')) return sc.threads === 'pending' ? new Promise(() => {}) : sc.threads === 'error' ? Promise.reject(new TypeError('Failed to fetch')) : sc.threads === '401' ? Promise.resolve(refused()) : sc.threads === '500' ? Promise.resolve(json({ detail: 'Internal Server Error' }, 500)) : Promise.resolve(json({ threads: sc.threads || [] }));
    if (u.includes('/api/history/')) return new Promise((r) => setTimeout(() => r(json({ messages: sc.history || [] })), sc.historyDelay || 0));
    if (u.includes('/api/transcribe')) return window.__txMode === 'down' ? Promise.reject(new TypeError('Failed to fetch')) : window.__txMode === '401' ? Promise.resolve(refused()) : window.__txMode === '500' ? Promise.resolve(json({ detail: 'Internal Server Error' }, 500)) : window.__txMode === 'ok' ? Promise.resolve(json({ text: 'what is on my list today' })) : new Promise(() => {});
    if (u.includes('/api/chat')) {
      const mode = window.__chatMode;
      if (mode === 'pending') return new Promise(() => {});
      if (mode === 'down') return Promise.reject(new TypeError('Failed to fetch'));
      if (mode === '500') return Promise.resolve(json({ detail: 'Internal Server Error' }, 500));
      if (mode === '401') return Promise.resolve(new Response('Missing or invalid access token', { status: 401, headers: { 'Content-Type': 'text/plain' } }));
      const msg = JSON.parse(opts.body).message;
      return Promise.resolve(json({ thread_id: 7, ...((sc.replies || {})[msg] || { answer: 'OK', tools_called: [] }) }));
    }
    return rf(url, opts);
  };
  if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = sc.mic === 'ok'
    ? async () => { const ac = new AudioContext(); const d = ac.createMediaStreamDestination(); const o = ac.createOscillator(); o.connect(d); o.start(); return d.stream; }
    : async () => { throw new Error('Permission denied'); };
  if (sc.thread) localStorage.setItem('diya_thread_id', sc.thread);
  window.__emptySeen = 0; setInterval(() => { if (document.querySelector('.empty-state')) window.__emptySeen++; }, 20);
  // Next's dev-only "N" badge is tooling, not UI; keep it out of the screenshots (and any variant CSS).
  document.addEventListener('DOMContentLoaded', () => {
    const s = document.createElement('style');
    s.textContent = 'nextjs-portal{display:none!important}' + ${JSON.stringify(VARIANT_CSS)};
    document.head.appendChild(s);
  });
  window.__wait = (ms) => new Promise((r) => setTimeout(r, ms));
  window.__type = async (text) => {
    const input = document.querySelector('.mock-vchat-input');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, text);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await __wait(700);
  };
  window.__send = async (text, settle = 900) => {
    await __type(text);
    document.querySelector('form.mock-vchat').requestSubmit();
    await __wait(settle);
  };
  const mic = () => document.querySelector('button[aria-label="Hold to talk"]');
  window.__micDown = async (settle = 600) => { mic().dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); await __wait(settle); };
  window.__micUp = async (settle = 600) => { mic().dispatchEvent(new PointerEvent('pointerup', { bubbles: true })); await __wait(settle); };
})();`

// ---- WCAG contrast audit of every visible text run (runs in the page) ----
const AUDIT = `(() => {
  const parse = (c) => { const m = c && c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const over = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const bgOf = (el) => { const layers = []; for (let n = el; n; n = n.parentElement) { const c = parse(getComputedStyle(n).backgroundColor); if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; } } let base = { r: 255, g: 255, b: 255, a: 1 }; for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base); return base; };
  const effOpacity = (el) => { let o = 1; for (let n = el; n; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return o; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const hex = (c) => '#' + [c.r, c.g, c.b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
  const out = [];
  const add = (el, fgCss, text, kind) => {
    const cs = getComputedStyle(el); const bg = bgOf(el); let fg = parse(fgCss); if (!fg || fg.a === 0) return; /* fully transparent text (e.g. the placeholder hidden under the mic chip) is invisible, not a contrast target */ fg = over(fg, bg);
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700); const need = large ? 3 : 4.5; const r = ratio(fg, bg);
    out.push({ kind, tag: el.tagName.toLowerCase(), cls: (el.className && el.className.baseVal === undefined ? el.className : '').toString().slice(0, 40), text: text.trim().slice(0, 34), fg: hex(fg), bg: hex(bg), size, ratio: Math.round(r * 100) / 100, need, pass: r >= need });
  };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const t = n.nodeValue; if (!t.trim()) continue; const el = n.parentElement; if (!el || ['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName)) continue;
    const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none' || !el.getClientRects().length || effOpacity(el) < 0.05) continue;
    add(el, cs.color, t, 'text');
  }
  for (const el of document.querySelectorAll('input[placeholder]')) { if (el.value) continue; add(el, getComputedStyle(el, '::placeholder').color, el.placeholder, 'placeholder'); }
  return out;
})()`

// ---- minimal CDP client ----
async function main() {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'diya-rig-'))
  const edge = spawn(EDGE, [
    '--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*', `--user-data-dir=${userData}`,
    '--ignore-certificate-errors', '--hide-scrollbars', '--mute-audio', '--autoplay-policy=no-user-gesture-required',
    '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--enable-webgl', '--ignore-gpu-blocklist', 'about:blank',
  ], { stdio: 'ignore' })
  let failedChecks = 0
  try {
    let ver
    for (let i = 0; i < 60; i++) { try { ver = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json(); break } catch { await sleep(300) } }
    if (!ver) throw new Error('Edge did not start')
    const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json()
    const ws = new WebSocket(target.webSocketDebuggerUrl)
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
    let id = 0
    const pending = new Map()
    const waiters = []
    const pageErrors = []
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data)
      if (m.method === 'Runtime.exceptionThrown') pageErrors.push((m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text || '').split(String.fromCharCode(10)).slice(0, 4).join(' | '))
      if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') pageErrors.push('console.error: ' + m.params.args.map((a) => a.value || a.description || '').join(' ').slice(0, 300))
      if (m.id && pending.has(m.id)) { const { res, rej } = pending.get(m.id); pending.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result) }
      else if (m.method) waiters.filter((w) => w.method === m.method).forEach((w) => w.res(m.params))
    }
    const send = (method, params = {}) => new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })) })
    const once = (method) => new Promise((res) => waiters.push({ method, res }))
    const evalJs = async (expression) => {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
      if (r.exceptionDetails) throw new Error('page error: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text))
      return r.result.value
    }
    await send('Page.enable'); await send('Runtime.enable')

    const summary = {}
    const wantVp = process.env.VP ? process.env.VP.split(',') : ['desktop', 'mobile']
    for (const vpName of wantVp) {
      const vp = VIEWPORTS[vpName]
      await send('Emulation.setDeviceMetricsOverride', { width: vp.w, height: vp.h, deviceScaleFactor: vp.dsf, mobile: vp.mobile })
      await send('Emulation.setTouchEmulationEnabled', { enabled: vp.mobile })
      for (const sc of SCENARIOS) {
        if (only && !sc.name.includes(only)) continue
        if ((process.env.SKIP || '').split(',').filter(Boolean).some((s) => sc.name.includes(s))) continue
        await send('Storage.clearDataForOrigin', { origin: BASE, storageTypes: 'local_storage,session_storage' })
        const { identifier } = await send('Page.addScriptToEvaluateOnNewDocument', { source: stubSource(sc.stub) })
        const loaded = once('Page.loadEventFired')
        await send('Page.navigate', { url: BASE + sc.path })
        await loaded
        await sleep(3500) // hydration + dynamic imports (metal-fx, effects)
        for (const step of sc.steps) {
          try { await evalJs(`(async () => { ${step} })()`) } catch (e) { console.log('   STEP ERROR:', String(e.message).slice(0, 160)); break }
        }
        await sleep(1500)
        const checks = []
        for (const c of sc.checks || []) {
          let ok = false
          try { ok = !!(await evalJs(`(async () => (${c.js}))()`)) } catch { ok = false }
          checks.push({ name: c.name, ok })
          if (!ok) failedChecks++
        }
        const audit = await evalJs(AUDIT)
        const shot = await send('Page.captureScreenshot', { format: 'png' })
        const file = `${sc.name}.${vpName}.png`
        fs.writeFileSync(path.join(outDir, file), Buffer.from(shot.data, 'base64'))
        const overflow = await evalJs(`({ sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth })`)
        const errs = pageErrors.splice(0)
        summary[`${sc.name}.${vpName}`] = { audit, horizontalOverflow: overflow.sw > overflow.cw, pageErrors: errs, checks }
        const fails = audit.filter((a) => !a.pass)
        console.log(`${file.padEnd(42)} text runs ${String(audit.length).padStart(2)}  contrast fails ${fails.length}${overflow.sw > overflow.cw ? '  H-OVERFLOW' : ''}${errs.length ? `  page errors ${errs.length}` : ''}`)
        for (const e of errs) console.log('   PAGE ERROR:', e.slice(0, 240))
        for (const c of checks) console.log(`   CHECK ${c.ok ? 'PASS' : 'FAIL'}  ${c.name}`)
        await send('Page.removeScriptToEvaluateOnNewDocument', { identifier })
      }
    }
    fs.writeFileSync(path.join(outDir, 'audit.json'), JSON.stringify(summary, null, 1))
    ws.close()
  } finally {
    edge.kill()
    await sleep(500)
    try { fs.rmSync(userData, { recursive: true, force: true }) } catch {}
  }
  if (failedChecks) {
    console.log(`\n${failedChecks} check(s) failed`)
    if (!process.env.EXPECT_FAIL) process.exit(1)
  }
}
main().catch((e) => { console.error('FAILED:', e); process.exit(1) })
