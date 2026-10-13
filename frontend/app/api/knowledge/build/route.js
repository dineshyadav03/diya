import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/knowledge/build: read the notes folder now and write the pages (no model, no network).
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/knowledge/build')
