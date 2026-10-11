import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/push/test: one notification that says nothing about the person, to every subscribed device.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/push/test')
