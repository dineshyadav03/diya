import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-ins for the API's GET /api/tasks (the open tasks, the finished ones and the counts) and
// POST /api/tasks (a task the person types; the date is read on the API's side).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/tasks')
export const POST = (request) => forward(request, '/api/tasks')
