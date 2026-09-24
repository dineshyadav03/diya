import { forwardHistory } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/history/{thread_id}; the id must be a whole number.
export const dynamic = 'force-dynamic'
export const GET = (request, context) => forwardHistory(request, context)
