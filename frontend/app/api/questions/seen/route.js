import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/questions/seen: these questions were put in front of the person.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/questions/seen')
