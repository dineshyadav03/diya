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

// 'unreachable' | 'unauthorized' | 'unreadable' | 'error'. A status that is not an integer (NaN
// included: it has type "number") counts as no answer.
function classify(status) {
  if (!Number.isInteger(status) || status === 502 || status === 503 || status === 504) return 'unreachable'
  if (status === 401) return 'unauthorized'
  if (status >= 200 && status < 300) return 'unreadable'
  return 'error'
}

// The chat's red "Didn't send" row under a message. Every text starts "Didn't send." because the
// design rig's checks look for it.
export function describeSendFailure(status) {
  switch (classify(status)) {
    case 'unreachable':
      return 'Didn’t send. Diya’s server didn’t answer.'
    case 'unauthorized':
      return `Didn’t send. Diya’s server refused it: ${REFUSED}.`
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
    case 'unreadable':
      return "Couldn't transcribe that: Diya's server sent back something this page couldn't read. Hold the mic to try again."
    default:
      return `Couldn't transcribe that: Diya's server answered with an error (HTTP ${status}). Hold the mic to try again.`
  }
}
