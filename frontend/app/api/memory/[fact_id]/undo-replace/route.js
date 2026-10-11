import { forwardFactUndoReplace } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/{fact_id}/undo-replace (take a correction back); the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardFactUndoReplace(request, context)
