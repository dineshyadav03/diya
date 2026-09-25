import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/ingest: copy newly staged facts in and check them.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/memory/ingest')
