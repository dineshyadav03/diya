import { forwardThreadSearch } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/threads/search?q=...: the History page's search box. Only the search words are passed on.
export const dynamic = 'force-dynamic'
export const GET = (request) => forwardThreadSearch(request)
