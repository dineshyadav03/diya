import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/push/subscribe: this device asks to be told by Web Push.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/push/subscribe')
