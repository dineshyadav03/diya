import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/feedback (what the person thinks of each reply: list, put, delete; docs/FEEDBACK_DESIGN.md).
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/feedback')
