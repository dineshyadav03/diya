import { forwardConnection } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/connections/{name}/clear-setup: forget what the page stored for a connector, and disconnect it.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardConnection(request, context, 'clear-setup')
