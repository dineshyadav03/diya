"""Google Contacts: look someone up, resolve a name to an address for an email, and add, change and delete contacts and their groups when you approve each (DIYA-110, -111, -112, -113; docs/GOOGLE_CHANGES.md), added 2026-10-26.

Two new cards:

* **Google Contacts (read)** (`contacts.readonly`): "what is Maya's email?", "find the contact Sam". Code reads your contacts and writes the answer itself (no model, no tool): a name, its addresses and numbers. Where two people match,
  it lists them and asks which. This card is also what lets an email go to a NAME: "email Maya that I will be late" is resolved here to Maya's address, shown on the approval card as "(Maya Rao, from your contacts)"; a name that is
  not in your contacts, or that matches two people, is refused, so an email never goes to a target that was ambiguous (DIYA-113). An address you typed yourself is still used as typed.
* **Google Contacts (change)** (`contacts`): add a contact, add an email or number to one, put one in a group or take them out, delete one. Each only when you approve it; a contact is found now by name, its version (etag) is checked
  again when it runs, and a duplicate is not made.

The words of a contact (names, notes) can come from people who shared them, so they are cleaned and cut, and read by code, never handed to a model as tools. Importing this module has no side effects except naming what each card may
ask Google for (diya_google_client.allow).
"""
from __future__ import annotations

import re

import diya_connectors
import diya_google_cards
import diya_google_client as client
import diya_google_mailwrite as mw
import diya_google_write as gw
import diya_intent
import diya_intent_google as asks
import diya_memory
from diya_actions import ActionFailed, ActionKind, ActionUncertain, InvalidArgs

PEOPLE = "https://people.googleapis.com/v1"
READ, CHANGE = "google_contacts_read", "google_contacts_change"
SCOPES = {READ: "https://www.googleapis.com/auth/contacts.readonly", CHANGE: "https://www.googleapis.com/auth/contacts"}
LABELS = {READ: "Google Contacts (read)", CHANGE: "Google Contacts (change)"}
RID = r"c[0-9]{1,30}"  # a contact's id in the People API: people/c1234567890
GID = r"[A-Za-z0-9_-]{1,60}"
FIELDS = "names,emailAddresses,phoneNumbers,memberships,metadata"
MAX_SHOWN = 5
MAX_PAGES = 3
PHONE = re.compile(r"\+?[0-9][0-9 ()-]{5,20}[0-9]")
_P = re.escape(PEOPLE)

for _card in (READ, CHANGE):
    client.allow(_card, "GET", rf"{_P}/people/me/connections")
    client.allow(_card, "GET", rf"{_P}/contactGroups")
client.allow(CHANGE, "GET", rf"{_P}/people/{RID}")
client.allow(CHANGE, "POST", rf"{_P}/people:createContact")
client.allow(CHANGE, "PATCH", rf"{_P}/people/{RID}:updateContact")
client.allow(CHANGE, "DELETE", rf"{_P}/people/{RID}:deleteContact")
client.allow(CHANGE, "POST", rf"{_P}/contactGroups/{GID}/members:modify")


def _norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").casefold()).split())


def _clean(value, limit=80):
    return diya_memory.printable(value, limit)


# ---- reading --------------------------------------------------------------------------------------------------------------------------------------

def _person(raw):
    names = [n for n in (raw.get("names") or []) if isinstance(n, dict)]
    name = next((n.get("displayName") for n in names if n.get("metadata", {}).get("primary")), None) or (names[0].get("displayName") if names else None) or ""
    emails = [str(e.get("value")).strip().lower() for e in (raw.get("emailAddresses") or []) if isinstance(e, dict) and _email_ok(e.get("value"))]
    phones = [" ".join(str(p.get("value")).split()) for p in (raw.get("phoneNumbers") or []) if isinstance(p, dict) and PHONE.fullmatch(" ".join(str(p.get("value") or "").split()))]
    groups = [m.get("contactGroupMembership", {}).get("contactGroupResourceName") for m in (raw.get("memberships") or []) if isinstance(m, dict) and m.get("contactGroupMembership")]
    resource = raw.get("resourceName")
    return {"resource": resource if isinstance(resource, str) and re.fullmatch(rf"people/{RID}", resource) else None, "etag": str(raw.get("etag") or "")[:200], "name": _clean(name, 80), "emails": emails[:5], "phones": phones[:5],
            "groups": [g for g in groups if isinstance(g, str)]}


