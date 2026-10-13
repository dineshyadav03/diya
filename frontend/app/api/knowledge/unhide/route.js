import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/knowledge/unhide: {"name": ...}, make that name's page again from the next build.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/knowledge/unhide')
