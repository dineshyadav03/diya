import { forwardActionDecision } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/actions/{action_id}/approve: the body carries the hash of what the
// page showed, so an action changed since is refused. The id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardActionDecision(request, context, 'approve')