def _email_ok(value):
    return isinstance(value, str) and mw.EMAIL.fullmatch(value.strip()) is not None


def contacts(config, card=READ):
    """The person's contacts as dicts (name, addresses, numbers, id, version), up to a few pages; GoogleError for a problem."""
    items, _more = client.pages(config, card, LABELS[card], f"{PEOPLE}/people/me/connections", {"personFields": FIELDS, "pageSize": 500, "sortOrder": "LAST_NAME_ASCENDING"}, "connections", max_pages=MAX_PAGES)
    return [p for p in (_person(i) for i in items) if p["name"] or p["emails"]]


def match(people, wanted):
    """The contacts whose name is `wanted` (whole name, else all its words in the name); [] if none."""
    target = _norm(wanted)
    if not target:
        return []
    exact = [p for p in people if _norm(p["name"]) == target]
    if exact:
        return exact
    words = target.split()
    return [p for p in people if all(w in _norm(p["name"]).split() or any(part.startswith(w) for part in _norm(p["name"]).split()) for w in words)]


def describe(person):
    bits = [", ".join(person["emails"]) if person["emails"] else "", ", ".join(person["phones"]) if person["phones"] else ""]
    return f"{person['name'] or '(no name)'}: " + ("; ".join(b for b in bits if b) or "no email or number saved")


_ASK = re.compile(
    r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya|and|can\s+you|could\s+you)\b[\s,]*)*(?:what(?:'s|s|\s+is|\s+are)|who(?:'s|s|\s+is)|tell\s+me|show\s+me|show|find|get|give\s+me|do\s+i\s+have)\s+(?:me\s+)?(?:the\s+)?"
    r"(?:(?P<name>[A-Za-z][A-Za-z .'-]{1,40}?)(?:'s|s')\s+(?P<what>e-?mail(?:\s+address)?|number|phone(?:\s+number)?|mobile|contact)|(?P<what2>contact|number|e-?mail)\s+(?:for|of|called|named)\s+(?P<name2>[A-Za-z][A-Za-z .'-]{1,40}?))\s*\??$", re.IGNORECASE)
_SHOW = re.compile(r"^\W*(?:(?:hey|hi|ok|okay|so|please|diya)\b[\s,]*)*(?:find|show|look\s+up|search\s+for)\s+(?:me\s+)?(?:the\s+|my\s+)?contact\s+(?:called\s+|named\s+)?(?P<name>[A-Za-z][A-Za-z .'-]{1,40}?)\s*\??$", re.IGNORECASE)


def request(text):
    """{"name": ..., "what": ...} when the message is a plain question about one contact ("what is Maya's email?", "find the contact Sam"), else None."""
    if not isinstance(text, str) or not text.strip() or len(text) > 120 or "\n" in text.strip():
        return None
    flat = text.replace(chr(0x2019), "'").strip()
    for pattern in (_ASK, _SHOW):
        found = pattern.search(flat)
        if found:
            groups = found.groupdict()
            name = " ".join((groups.get("name") or groups.get("name2") or "").split()).strip(" .'-")
            what = (groups.get("what") or groups.get("what2") or "contact").lower()
            if name and not re.fullmatch(r"(?:my|your|the|it|that|this|his|her|their)", name, re.IGNORECASE):
                return {"name": name, "what": "email" if "mail" in what else "number" if re.search(r"number|phone|mobile", what) else "contact"}
    return None


