import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/connections/connect-google: every Google card in one sign-in (the call waits for the owner to finish in their browser).
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/connections/connect-google')
