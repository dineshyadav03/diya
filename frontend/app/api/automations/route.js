import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-ins for the API's GET /api/automations (what Diya does on a schedule) and POST /api/automations (one the person types;
// the sentence is read on the API's side, exactly as the chat reads it).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/automations')
export const POST = (request) => forward(request, '/api/automations')
