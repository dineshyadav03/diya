import { forwardConnection } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/connections/{name}/connect: a token-kind connector's
// pasted-token form.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardConnection(request, context, 'connect')
