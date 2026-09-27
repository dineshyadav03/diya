import { forward } from '../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/merge: move a person's facts onto another name
// (or back to no one in particular). No page calls this yet -- the route exists so the action is
// reachable (curl, or a future merge control) without a browser ever holding the access token.
export const dynamic = 'force-dynamic'
export const POST = (request) => forward(request, '/api/memory/merge')
