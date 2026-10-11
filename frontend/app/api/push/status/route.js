import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/push/status: whether Web Push is on, why not, and which devices are subscribed (never an endpoint or a key).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/push/status')
