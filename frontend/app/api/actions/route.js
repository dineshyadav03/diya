import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/actions: what is waiting for the owner, what was decided or
// finished, the counts, and which kinds of action Diya can propose at all.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/actions')
