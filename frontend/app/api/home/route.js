import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/home (the cards for today, found by code). Read only: a card's buttons call the routes that already exist.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/home')
