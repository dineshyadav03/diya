import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-ins for the API's GET /api/categories (the categories, and where the newest messages of the one chat are) and
// POST /api/categories (move a message, add or rename a category; docs/ONE_CHAT_DESIGN.md).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/categories')
export const POST = (request) => forward(request, '/api/categories')
