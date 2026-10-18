import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/journal (what Diya did with a tool or an account; docs/ACTIVITY_JOURNAL_DESIGN.md). Read-only: there is no other method.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/journal')
