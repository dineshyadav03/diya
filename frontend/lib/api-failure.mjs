// Why a call to the API didn't work, in words the person can act on -- one message per place the
// UI shows one: sending a chat message, loading the list of past chats, transcribing a recording.
//
// The browser only ever hears from the UI's own server (app/api), so the HTTP status is the whole
// story: 401 means the API refused the access token the UI server sends (missing or wrong); no
// status at all, or 502/503/504, means nothing answered; any other status is an error the API or the
// UI server reported. These used to be one fixed message each, "Diya's server didn't answer", which
// sent someone with a missing token looking for a server that was running fine.
//
// This is browser code: it names no token, address or setting (tests/test_frontend_proxy.py scans it
// for exactly that), so the 401 message points at docs/lan.md instead of spelling out how to fix it.
// Each function keeps its place's existing wording for the "nothing answered" case, which is true.

const REFUSED = 'the access token the UI sends is missing or wrong (see docs/lan.md, Access token)'
const SIGNED_OUT = 'You’re signed out of Diya. Reload this page to sign in again.'

// 'unreachable' | 'unauthorized' | 'signin' | 'unreadable' | 'error'. A status that is not an integer (NaN
// included: it has type "number") counts as no answer. 511 is the UI's own sign-in (docs/UI_LOGIN_DESIGN.md): this
// browser is not signed in to Diya, which is nothing to do with the API's access token (401).
function classify(status) {
  if (!Number.isInteger(status) || status === 502 || status === 503 || status === 504) return 'unreachable'
  if (status === 401) return 'unauthorized'
  if (status === 511) return 'signin'
  if (status >= 200 && status < 300) return 'unreadable'
  return 'error'
}

// What a failed chat call said, when the API said anything: the reason it gave (`detail`, in words for a person) and
// the chat it kept the message in (`thread_id`; the first message of a new chat has no id until the server answers).
// `body` is the parsed JSON of the error response, or null when it had none.
export function readFailure(body) {
  const detail = typeof body?.detail === 'string' && body.detail.trim() ? body.detail.trim().slice(0, 300) : undefined
  const threadId = Number.isInteger(body?.thread_id) ? body.thread_id : undefined
  return { detail, threadId }
}

// The chat's red row under a message that was not answered. Without a reason from the API every text starts "Didn't
// send." because the design rig's checks look for it. With one, the API did answer (it kept the message and could not
// reply), so the row says "No reply." and gives the reason as the API worded it; a refused token (401) keeps its own text.
export function describeSendFailure(status, detail) {
  if (typeof detail === 'string' && detail && Number.isInteger(status) && status >= 400 && status !== 401 && status !== 511) {
    return `No reply. ${detail}`
  }
  switch (classify(status)) {
    case 'unreachable':
      return 'Didn’t send. Diya’s server didn’t answer.'
    case 'unauthorized':
      return `Didn’t send. Diya’s server refused it: ${REFUSED}.`
    case 'signin':
      return `Didn’t send. ${SIGNED_OUT}`
    case 'unreadable':
      return 'Didn’t send. Diya’s server sent back something this page couldn’t read.'
    default:
      return `Didn’t send. Diya’s server answered with an error (HTTP ${status}).`
  }
}

// The sentence under a "Couldn't load ..." headline: the History page's list of chats, and a saved
// chat that the chat page could not open.
export function describeLoadFailure(status) {
  switch (classify(status)) {
    case 'unreachable':
      return 'Diya’s server didn’t answer. Check that it’s running, then try again.'
    case 'unauthorized':
      return `Diya’s server refused the request: ${REFUSED}.`
    case 'signin':
      return SIGNED_OUT
    case 'unreadable':
      return 'Diya’s server sent back something this page couldn’t read.'
    default:
      return `Diya’s server answered with an error (HTTP ${status}).`
  }
}

// The system message in the chat after a recording could not be transcribed (straight apostrophes,
// like the other system messages the microphone writes).
export function describeTranscribeFailure(status) {
  switch (classify(status)) {
    case 'unreachable':
      return "Couldn't reach Diya's server to transcribe that. Hold the mic to try again."
    case 'unauthorized':
      return `Couldn't transcribe that: Diya's server refused it, because ${REFUSED}. Hold the mic to try again.`
    case 'signin':
      return "Couldn't transcribe that: you're signed out of Diya. Reload this page to sign in again."
    case 'unreadable':
      return "Couldn't transcribe that: Diya's server sent back something this page couldn't read. Hold the mic to try again."
    default:
      return `Couldn't transcribe that: Diya's server answered with an error (HTTP ${status}). Hold the mic to try again.`
  }
}

// The red line on the memory page when something the person asked for -- accept, reject, edit, add, check
// for new facts -- was not carried out. Each text makes that clear, because it is true of a refusal.
//
// The API refuses with a reason in `detail` (404 no such fact, 409 it doesn't apply or would repeat or
// overflow the memory, 422 text that may not be stored). That reason is already in words for a person, so
// it is shown as it is; a detail that is not a plain string (a validation error list) is not.
export function describeActionFailure(status, detail) {
  const reason = typeof detail === 'string' && detail.trim() ? detail.trim() : ''
  switch (classify(status)) {
    case 'unreachable':
      return 'Diya’s server didn’t answer, so nothing was changed. Check that it’s running, then try again.'
    case 'unauthorized':
      return `Diya’s server refused it, so nothing was changed: ${REFUSED}.`
    case 'signin':
      return `${SIGNED_OUT} Nothing was changed.`
    case 'unreadable':
      return 'Diya’s server sent back something this page couldn’t read. Refresh to see what it did.'
    default:
      return reason
        ? `Not done: ${reason}${/[.!?]$/.test(reason) ? '' : '.'}`
        : `Diya’s server answered with an error (HTTP ${status}), so nothing was changed.`
  }
}
