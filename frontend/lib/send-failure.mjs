// Why a chat message didn't go through, in words the person can act on.
//
// The browser only ever hears from the UI's own server (app/api/chat), so the HTTP status is the
// whole story: 401 means the API refused the access token the UI server sends (missing or wrong);
// no status at all, or 502/503/504, means nothing answered; any other status is an error the API
// or the UI server reported. It used to be one message for all of them, "Diya's server didn't
// answer", which sent someone with a missing token looking for a server that was running fine.
//
// Every message starts "Didn't send." (the design rig's checks look for it). This is browser code:
// it names no token, address or setting (tests/test_frontend_proxy.py scans it for exactly that),
// so the 401 message points at docs/lan.md instead of spelling out how to set the token.

const DIDNT_ANSWER = 'Didn’t send. Diya’s server didn’t answer.'

export function describeSendFailure(status) {
  if (!Number.isInteger(status) || status === 502 || status === 503 || status === 504) return DIDNT_ANSWER
  if (status === 401) {
    return 'Didn’t send. Diya’s server refused it: the access token the UI sends is missing or wrong (see docs/lan.md, “Access token”).'
  }
  if (status >= 200 && status < 300) return 'Didn’t send. Diya’s server sent back something this page couldn’t read.'
  return `Didn’t send. Diya’s server answered with an error (HTTP ${status}).`
}