def lookup(config, found):
    """The answer to a request (see `request`), built by code from the contacts: a name, its addresses and numbers; or which people match, or that none does. Returns (text, status) with status found/nothing/problem."""
    if diya_connectors.read_token(config, READ) is None:
        return "Google Contacts (read) is not connected.", "problem"
    try:
        people = contacts(config)
    except client.GoogleError as exc:
        return str(exc), "problem"
    matches = match(people, found["name"])
    if not matches:
        return f"No one called {_clean(found['name'], 60)!r} is in your contacts.", "nothing"
    if len(matches) > 1:
        return f"{len(matches)} contacts match {_clean(found['name'], 60)!r}:\n" + "\n".join(f"- {describe(p)}" for p in matches[:MAX_SHOWN]) + ("\n(and more)" if len(matches) > MAX_SHOWN else ""), "found"
    person = matches[0]
    if found["what"] == "email":
        text = f"{person['name']}: " + (", ".join(person["emails"]) if person["emails"] else "no email saved")
    elif found["what"] == "number":
        text = f"{person['name']}: " + (", ".join(person["phones"]) if person["phones"] else "no number saved")
    else:
        text = describe(person)
    return text + "\n(From your Google Contacts, which I can only read.)", "found"


# ---- an email goes to a NAME only if one contact has it, and the card says so -------------------------------------------------------------------

def resolve_names(config, items, said):
    """For the people an email (or an invitation, or a share) is for: `items` are what the model gave, each an address or a name. An address must be one the person typed (done by the caller); a NAME must be in the person's own
    words and be exactly one contact with exactly one address. Returns (the addresses, how each name was resolved, in words). InvalidArgs, saying what to ask, for anything else."""
    addresses, notes = [], []
    for item in items:
        if mw.EMAIL.fullmatch(item):
            addresses.append(item.lower())
            continue
        if not diya_intent.said_in(item, said):
            raise InvalidArgs(f"{_clean(item, 40)!r} is not a name or an address the user said, so it is not used; ask them who it is for")
        if diya_connectors.read_token(config, READ) is None:
            raise InvalidArgs(f"the user said a name ({_clean(item, 40)!r}), and Diya can only turn a name into an address with Google Contacts (read) connected; ask for the email address")
        try:
            found = match(contacts(config), item)
        except client.GoogleError as exc:
            raise InvalidArgs(f"{exc} Nothing was proposed.")
        if not found:
            raise InvalidArgs(f"no one called {_clean(item, 40)!r} is in the user's contacts; ask for the email address")
        if len(found) > 1:
            raise InvalidArgs(f"{len(found)} contacts match {_clean(item, 40)!r}: " + "; ".join(describe(p) for p in found[:MAX_SHOWN]) + ". Ask which one, by the address, and do not choose")
        person = found[0]
        if len(person["emails"]) != 1:
            raise InvalidArgs(f"{person['name']} has {'no' if not person['emails'] else len(person['emails'])} email address{'es' if len(person['emails']) > 1 else ''} saved; ask for the address to use")
        addresses.append(person["emails"][0])
        notes.append(f"{person['name']}, from your contacts")
    return addresses, notes


# ---- changing contacts ----------------------------------------------------------------------------------------------------------------------------

def _find_contact(config, name, said):
    wanted = " ".join(re.sub(r"[^\w' .&-]", " ", name).split())[:80] if isinstance(name, str) and diya_intent.said_in(name, said) else ""
    if not wanted:
        raise InvalidArgs("say which contact, by name, in the user's own words; I do not choose one")
    try:
        found = match(contacts(config, CHANGE), wanted)
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    if not found:
        raise InvalidArgs(f"no one called {_clean(wanted, 40)!r} is in your contacts")
    if len(found) > 1:
        raise InvalidArgs(f"{len(found)} contacts match {_clean(wanted, 40)!r}: " + "; ".join(describe(p) for p in found[:MAX_SHOWN]) + ". Ask which one and do not choose")
    if not found[0]["resource"]:
        raise InvalidArgs("Google gave that contact no usable id, so it cannot be changed safely")
    return found[0]


def _ref(person):
    return {"name": _clean(person["name"], 80), "resource": person["resource"], "etag": person["etag"]}


