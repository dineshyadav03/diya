import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/transcribe (the audio upload).
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/transcribe')
