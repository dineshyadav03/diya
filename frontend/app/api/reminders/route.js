import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-ins for the API's GET /api/reminders (the pending reminders, each due, upcoming or with no
// time) and POST /api/reminders (a reminder the person types; the time is read on the API's side).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/reminders')
export const POST = (request) => forward(request, '/api/reminders')
