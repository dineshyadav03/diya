import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/today (what is due now and later today, the tasks overdue or due today, and
// the repeating reminders that will make one next). Read only: there is nothing to change here.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/today')
