import { forwardTaskAction } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/tasks/{task_id}/done: the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardTaskAction(request, context, 'done')
