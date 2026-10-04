import { forwardActionDecision } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/actions/{action_id}/resolve: what the owner found for an action whose
// outcome was unknown. The id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardActionDecision(request, context, 'resolve')
