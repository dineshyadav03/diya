import { forwardFactPurge } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/memory/{fact_id}/forget-for-good (take a fact's words out for good; docs/FORGET_DESIGN.md); the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardFactPurge(request, context)
