import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-ins for the API's GET /api/scheduled (the repeating reminders, what happened lately and the counts)
// and POST /api/scheduled (a repeating reminder the person types; the repeat is read on the API's side).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/scheduled')
export const POST = (request) => forward(request, '/api/scheduled')