def _validate_ref(args):
    if not isinstance(args.get("resource"), str) or not re.fullmatch(rf"people/{RID}", args["resource"]):
        raise InvalidArgs("a change needs the contact found by name (Diya finds it; it cannot be given an id)")
    gw._clean_title(args.get("name"), "a contact")
    if not isinstance(args.get("etag", ""), str) or len(args.get("etag", "")) > 200:
        raise InvalidArgs("the contact's version is not usable")


def _read_person(config, resource):
    return _person(client.read(config, CHANGE, LABELS[CHANGE], f"{PEOPLE}/{resource}", {"personFields": FIELDS}))


def _still_the_same(config, args):
    try:
        now = _read_person(config, args["resource"])
    except client.GoogleError as exc:
        if exc.kind == "not_found":
            raise ActionFailed("That contact is not in your contacts any more, so nothing was done.")
        raise ActionFailed(f"{exc} Nothing was done.")
    if args.get("etag") and now["etag"] and now["etag"] != args["etag"]:
        raise ActionFailed(f"{args['name']} was changed in Google Contacts after it was proposed, so nothing was done. Look at it in Google and ask again if you still want this.")
    return now


def _typed_details(args, text):
    """Of the email and number the model gave, the ones the person typed themselves."""
    kept = dict(args)
    if kept.get("email") is not None:
        kept["email"] = mw.own_recipients(kept["email"], text, "the email address")
        if len(mw._split(kept["email"])) != 1:
            raise InvalidArgs("one email address at a time")
    if kept.get("phone") is not None:
        digits = re.sub(r"\D", "", str(kept["phone"]))
        if not PHONE.fullmatch(" ".join(str(kept["phone"]).split())) or digits not in "".join(re.findall(r"\d+", text)):
            raise InvalidArgs("the number must be one the user typed; ask them for it")
        kept["phone"] = " ".join(str(kept["phone"]).split())
    return kept


# ---- add a contact -----------------------------------------------------------------------------------------------------------------------------------

def add_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "email", "phone")}
    if not gw._own_words(kept.get("name"), text):
        raise InvalidArgs("the contact's name must be one the user said; ask them")
    kept = _typed_details(kept, text)
    if not kept.get("email") and not kept.get("phone"):
        raise InvalidArgs("a contact needs an email address or a number that the user typed")
    return kept, []


def add_resolve(config, args, said):
    try:
        existing = contacts(config, CHANGE)
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    for person in existing:
        if _norm(person["name"]) == _norm(args["name"]) or (args.get("email") and args["email"].lower() in person["emails"]):
            raise InvalidArgs(f"{describe(person)} is already in your contacts, so a second one is not made")
    return dict(args)


def add_validate(args):
    gw._only(args, {"name", "email", "phone"}, "a contact")
    gw._clean_title(args.get("name"), "a contact")
    if args.get("email") is not None and len(mw._addresses(args["email"], "the email address")) != 1:
        raise InvalidArgs("one email address at a time")
    if args.get("phone") is not None and not PHONE.fullmatch(str(args["phone"])):
        raise InvalidArgs("that is not a phone number")
    if not args.get("email") and not args.get("phone"):
        raise InvalidArgs("a contact needs an email address or a number")


def add_render(args):
    return f"Add to your Google Contacts: {_clean(args['name'], 80)}" + "".join(f", {label} {_clean(args[key], 60)}" for key, label in (("email", "email"), ("phone", "number")) if args.get(key))


def add_execute(config, args):
    given, _, family = args["name"].partition(" ")
    body = {"names": [{"givenName": given, "familyName": family}] if family else [{"givenName": given}]}
    if args.get("email"):
        body["emailAddresses"] = [{"value": args["email"]}]
    if args.get("phone"):
        body["phoneNumbers"] = [{"value": args["phone"]}]
    response = client.send(config, CHANGE, LABELS[CHANGE], "POST", f"{PEOPLE}/people:createContact", params={"personFields": FIELDS}, body=body, doing=f"adding {args['name']}")
    made = _person(client.as_json(response))
    if not made["resource"]:
        raise ActionUncertain("Google said the contact was added but gave no usable id to check it by, so it is not confirmed. Look in Google Contacts, then record what you found.")
    try:
        found = _read_person(config, made["resource"])
    except client.GoogleError:
        raise ActionUncertain("Google said the contact was added, but reading it back to check did not work, so it is not confirmed. Look in Google Contacts, then record what you found.")
    if _norm(found["name"]) != _norm(args["name"]) or (args.get("email") and args["email"].lower() not in found["emails"]) or (args.get("phone") and args["phone"] not in found["phones"]):
        raise ActionUncertain("Google said the contact was added, but reading it back showed something different, so it is not confirmed. Look in Google Contacts, then record what you found.")
    return f"Added to your Google Contacts and read back to check: {describe(found)}."


