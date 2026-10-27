"""Can diya-chat (the 4B model on this laptop) do the building blocks of a Hark-like assistant? Four probes against the real model through Ollama, scored by code, nothing saved, no accounts touched.

  A  pull the details out of a booking request in the person's words (restaurant, party size, 24-hour time)
  B  draft a short message to a restaurant (the facts must be in it, short, no invented phone number)
  C  pick the right element from a page's structure (a login page), one task at a time
  D  tell whether a step worked from what the page says afterwards (the usual failure of small models: saying "done" when it was not)

Run:  python handoff/tools/capability_probe.py
"""
import json
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
URL, MODEL = "http://127.0.0.1:11434/api/chat", "diya-chat"


def ask(system, user, tokens=200):
    body = {"model": MODEL, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "options": {"temperature": 0, "num_predict": tokens}}
    started = time.time()
    request = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    reply = json.load(urllib.request.urlopen(request, timeout=300))["message"]["content"].strip()
    return reply, time.time() - started


def report(name, right, total, seconds):
    print(f"{name:<44} {right}/{total} right   {seconds / total:4.1f} s each")


# ---- A: details from words -----------------------------------------------------------------------------------------------------------------
A = [
    ("Book a table for 4 at Vaishali on Saturday at 8pm", "vaishali", 4, "20:00"),
    ("table for two at Roast, tomorrow 7:30 pm", "roast", 2, "19:30"),
    ("reserve 6 seats at Toit this Friday 9 pm", "toit", 6, "21:00"),
    ("dinner for 3 at Kailash Parbat on 2 Nov at 8", "kailash parbat", 3, "20:00"),
    ("book me an italian place for 2 tonight around 8", "", 2, "20:00"),
]
SYSTEM_A = 'Reply with JSON only, no other words: {"restaurant": string or null, "party_size": integer, "time": "HH:MM" in 24 hours}. Use null for a restaurant that is not named.'
right = fields = 0
spent = 0.0
for text, name, size, clock in A:
    reply, took = ask(SYSTEM_A, text)
    spent += took
    try:
        data = json.loads(re.search(r"\{.*\}", reply, re.S).group(0))
    except Exception:
        data = {}
    got = [str(data.get("restaurant") or "").lower().strip() == name or (name and name in str(data.get("restaurant") or "").lower()), data.get("party_size") == size, str(data.get("time")) == clock]
    right += all(got)
    fields += sum(bool(g) for g in got)
    print("   A:", text[:46].ljust(46), "->", json.dumps(data)[:70], "" if all(got) else "  <-- WRONG")
report("A  details from the person's words (all 3 right)", right, len(A), spent)
print(f"   A  fields right: {fields}/{3 * len(A)}")

# ---- B: draft a message --------------------------------------------------------------------------------------------------------------------
B = [
    ("Write a short WhatsApp message asking Vaishali to book a table for 4 on Saturday at 8 pm.", ["4", "saturday", "8"]),
    ("Write a short message to Toit asking for a table for 6 this Friday at 9 pm, and to confirm by reply.", ["6", "friday", "9"]),
    ("Write a short email to Roast asking for a table for two tomorrow at 7:30 pm.", ["two", "7:30"]),
]
right = 0
spent = 0.0
for prompt, needed in B:
    reply, took = ask("You write short, polite messages for the user. Reply with the message only.", prompt, 160)
    spent += took
    low = reply.lower()
    facts = all(n in low for n in needed)
    short = len(reply.split()) <= 70
    invented = bool(re.search(r"\d{10}|\+\d{2}", reply))
    placeholder = bool(re.search(r"\[[^\]]+\]", reply))
    right += facts and short and not invented
    print(f"   B: facts {'ok' if facts else 'MISSING'}, {len(reply.split())} words, invented number {invented}, placeholders {placeholder}")
report("B  draft a message (facts, short, no invented number)", right, len(B), spent)

# ---- C: pick the element -------------------------------------------------------------------------------------------------------------------
PAGE = """[e1] link "Skip to content"
[e2] link "GitHub homepage"
[e3] heading "Sign in to GitHub"
[e4] textbox "Username or email address"
[e5] textbox "Password"
[e6] link "Forgot password?"
[e7] button "Sign in"
[e8] button "Sign in with a passkey"
[e9] link "Create an account"
[e10] link "Terms"
[e11] link "Privacy"
[e12] link "Contact GitHub support\""""
C = [("the field where the user name goes", "e4"), ("the field where the password goes", "e5"), ("the button that submits the form", "e7"), ("the link for someone who lost their password", "e6"),
     ("the link for a person who has no account yet", "e9"), ("the button to sign in without a password", "e8"), ("the link to the terms of service", "e10"), ("the link to the privacy policy", "e11")]
right = 0
spent = 0.0
for what, ref in C:
    reply, took = ask("You control a web browser. You are given the page's elements. Reply with ONLY the ref of the element asked for, like e3.", f"{PAGE}\n\nWhich element is {what}?", 12)
    spent += took
    got = re.search(r"e\d+", reply)
    right += bool(got) and got.group(0) == ref
    if not (got and got.group(0) == ref):
        print("   C: wrong on", what, "->", reply[:30])
report("C  pick the right element on a login page", right, len(C), spent)

# ---- D: did the step work? -----------------------------------------------------------------------------------------------------------------
D = [
    ("Task: book a table. Page now says: 'Booking confirmed for Saturday 8 PM, table for 4. A confirmation was sent to your phone.'", "YES"),
    ("Task: pay the electricity bill. Page now says: 'Payment successful. Receipt number 88213.'", "YES"),
    ("Task: place the order. Page now says: 'Thank you! Your order is placed. Estimated delivery Friday.'", "YES"),
    ("Task: pay the electricity bill. Page now says: 'Payment failed. Your bank declined the transaction. Please try again.'", "NO"),
    ("Task: book a table. Page now says: 'Your session has expired. Please sign in again to continue.'", "NO"),
    ("Task: place the order. Page now says: 'Please enter a valid card number.' and the card field is red.", "NO"),
    ("Task: pay the bill. Page now says: 'Please verify you are human to continue.' with a checkbox.", "NO"),
    ("Task: book a table. Page now says: 'Request received. The restaurant will confirm your booking by SMS within 2 hours.'", "NO"),
]
right = 0
spent = 0.0
for text, truth in D:
    reply, took = ask("You check whether a browser task is finished. Reply with ONLY YES if the task is clearly finished, otherwise ONLY NO.", text, 6)
    spent += took
    ok = reply.strip().upper().startswith(truth)
    right += ok
    if not ok:
        print("   D: wrong on", text[:70], "->", reply[:12])
report("D  tell whether a step worked", right, len(D), spent)
