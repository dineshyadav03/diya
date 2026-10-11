import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/questions: the questions that may be put in front of the person now.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/questions')
