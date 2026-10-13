import { forward } from '../../../lib/proxy.mjs'

// Same-origin stand-in for the API's GET /api/knowledge (the pages made from the person's notes, docs/KNOWLEDGE_DESIGN.md).
export const dynamic = 'force-dynamic'
export const GET = (request) => forward(request, '/api/knowledge')
