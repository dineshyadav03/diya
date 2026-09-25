import { forwardFact } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/memory/{fact_id}; the id must be a whole number.
export const dynamic = 'force-dynamic'
export const GET = (request, context) => forwardFact(request, context)