# ---- add an email or a number to a contact ----------------------------------------------------------------------------------------------------

def update_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "email", "phone")}
    kept = _typed_details(kept, text)
    if not kept.get("email") and not kept.get("phone"):
        raise InvalidArgs("say which email address or number to add, and type it")
    return kept, []


def update_resolve(config, args, said):
    person = _find_contact(config, args.get("name"), said)
    if (args.get("email") and args["email"].lower() in person["emails"]) and (not args.get("phone") or args["phone"] in person["phones"]):
        raise InvalidArgs(f"{person['name']} already has that")
    if args.get("phone") and args["phone"] in person["phones"] and not args.get("email"):
        raise InvalidArgs(f"{person['name']} already has that")
    return dict(_ref(person), **{k: args[k] for k in ("email", "phone") if args.get(k)})


def update_validate(args):
    gw._only(args, {"name", "resource", "etag", "email", "phone"}, "changing a contact")
    _validate_ref(args)
    if args.get("email") is not None and len(mw._addresses(args["email"], "the email address")) != 1:
        raise InvalidArgs("one email address at a time")
    if args.get("phone") is not None and not PHONE.fullmatch(str(args["phone"])):
        raise InvalidArgs("that is not a phone number")
    if not args.get("email") and not args.get("phone"):
        raise InvalidArgs("say what to add: an email address or a number")


def update_render(args):
    return f"Add to the contact {_clean(args['name'], 60)}: " + " and ".join(f"{label} {_clean(args[key], 60)}" for key, label in (("email", "the email"), ("phone", "the number")) if args.get(key))


def update_execute(config, args):
    now = _still_the_same(config, args)
    emails = [{"value": e} for e in now["emails"]] + ([{"value": args["email"]}] if args.get("email") and args["email"].lower() not in now["emails"] else [])
    phones = [{"value": p} for p in now["phones"]] + ([{"value": args["phone"]}] if args.get("phone") and args["phone"] not in now["phones"] else [])
    fields = [f for f, given in (("emailAddresses", args.get("email")), ("phoneNumbers", args.get("phone"))) if given]
    body = {"etag": args["etag"] or now["etag"]}
    if "emailAddresses" in fields:
        body["emailAddresses"] = emails
    if "phoneNumbers" in fields:
        body["phoneNumbers"] = phones
    client.send(config, CHANGE, LABELS[CHANGE], "PATCH", f"{PEOPLE}/{args['resource']}:updateContact", params={"updatePersonFields": ",".join(fields), "personFields": FIELDS}, body=body, doing=f"changing {args['name']}")
    try:
        found = _read_person(config, args["resource"])
    except client.GoogleError:
        raise ActionUncertain("Google said the contact was changed, but reading it back to check did not work, so it is not confirmed. Look in Google Contacts, then record what you found.")
    if (args.get("email") and args["email"].lower() not in found["emails"]) or (args.get("phone") and args["phone"] not in found["phones"]):
        raise ActionUncertain("Google said the contact was changed, but reading it back did not show the new details, so it is not confirmed. Look in Google Contacts, then record what you found.")
    return f"Changed in your Google Contacts and read back to check: {describe(found)}."


# ---- delete a contact -----------------------------------------------------------------------------------------------------------------------------

def delete_resolve(config, args, said):
    return _ref(_find_contact(config, args.get("name"), said))


