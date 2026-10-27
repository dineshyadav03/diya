"""One read-only call per newer Google card on the owner's real account. Prints only the HTTP status and a count, never any content."""
import sys

import httpx

sys.path.insert(0, "C:/Users/dines/OneDrive/Desktop/mac-mini-ai-engineer")
import diya_config
import diya_google_calendar as gcal

config = diya_config.load_config()
PROBES = [
    ("google_mail_drafts", "https://gmail.googleapis.com/gmail/v1/users/me/drafts", {"maxResults": 1}, "drafts"),
    ("google_mail_send", "https://gmail.googleapis.com/gmail/v1/users/me/profile", {}, None),
    ("google_mail_organise", "https://gmail.googleapis.com/gmail/v1/users/me/labels", {}, "labels"),
    ("google_calendar_change", "https://www.googleapis.com/calendar/v3/users/me/calendarList", {"maxResults": 1}, "items"),
    ("google_calendar_guests", "https://www.googleapis.com/calendar/v3/users/me/calendarList", {"maxResults": 1}, "items"),
    ("google_drive_read", "https://www.googleapis.com/drive/v3/files", {"pageSize": 1, "fields": "files(id)"}, "files"),
    ("google_drive_change", "https://www.googleapis.com/drive/v3/about", {"fields": "user(kind)"}, None),
    ("google_contacts_read", "https://people.googleapis.com/v1/people/me/connections", {"personFields": "names", "pageSize": 1}, "connections"),
    ("google_contacts_change", "https://people.googleapis.com/v1/people/me/connections", {"personFields": "names", "pageSize": 1}, "connections"),
]
for name, url, params, key in PROBES:
    try:
        token = gcal.access_token(config, name)
    except Exception as error:
        print(name.ljust(24), "no access token:", type(error).__name__, str(error)[:120])
        continue
    if not token:
        print(name.ljust(24), "no access token")
        continue
    try:
        reply = httpx.get(url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except Exception as error:
        print(name.ljust(24), "network:", type(error).__name__)
        continue
    extra = ""
    if reply.status_code != 200:
        try:
            body = reply.json().get("error", {})
            extra = f"  {body.get('status', '')} {str(body.get('message', ''))[:140]}"
        except Exception:
            extra = ""
    elif key:
        try:
            extra = f"  ({len(reply.json().get(key, []))} on first page)"
        except Exception:
            pass
    print(name.ljust(24), reply.status_code, extra)
