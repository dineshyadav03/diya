import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/permissions (what each connection can do, since when, when last used; docs/PERMISSIONS_DESIGN.md). Read-only: there is no other method.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/permissions')