def delete_validate(args):
    gw._only(args, {"name", "resource", "etag"}, "deleting a contact")
    _validate_ref(args)


def delete_render(args):
    return f"Delete the contact {_clean(args['name'], 80)} from your Google Contacts (Diya cannot bring it back)"


def delete_execute(config, args):
    _still_the_same(config, args)
    client.send(config, CHANGE, LABELS[CHANGE], "DELETE", f"{PEOPLE}/{args['resource']}:deleteContact", ok=(200, 204), doing=f"deleting {args['name']}")
    try:
        _read_person(config, args["resource"])
    except client.GoogleError as exc:
        if exc.kind == "not_found":
            return f"Deleted from your Google Contacts: {args['name']}. Google no longer has it."
        raise ActionUncertain("Google said the contact was deleted, but reading to check did not work, so it is not confirmed. Look in Google Contacts, then record what you found.")
    raise ActionUncertain("Google said the contact was deleted, but it is still there, so it is not confirmed. Look in Google Contacts, then record what you found.")


# ---- groups ------------------------------------------------------------------------------------------------------------------------------------------

def _groups(config):
    items, _more = client.pages(config, CHANGE, LABELS[CHANGE], f"{PEOPLE}/contactGroups", {"pageSize": 200, "groupFields": "name,groupType,memberCount"}, "contactGroups", max_pages=1)
    return [g for g in items if g.get("groupType") == "USER_CONTACT_GROUP" and isinstance(g.get("resourceName"), str) and re.fullmatch(rf"contactGroups/{GID}", g["resourceName"])]


def group_prepare(args, text):
    kept = {k: v for k, v in args.items() if k in ("name", "group", "action")}
    if kept.get("action") not in ("add", "remove"):
        raise InvalidArgs("a contact is put in a group (add) or taken out of it (remove)")
    if not gw._own_words(kept.get("group"), text):
        raise InvalidArgs("the group's name must be one the user said; ask them")
    return kept, []


def group_resolve(config, args, said):
    person = _find_contact(config, args.get("name"), said)
    try:
        groups = [g for g in _groups(config) if _norm(g.get("name")) == _norm(args["group"])]
    except client.GoogleError as exc:
        raise InvalidArgs(f"{exc} Nothing was proposed.")
    if len(groups) != 1:
        raise InvalidArgs(f"there is no group of yours called {_clean(args['group'], 40)!r} (Diya does not make groups, and the built-in ones cannot be changed)")
    group = groups[0]["resourceName"]
    inside = group in person["groups"]
    if args["action"] == "add" and inside:
        raise InvalidArgs(f"{person['name']} is already in {_clean(args['group'], 40)}")
    if args["action"] == "remove" and not inside:
        raise InvalidArgs(f"{person['name']} is not in {_clean(args['group'], 40)}")
    return dict(_ref(person), action=args["action"], group=_clean(groups[0].get("name"), 60), group_id=group.split("/", 1)[1])


def group_validate(args):
    gw._only(args, {"name", "resource", "etag", "action", "group", "group_id"}, "changing a group")
    _validate_ref(args)
    if args.get("action") not in ("add", "remove") or not isinstance(args.get("group_id"), str) or not re.fullmatch(GID, args["group_id"]):
        raise InvalidArgs("a group is found by its name; it cannot be given an id")
    gw._clean_title(args.get("group"), "a group")


def group_render(args):
    return f"{'Put' if args['action'] == 'add' else 'Take'} the contact {_clean(args['name'], 60)} {'in' if args['action'] == 'add' else 'out of'} your group {_clean(args['group'], 60)}"


