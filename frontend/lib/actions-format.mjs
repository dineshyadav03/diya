// How the Actions page words things (docs/ACTIONS_DESIGN.md, unit A3): which tools ran before a proposal, how long
// a proposal has left, and what each status means in plain words. Pure functions, tested under Node
// (tests/test_actions_format.py), the same way frontend/lib/memory-groups.mjs is -- easier to prove right in
// isolation than by rendering the page.

// The words for each tool a proposal can have come after. A tool this table does not know is shown by its own
// name with the underscores taken out, never hidden: the owner is told what was read, not what is convenient.
const SOURCE_WORDS = {
  web_search: 'the web',
  get_weather: 'the weather service',
  search_notes: 'your notes',
  list_files: 'your files',
  search_home_assistant: 'Home Assistant',
  search_notion: 'Notion',
  list_todoist_tasks: 'Todoist',
  list_calendar_events: 'Google Calendar',
}

export function sourceWords(names) {
  const words = [...new Set((names || []).map((name) => SOURCE_WORDS[name] || String(name).replace(/_/g, ' ')))]
  if (words.length <= 1) return words.join('')
  return `${words.slice(0, -1).join(', ')} and ${words[words.length - 1]}`
}

// "expires in 23 h 5 min" / "expires in 42 min" / "expired". An unreadable time says nothing rather than guess.
export function timeLeft(expiresAt, now = Date.now()) {
  const left = Date.parse(expiresAt) - now
  if (!Number.isFinite(left)) return ''
  if (left <= 0) return 'expired'
  const minutes = Math.ceil(left / 60000)
  if (minutes < 60) return `expires in ${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `expires in ${hours} h ${rest} min` : `expires in ${hours} h`
}

const STATUS_WORDS = {
  pending: 'Waiting for you',
  approved: 'Approved, not run yet',
  executing: 'Running',
  succeeded: 'Done',
  failed: 'Failed',
  rejected: 'Turned down',
  expired: 'Expired, not done',
  unknown: 'Outcome unknown',
}

export function statusWords(status) {
  return STATUS_WORDS[status] || String(status)
}
