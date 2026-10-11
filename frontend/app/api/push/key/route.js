import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/push/key: the public application server key the browser subscribes with.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/push/key')
