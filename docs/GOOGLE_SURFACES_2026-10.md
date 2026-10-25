# What Google's own pages say about the services Diya might reach (read 2026-10-25)

This is a record for the task sheet's "check / investigate / verify" rows for Google (DIYA-071, -079, -085, -114, -122, -125, -127, -129, -131, -133, and part of -118). Every fact below was read on a Google page on
2026-10-25 and has its address next to it. Where a page did not say something, this page says "not stated" instead of guessing; those are the places to look again before building anything. Google changes these
pages: treat this as dated, not permanent. Nothing here changes what Diya does today (read-only Calendar and Gmail, approved adds to Calendar, Tasks and Drive; see `docs/GOOGLE_WRITE_DESIGN.md`).

## DIYA-071 What Google requires of an app like Diya (OAuth verification)

What the pages say:
- A new app is in **Testing**: only listed test users, up to 100, and **refresh tokens last 7 days** ("Tokens granted under a Testing status always expire in 7 days"), so a Testing app would need a sign-in every week.
  [Manage App Audience](https://support.google.com/cloud/answer/15549945?hl=en), [Data Portability: configure OAuth](https://developers.google.com/data-portability/user-guide/configure-oauth)
- **Published but unverified** ("In production"): "Any Google user can access the app", the page calls this "Strongly discouraged"; for sensitive or restricted scopes users see an unverified-app warning and "a hard cap
  of 100 total users applies", over the life of the project. [OAuth app state overview](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview)
- The overview page has **no statement exempting a personal, own-use app** from verification. (A Nest Device Access page says personal use needs no verification for restricted scopes; that is a different product's
  page and is not relied on.) The honest reading: Diya works for one person as an unverified app because the warning can be clicked through and the cap of 100 is not reached; Google could tighten that.
- Which of Diya's scopes Google labels what:

  | Scope Diya asks for | Label on Google's page |
  |---|---|
  | `gmail.readonly` | **Restricted** ([Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)) |
  | `drive.file` | **Non-sensitive**, and the one Google recommends for most uses ([Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)) |
  | `calendar.readonly`, `calendar.events` | not labelled on the Calendar page ([Calendar auth](https://developers.google.com/workspace/calendar/api/auth)); the Cloud Console shows the label when a scope is added |
  | `tasks` | not labelled on the Tasks page ([Tasks auth](https://developers.google.com/workspace/tasks/auth)); same |

What this means for Diya, as a decision recorded here (the owner decided on 2026-10-18 for a personal account and an unverified "In production" app, `docs/DECISIONS_2026-10-18.md`): keep the project **In production** (never
Testing, or the sign-in dies every 7 days); expect Google's warning screen; do not add a second user (the 100-user lifetime cap, and a restricted scope like Gmail's would then want a paid security assessment); if Google
ever stops allowing an unverified app to use `gmail.readonly`, Gmail is the part that stops, and Diya's other Google parts do not depend on it.

## DIYA-079 Gmail filters and permanent deletion

- Creating a filter needs `gmail.settings.basic` (a **Restricted** scope) and an account holds at most 1,000 filters. [filters.create](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.filters/create)
- `users.messages.delete` "Immediately and permanently deletes the specified message", cannot be undone, the page recommends `messages.trash` instead, and it needs one scope: the full-mailbox `https://mail.google.com/`,
  which also reads, composes and sends everything. [messages.delete](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/delete)
- Decision: Diya offers **neither**. A filter would be a tier-2 proposal the owner approves exactly as shown (it changes how future mail is handled, and its scope is Restricted); permanent deletion is **off and has no
  design**: the only scope that allows it also grants send and read-everything, which no part of Diya may hold. Trash (recoverable) is the only deletion that could ever be proposed.

## DIYA-085 Creating calendars and sharing them (ACL)

- `calendars.insert` accepts `calendar`, `calendar.app.created` or `calendar.calendars`; `acl.insert` accepts only `calendar` or `calendar.acls` (not `calendar.app.created`). So an app limited to the narrow
  app-created scope could make a calendar but not share it. This is read from search summaries of the reference pages ([calendars.insert](https://developers.google.com/google-apps/calendar/v3/reference/calendars/insert),
  [acl.insert](https://developers.google.com/workspace/calendar/api/v3/reference/acl/insert)), not from the pages opened; check them live before relying on it.
- Google recommends authenticating as the intended data owner, not a service account, which would own the new calendar.
- Decision: Diya holds `calendar.events` only. That can add events to the owner's own calendars; it cannot create calendars or change who can see them, and sharing is not offered at all (the owner's decision: an
  event is added "just for you", nobody is invited). A calendar or sharing change would be a new connector with a new scope and the same approval card.

## DIYA-114 Google Forms

- `forms.create` accepts `drive`, `drive.file` or `forms.body`; it creates a form from a title only, and items are added afterwards with `forms.update`/`batchUpdate`. `forms.responses.list` accepts `drive`,
  `drive.file` or `forms.responses.readonly`. So `drive.file` alone covers making a form and reading its responses. [forms.create](https://developers.google.com/workspace/forms/api/reference/rest/v1/forms/create),
  [responses.list](https://developers.google.com/workspace/forms/api/reference/rest/v1/forms.responses/list)
- Forms made through the API **after 30 June 2026 start unpublished**, and who may answer is managed through Drive permissions. [Publish and manage responders](https://developers.google.com/workspace/forms/api/guides/publish-form)
- Account constraints (consumer vs Workspace): **not stated** on the pages read. Diya already holds `drive.file`, so a Forms feature would need no new scope for create and read; it is not built.

## DIYA-122 Google Meet (part of the row; see the end for what is still open)

- Recordings, transcripts and smart notes go to **the meeting organizer's Drive** ("The user that created the meeting space"); a transcript's entries are available **30 days** after the conference ends; the API
  "isn't intended for performance tracking or user evaluation within your domain". [Meet REST API overview](https://developers.google.com/workspace/meet/api/guides/overview)
- Read scopes: `meetings.space.created` (spaces the app made) or `meetings.space.readonly` (artifacts of conferences made by other apps, such as Calendar). [Work with artifacts](https://developers.google.com/workspace/meet/api/guides/artifacts)
- Which Workspace editions or admin settings are needed: **not stated** on the pages read. So the row's "account entitlements" part is open.

## DIYA-125 Google Keep

- The Keep API is "a RESTful API used to create apps allowing enterprise administrators to manage Google Keep notes" (example use: fixing notes flagged by a security broker), authorised by **domain-wide delegation**
  (a service account, or an OAuth client the administrator approves). It was made available to enterprise administrators on 2 September 2021. [Keep API overview](https://developers.google.com/workspace/keep/api/guides),
  [release notes](https://developers.google.com/workspace/keep/release-notes)
- No page promises it for personal (consumer) accounts, and none excludes them in words. Decision: **no consumer support is assumed or promised**; Diya has no Keep feature.

## DIYA-127 Google Classroom

- The API's reach depends on the role in each class: teachers create and grade, students view and turn in, domain administrators can view coursework "but have no write permissions"; only an administrator changes a
  role. Administrators also decide whether their teachers and students may authorise other services. [Classroom FAQ](https://developers.google.com/workspace/classroom/support/faq),
  [Control user access](https://support.google.com/edu/classroom/answer/6023715?hl=en)
- Classroom is available to domains on Google Workspace for Education; a school setting needs a school-provided account. [About Classroom user accounts](https://support.google.com/edu/classroom/answer/7582372/about-classroom-user-accounts?hl=en)
- Whether a personal account may call the API at all: **not stated** in plain words on the pages read. A Classroom feature would need the owner's school account and the school's allowance; not built.

## DIYA-129 Google Photos

- From 31 March 2025 the Library API lost `photoslibrary.readonly`, `photoslibrary.sharing` and `photoslibrary`: calls relying only on them return 403; reading is limited to media **the app itself created**; uploads
  and album creation use `photoslibrary.appendonly`; sharing methods were discontinued; to let a person pick from their whole library the **Picker API** (`photospicker.mediaitems.readonly`) is used.
  [Updates to the Google Photos APIs](https://developers.google.com/photos/support/updates), [Authorization scopes](https://developers.google.com/photos/overview/authorization)
- One search snippet listed `photoslibrary.readonly.appcreateddata` as removed while other pages describe it as the remaining read scope: the authorisation page is the one to check before any scope list is written.
- Decision: Diya cannot read the owner's photo library through the Library API any more; only a person-picked item (Picker) or upload is possible. Not built; not planned.

## DIYA-131 Maps, Places and Routes

- These are **key-based, pay-as-you-go** services of the Maps Platform, not the owner's account content: Places API (New) and Routes API charge per request by the kind of data asked for (the field mask picks the
  tier), with a free monthly amount per SKU since 1 March 2025 (for example 10,000 for Essentials, 5,000 for Pro, 1,000 for Enterprise SKUs). [Places usage and billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing),
  [Core services pricing](https://developers.google.com/maps/billing-and-pricing/pricing), [March 2025 changes](https://developers.google.com/maps/billing-and-pricing/march-2025)
- That a billing account is required and how a key is restricted: **not stated** on the pages read.
- Decision: a lookup ("how far is X", "what is near Y") would be a read-only tool with a key held like any other secret and its host named in `diya_catalog.py`; the place named leaves the computer, so it would be
  declared in `FREE_TEXT_OUT` like weather. There is nothing in Maps to edit in the owner's account, so no write exists to design. Not built.

## DIYA-133 YouTube

- Uploading (`videos.insert`) needs one of `youtube.upload`, `youtube`, `youtubepartner` or `youtube.force-ssl`; it costs 1 unit from the **Video Uploads quota bucket, 100 calls a day**; videos from unverified
  API projects "are not restricted to private viewing mode" (the page's own words). [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- The default quota is 10,000 units a day for other methods, with search and uploads in their own buckets; going beyond needs an audit and extension request. [Quota calculator](https://developers.google.com/youtube/data/determine_quota_cost),
  [revision history](https://developers.google.com/youtube/data/revision_history)
- Which channel is eligible and whether a brand account is needed: **not stated** on the pages read. Not built.

## DIYA-118 Google Chat (only the part that could be read)

- Two ways in: **user authentication** (acts as the person, after their consent, sees only what they can) and **app authentication** (a service account acting as the app; `chat.bot` needs no approval, other
  `chat.app.*` scopes need a one-time administrator approval). [Chat: authenticate and authorize](https://developers.google.com/workspace/chat/authenticate-authorize)
- Whether a personal Google account can use it: **not stated**; the page speaks of administrators and domains. The row asks that a *test account* be shown to support the intended mode: that needs a real account
  and has not been done, so the row stays open.

## What is still open after this

The Meet edition question (DIYA-122), whether a personal account can use Classroom (DIYA-127), whether Maps needs billing, YouTube channel eligibility, and the live check of the Calendar ACL pages are the places where
a Google page did not say. A Workspace or school test account, or Google's support, would settle them; none of these is needed for what Diya does today.
