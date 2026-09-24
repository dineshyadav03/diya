import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/chat: forwards it, with the access token, from here.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/chat')
