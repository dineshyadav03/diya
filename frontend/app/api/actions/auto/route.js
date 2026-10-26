import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/actions/auto: switch one kind of addition that touches only you to "do it straight away", or back to asking (docs/ACTIONS_DESIGN.md).
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/actions/auto')
