# Admin and cloud powers: off, and what it would take to turn any on (DIYA-135, -136, -137, -138; written 2026-10-25)

Diya is for one person on a personal Google account (`docs/DECISIONS_2026-10-18.md`). Nothing in it can administer anything. This page says so as a rule, pins it with a test, and writes down in advance what a
future request for such a power would have to meet, so that it is a decision made on purpose and not a feature that slips in.

## The rules that hold today (each is checked by `tests/test_google_admin_policy.py`)

1. **The Google permissions Diya asks for are exactly nine**, all about the owner's own things: `calendar.readonly`, `calendar.events`, `gmail.readonly`, `tasks`, `drive.file`, and the three Gmail cards added on 2026-10-26: `gmail.compose` (drafts), `gmail.send` (sending one approved email) and `gmail.modify` (filing mail), and `drive.readonly` (searching and reading the owner's own Drive files, a Drive read card that changes nothing). A tenth is a change to that test and a decision. Google's own meaning of `gmail.compose` and `gmail.modify` is wider than what Diya does with them (both include sending); Diya's code gives each card a list of the requests it may make (`diya_google_client.allow`), and `tests/test_google_mailwrite.py` pins that the drafts and organise cards have no way to send and that nothing can delete mail for good.
2. **No permission that administers anything is asked for, by name or by kind**: nothing with `admin`, `directory`, `cloud-platform`, `cloud-billing`, `iam`, `compute`, `groups`, `vault`, `reseller` or `chrome.management` in it.
3. **There is no connector for cloud administration or directory administration** in the registry, and none with those words in its name or description.
4. **No tool or proposal can spend money or provision a resource**: the catalog (`diya_catalog.py`) has no entry at tier 4 (destructive or privileged at scale), the entries at tier 3 (an email sent to another person, a task or draft deleted that Diya cannot bring back) are proposals the owner approves one at a time and are never done straight away, and none has an effect that mentions billing, a project, a resource, a role or an account.

## DIYA-135 Cloud administration is off by default

Finance and resource provisioning (billing, projects, virtual machines, roles) are **unavailable** and stay so. No code exists that could do them, and no switch turns them on, because a switch would be the first
step of the thing that needs its own security design. Wanting one means writing that design first (below), not enabling a flag.

## DIYA-136 If cloud administration is ever pursued

It would not be a tool the chat model can reach. It would need, all together:
- its **own Google Cloud project, OAuth client and connector**, never the one Calendar, Gmail, Tasks and Drive share, so revoking it cannot touch them and a leak of one cannot reach the other;
- its **own permission scope**, the narrowest that does the one thing, requested only at the moment of connecting, and shown in words on the Connections page;
- every action a **proposal at tier 4** that the owner approves one at a time, with the exact amounts, project and resource shown (the existing digest-bound approval, `diya_actions.py`), plus a **second, independent
  confirmation for anything involving billing or deletion** (the owner types the name of the resource or the amount), outside the chat page, so a conversation cannot walk the owner through it;
- **no standing grants** (decision 228: ask every time), a hard cap on amounts and on count per day, a read-back of the result (as for Google writes, DIYA-052), and an entry in the activity record;
- the **kill switch** (`diya_pause.py`) stopping it first, and **no use from an unattended job**.

## DIYA-137 Directory and organisation admin stay off in the personal product

No identity, group, user, device or organisation-policy write access, and no read of the organisation's directory either. A personal Google account has no directory, so there is nothing for it to manage.

## DIYA-138 An enterprise-only admin package, if ever requested

Only for a **verified Google Workspace tenant**, never offered to a personal account, and only after all of:
- proof that the person is a **super administrator** of that tenant (the connect step checks it with Google, it is not a setting typed in);
- an **independent security review** of the specific permissions and the code that uses them, written down before any build;
- **domain-wide delegation refused** unless the review approves that exact use, because it lets one credential act as any user in the domain;
- the same approval, second-confirmation, cap, record and kill-switch rules as DIYA-136, plus a **separate installation** from the personal one (not a mode of it), so a personal install can never carry the package.

Until a request exists, none of this is built; this page is the whole of the work.
