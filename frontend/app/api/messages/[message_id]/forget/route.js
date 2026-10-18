import { forwardMessageForget } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/messages/{message_id}/forget (delete one of the person's messages and Diya's reply, and what was learned from it; docs/FORGET_DESIGN.md);
// the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardMessageForget(request, context)
