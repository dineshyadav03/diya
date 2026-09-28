import { forwardConnection } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/connections/{name}/disconnect: removes a connector's
// stored credential (idempotent).
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardConnection(request, context, 'disconnect')
