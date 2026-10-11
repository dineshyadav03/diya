import { forwardFactReplace } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/{fact_id}/replace (accept a waiting fact and retire the accepted one it replaces, together);
// the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardFactReplace(request, context)
