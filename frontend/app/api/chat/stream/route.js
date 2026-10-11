import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/chat/stream: forwards it, with the access token, from here, and hands the answer back as it arrives (forward() passes the body through
// unread), so the page can show a reply as it is written.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/chat/stream')
