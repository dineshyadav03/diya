import { forwardLearned } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/memory/learned?message_id=N; the id must be a whole number.
export const dynamic = 'force-dynamic'
export const GET = (request) => forwardLearned(request)
