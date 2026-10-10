import { forwardReminderSnooze } from '../../../../../lib/proxy.mjs'

// Same-origin stand-in for the API's POST /api/reminders/{reminder_id}/snooze: the id must be a whole number.
export const dynamic = 'force-dynamic'
export const POST = (request, context) => forwardReminderSnooze(request, context)
