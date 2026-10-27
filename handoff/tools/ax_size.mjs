// How big is a web page to a text-only agent? Opens a few PUBLIC pages in the installed Edge (headless, a throwaway profile) and measures the accessibility tree a browser-control tool
// would hand to a model, written compactly as one line per useful element. Reads only; nothing is typed, clicked or signed in.
import { spawn } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const EDGE = process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'
const PAGES = ['https://example.com', 'https://github.com/login', 'https://en.wikipedia.org/wiki/Main_Page', 'https://www.amazon.in', 'https://www.irctc.co.in']
const port = 9333
const profile = mkdtempSync(join(tmpdir(), 'ax-'))
const edge = spawn(EDGE, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--headless=new', '--disable-gpu', '--no-first-run', 'about:blank'], { stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function pageSocket() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json()
      const page = list.find((t) => t.type === 'page')
      if (page) return new WebSocket(page.webSocketDebuggerUrl)
    } catch {}
    await sleep(250)
  }
  throw new Error('no browser')
}

const ws = await pageSocket()
await new Promise((r) => (ws.onopen = r))
let id = 0
const waiting = new Map()
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data)
  if (msg.id && waiting.has(msg.id)) waiting.get(msg.id)(msg.result || msg.error)
}
const send = (method, params = {}) => new Promise((r) => { const n = ++id; waiting.set(n, r); ws.send(JSON.stringify({ id: n, method, params })) })

await send('Page.enable')
for (const url of PAGES) {
  const t0 = Date.now()
  await send('Page.navigate', { url })
  await sleep(6000)
  const tree = await send('Accessibility.getFullAXTree')
  const nodes = (tree && tree.nodes) || []
  const lines = []
  for (const n of nodes) {
    if (n.ignored) continue
    const role = n.role && n.role.value
    const name = n.name && n.name.value
    if (!role || ['none', 'generic', 'InlineTextBox', 'LineBreak'].includes(role)) continue
    if (!name && !['textbox', 'button', 'link', 'checkbox', 'combobox'].includes(role)) continue
    lines.push(`- ${role} "${String(name || '').slice(0, 120)}"`)
  }
  const chars = lines.join('\n').length
  const interactive = lines.filter((l) => /^- (button|link|textbox|checkbox|combobox|menuitem|tab|radio|searchbox)/.test(l)).length
  console.log(`${url.padEnd(42)} nodes ${String(nodes.length).padStart(5)}  lines ${String(lines.length).padStart(4)}  interactive ${String(interactive).padStart(4)}  ~${Math.round(chars / 3.5)} tokens  (${Date.now() - t0} ms)`)
}
ws.close()
edge.kill()
process.exit(0)