def group_execute(config, args):
    _still_the_same(config, args)
    key = "resourceNamesToAdd" if args["action"] == "add" else "resourceNamesToRemove"
    client.send(config, CHANGE, LABELS[CHANGE], "POST", f"{PEOPLE}/contactGroups/{args['group_id']}/members:modify", body={key: [args["resource"]]}, doing=f"changing the group {args['group']}")
    try:
        found = _read_person(config, args["resource"])
    except client.GoogleError:
        raise ActionUncertain("Google said the group was changed, but reading to check did not work, so it is not confirmed. Look in Google Contacts, then record what you found.")
    inside = f"contactGroups/{args['group_id']}" in found["groups"]
    if inside != (args["action"] == "add"):
        raise ActionUncertain("Google said the group was changed, but reading it back showed it was not, so it is not confirmed. Look in Google Contacts, then record what you found.")
    return f"{'Put' if args['action'] == 'add' else 'Took'} {args['name']} {'in' if args['action'] == 'add' else 'out of'} {args['group']} and read back to check."


# ---- the kinds and the cards ---------------------------------------------------------------------------------------------------------------------

def _kind(name, label, tool_name, description, properties, required, **functions):
    return ActionKind(
        name=name, label=label, connector=CHANGE, **functions,
        tool={"type": "function", "function": {"name": tool_name, "description": description + " This only PROPOSES it: nothing is changed until the user approves it on the Actions page.",
                                                "parameters": {"type": "object", "properties": properties, "required": required}}},
    )


NAME = {"type": "string", "description": "The contact's name, exactly as the user said it."}


def action_kinds():
    return (
        _kind("google_contacts_add", "Add a contact", "propose_add_contact", "Propose adding a new contact with the email address or number the user typed. Use it only when the user asks to add a contact.",
              {"name": NAME, "email": {"type": "string", "description": "Optional. The email address, exactly as the user typed it."}, "phone": {"type": "string", "description": "Optional. The number, exactly as the user typed it."}}, ["name"],
              validate=add_validate, render=add_render, execute=add_execute, asked=asks.adds_contact, prepare=add_prepare, resolve=add_resolve),
        _kind("google_contacts_update", "Add an email or number to a contact", "propose_update_contact", "Propose adding an email address or a number, which the user typed, to a contact they name. Use it only when the user asks for that.",
              {"name": NAME, "email": {"type": "string", "description": "Optional. The email address to add, exactly as typed."}, "phone": {"type": "string", "description": "Optional. The number to add, exactly as typed."}}, ["name"],
              validate=update_validate, render=update_render, execute=update_execute, asked=asks.updates_contact, prepare=update_prepare, resolve=update_resolve),
        _kind("google_contacts_delete", "Delete a contact", "propose_delete_contact", "Propose deleting one contact the user names. Diya cannot bring it back. Use it only when the user asks for that.",
              {"name": NAME}, ["name"], validate=delete_validate, render=delete_render, execute=delete_execute, asked=asks.deletes_contact, resolve=delete_resolve),
        _kind("google_contacts_group", "Put a contact in a group", "propose_contact_group", "Propose putting a contact in one of the user's own contact groups, or taking them out. Use it only when the user asks for that, naming the contact and the group.",
              {"name": NAME, "group": {"type": "string", "description": "The group's name, exactly as the user said it."}, "action": {"type": "string", "enum": ["add", "remove"], "description": "add or remove."}}, ["name", "group", "action"],
              validate=group_validate, render=group_render, execute=group_execute, asked=asks.groups_contact, prepare=group_prepare, resolve=group_resolve),
    )


def connectors():
    return (
        diya_google_cards.card(READ, LABELS[READ], "Look someone up in your contacts when you ask, and turn a name into an email address for an email you approve.", SCOPES[READ], "People API (Google Contacts)",
                               ("Reads your contacts when you ask for a name's email or number, and finds the address when you tell Diya to email a name.", "Shows which contact was used on the approval card.",
                                "Cannot add, change or delete a contact, and never guesses between two people with the same name.")),
        diya_google_cards.card(CHANGE, LABELS[CHANGE], "Add a contact, add an email or number to one, put one in a group or delete one, when you approve it.", SCOPES[CHANGE], "People API (Google Contacts)",
                               ("Adds a contact, adds an email or number you typed to one, puts one in a group of yours or takes them out, and deletes one, only when you approve that one change.",
                                "Finds the contact by name when you ask, and checks it has not changed before it acts.", "Cannot make groups, and never makes a second contact for someone who is already there.")),
    )
