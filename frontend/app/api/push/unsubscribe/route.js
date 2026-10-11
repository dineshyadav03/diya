import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/push/unsubscribe: this device asks to stop being told.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/push/unsubscribe')
