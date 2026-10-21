// Day separators for the chat (docs/ONE_CHAT_DESIGN.md, task DIYA-158): the one chat grows for months, so each message that has a time is shown under the person's own
// calendar day. A pure function, tested under Node (tests/test_day_labels.py) with fixed clocks and zones: easier to prove right in isolation than by rendering the page.
//
// "Day" means the day on the computer the page is open on, whatever zone the server stored the time in: a message saved at 20:30 UTC is the next morning in Mumbai.

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parse(iso) {
  if (typeof iso !== 'string') return null
  const moment = new Date(iso)
  return Number.isNaN(moment.getTime()) ? null : moment
}

function startOfDay(moment) {
  return new Date(moment.getFullYear(), moment.getMonth(), moment.getDate())
}

// A text that is the same for every moment of one local day and different for any other day, or null when `iso` is not a time.
export function dayKey(iso) {
  const moment = parse(iso)
  if (!moment) return null
  return `${moment.getFullYear()}-${String(moment.getMonth() + 1).padStart(2, '0')}-${String(moment.getDate()).padStart(2, '0')}`
}

// What a day is called: "Today", "Yesterday", "Mon 19 Oct" within this year, "Mon 19 Oct 2025" for another year. null when `iso` is not a time.
export function dayLabel(iso, now = new Date()) {
  const moment = parse(iso)
  if (!moment) return null
  const days = Math.round((startOfDay(now).getTime() - startOfDay(moment).getTime()) / 86400000)
  if (days === 0) return 'Today'
  if (days === 1) return 'Yesterday'
  const label = `${WEEKDAYS[moment.getDay()]} ${moment.getDate()} ${MONTHS[moment.getMonth()]}`
  return moment.getFullYear() === now.getFullYear() ? label : `${label} ${moment.getFullYear()}`
}

// For a list of messages ({ at } holding an ISO time, or no `at` at all), a list of the same length: the label of the day each one starts, or null where it is on the same day as the
// one before it. A message with no time never starts a day and never ends one, so it cannot split a day in two.
export function dayBreaks(messages, now = new Date()) {
  let last = null
  return messages.map((message) => {
    const key = dayKey(message && message.at)
    if (key === null) return null
    if (key === last) return null
    last = key
    return dayLabel(message.at, now)
  })
}
