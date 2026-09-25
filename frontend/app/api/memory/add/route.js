import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/add: a fact typed by the person.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/memory/add')
