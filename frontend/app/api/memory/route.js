import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/memory: every fact, with its flags and the memory's size.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/memory')
