import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/pause (the kill switch: stop Diya acting on her own; docs/PAUSE_DESIGN.md).
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/pause')
