import { forwardScheduledAction } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/scheduled/{series_id}/skip: the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardScheduledAction(request, context, 'skip')
