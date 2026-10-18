import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/dreaming (what Dreaming's scheduled passes read and did; docs/DREAMING_RECEIPTS_DESIGN.md). Read-only: there is no other method.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/dreaming')
