# Sign-ins at rest, PKCE, and taking the permission back (2026-10-18)

The blueprint's milestone G0 (Google foundation) asks for three things about how a Google sign-in is held. All three are in, tested against stand-ins, and not yet tried against the real Google.

## 1. A sign-in is stored encrypted for this Windows user

**The problem found.** A connector's refresh token was a plain file in the connector tokens folder, and that folder is beside the code by default, which for this project is inside OneDrive. A connected Google account would have had its refresh token uploaded to the cloud in plain text (`docs/AUDIT_2026-10-10.md`, F3, already told the owner to move the data folder; this makes the files safe even if they are not moved). Nothing was connected for real yet, so nothing leaked.

**The change** (`diya_secrets.py`). On Windows, a token and Google's client secret are written protected with **DPAPI** (`CryptProtectData`, the operating system's own per-user encryption, called through `ctypes`: no new dependency). Only the same Windows user on the same machine can decrypt the file, so a copy in OneDrive, in a backup, or on a stolen disk is useless without that login. The file holds `dpapi1:` and base64.

- A file from before (plain text) is still read, and is rewritten protected the first time it is read.
- A protected file that **cannot be decrypted here** (copied to another user or machine, or damaged) counts as **not connected**; the answer is to connect again. It is never an error that stops Diya.
- Off Windows nothing is changed: no DPAPI, so the file stays as it was. (The Mac mini is deferred indefinitely; the macOS Keychain is the equivalent and is not built.)
- `DIYA_PROTECT_SECRETS=0` keeps files plain.
- Moving the data folder with `python diya_data.py move` copies the protected bytes, and they still work for the same Windows user.

**What it is not.** It does not stop another program **running as the same Windows user on the unlocked machine**: that program can ask DPAPI too (the fixed "entropy" in the call only stops a program that does not know it from decrypting by accident). It is not a password, and the owner is asked for nothing. The access token the UI uses (`diya_token.hash`) and the Telegram and push keys are not covered by this change.

## 2. PKCE on the sign-in

The sign-in already used the system browser and a loopback port (RFC 8252). It now also sends a **PKCE** challenge (RFC 7636, `S256`) when it starts and the matching verifier when the code is exchanged, so an authorization code someone else caught on the loopback port is no use without the verifier, which never leaves the process. Google's documentation recommends it for installed apps; the stand-in test checks that the verifier sent matches the challenge sent first.

## 3. Disconnecting takes the permission back at Google

Pressing **Disconnect** used to forget the token here and leave Google's permission in place. It now also calls Google's revoke endpoint (`oauth2.googleapis.com/revoke`) and the page says what happened: *Google was told to forget the permission*, or *Google did not confirm...: you can remove Diya at myaccount.google.com/permissions*. Whatever Google does, the sign-in here is removed.

**One deliberate limit.** While **another Google card is still connected**, nothing is revoked. I could not confirm from Google's documentation whether revoking one refresh token of an app also ends the app's other grants, and signing the owner out of Gmail because they disconnected Tasks would be a surprise. So only the **last** Google card to be disconnected revokes; the page says nothing was sent in the meantime. This is a choice made without being able to test the real service, and it can be loosened if the real behaviour is shown to be per token.

## Proof

`tests/test_secrets.py`: protect and read back with a reversible stand-in for DPAPI (so the answer does not depend on the machine) and, on Windows only, one real DPAPI round trip; a plain file is read and upgraded once; an undecryptable file is "not connected"; protection off changes nothing; the client secret file follows the same rule; the PKCE pair, the URL, and the exchange; revoke only for the last card, a refusal or an unreachable Google never stops the disconnect, and the route's answer.

## Not done, from the same section of the blueprint

Storing the account's identity (`sub`, email) and checking it before a write (needs the `openid` and `email` scopes, an extra consent), several Google accounts, and a visible grant table with expiry (the approval system is the only grant today: nothing is pre-approved).
