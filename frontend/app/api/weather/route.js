import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-ins for the API's GET /api/weather (the weather where the person shared their place), POST (the place, from the browser) and DELETE (forget it).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/weather')
export const POST = (request) => forward(request, '/api/weather')
export const DELETE = (request) => forward(request, '/api/weather')
