import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/playbooks (the steps the person wrote, and any file that cannot be used, docs/PLAYBOOKS_DESIGN.md). Read-only: there is no other method.
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/playbooks')
