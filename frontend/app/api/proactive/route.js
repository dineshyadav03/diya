import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/proactive: what Diya wrote first and the person has not looked at yet.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/proactive')
