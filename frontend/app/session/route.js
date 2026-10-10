import { handleSession, newLoginState } from '../../server/ui-login.mjs'

// Signing in and out, and asking whether this browser is signed in (docs/UI_LOGIN_DESIGN.md). Not under app/api: that folder is
// the same-origin stand-in for the Python API, and this has nothing to do with it.
export const dynamic = 'force-dynamic'

const state = newLoginState() // the count of wrong passcodes lives as long as this server does

const handle = (request) => handleSession(request, process.env, state)
export const GET = handle
export const POST = handle
export const DELETE = handle
