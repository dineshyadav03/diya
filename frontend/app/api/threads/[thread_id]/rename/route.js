import { forwardThreadRename } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/threads/{thread_id}/rename: the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardThreadRename(request, context)
