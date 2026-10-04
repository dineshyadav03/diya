import { forwardAction } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/actions/{action_id}: one action, the message it came from and its
// history. The id must be a whole number.
export const dynamic = 'force-dynamic'
export const GET = (request, context) => forwardAction(request, context)
