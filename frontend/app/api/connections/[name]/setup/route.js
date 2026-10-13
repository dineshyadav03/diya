import { forwardConnection } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/connections/{name}/setup: a connector's one-time setup form (Google's client ID and secret).
// What is sent is forwarded as it is and never read back.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardConnection(request, context, 'setup')
