import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/proactive/seen: these were looked at, so they are not shown again.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/proactive/seen')
