import { forwardQuestionAnswer } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/questions/{question_id}/answer; the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardQuestionAnswer(request, context)
