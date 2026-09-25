import { forwardFactAction } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/{fact_id}/{action}: the id must be a whole number and
// the action one the API has (accept, reject, reopen, retire, restore, edit).
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardFactAction(request, context)
