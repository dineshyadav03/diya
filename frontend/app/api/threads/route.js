import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/threads.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/threads')
