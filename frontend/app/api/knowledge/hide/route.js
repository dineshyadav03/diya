import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/knowledge/hide: {"name": ...}, remove that name's page and never make it again.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/knowledge/hide')
