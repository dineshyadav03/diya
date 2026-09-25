# LAN mode and certificates

By default the API and the UI are reachable from this computer only. This page covers TLS
certificates and using Diya from a phone or another machine.

## Certificates (mkcert)

Browsers allow the microphone only on secure origins, and the backend refuses to start without a
certificate. [mkcert](https://github.com/FiloSottile/mkcert) makes one your browser trusts:

```bash
mkcert -install                       # once per machine
mkcert localhost 127.0.0.1 ::1        # writes localhost+2.pem and localhost+2-key.pem
```

Run the second command in the repo root. The number in the file names counts the names after
the first. Keep exactly one such pair there: the backend and `npm run dev` both find it, and two
pairs are an error, not a guess. To use files elsewhere, set `DIYA_SSL_CERT` and `DIYA_SSL_KEY`
(both, or neither; relative paths are read from the repo root). The files are gitignored.

## Using it from another device

1. Add the name or IPv4 address the device will use to the certificate
   (`mkcert localhost 127.0.0.1 ::1 <name-or-ip>`) and remove the old pair.
2. Install and trust mkcert's root CA on the device. `mkcert -CAROOT` shows where it is; on iOS,
   trust it under Settings > General > About > Certificate Trust Settings.
3. Start the UI with `npm run dev:lan` (in `frontend/`), open `https://<name-or-ip>:3000` on the
   device, and allow inbound TCP 3000 in the operating system's firewall. The API can stay as it is,
   on this computer only: see "How the UI reaches the API" below.
4. Only if another device should call the API directly (curl, a script), start it in LAN mode with
   that same name or address, and allow inbound TCP 8080 too.
   PowerShell: `$env:DIYA_LAN = "1"; $env:DIYA_ALLOWED_HOSTS = "<name-or-ip>"; python diya_web.py`
   POSIX: `DIYA_LAN=1 DIYA_ALLOWED_HOSTS=<name-or-ip> python diya_web.py`

## How the UI reaches the API

The browser only ever talks to the UI, on its own origin. The UI's `/api/*` routes
(`frontend/app/api`) run on the UI's server, which forwards each one to the API at
`https://127.0.0.1:<DIYA_PORT>` (default 8080) and hands the answer back. The address comes from
configuration, never from the browser's request, so a phone at `https://<name-or-ip>:3000`, or a
request with a forged `Host`, changes nothing about where the forwarded request goes.

- **Access token.** The API requires one by default, so the UI server attaches it and the browser
  never holds it. Put the token the API printed at its first start in `DIYA_TOKEN` in the
  environment of the terminal that runs `npm run dev` (PowerShell: `$env:DIYA_TOKEN = "<token>"`;
  POSIX: `export DIYA_TOKEN=<token>`), or on a line `DIYA_TOKEN=<token>` in `frontend/.env.local`
  (gitignored). Only a hash is kept, so a lost token can't be shown again: start the API once with
  `--rotate-token` (or `DIYA_ROTATE_TOKEN=1`, removed again afterwards) and use the new one. Without
  `DIYA_TOKEN` (or with a wrong one) the API's 401 comes straight through, `npm run dev` says so at
  startup, and the chat, the History page and the microphone each say the access token the UI sends
  is missing or wrong, rather than that the server didn't answer (which is what they say when nothing
  is listening). Only the
  content type and that token are taken from the browser's request; its cookies, `Authorization`
  and everything else are dropped. The token is only sent over https, or to this computer itself.
- **Settings.** `DIYA_PORT` (the API's port; the UI server follows it, so a non-default port now
  works) and `DIYA_API_URL` (an `https://host:port` origin, for an API that is not on this
  computer's loopback address).
- **Certificate trust.** The UI server's own HTTPS call to the API must trust your mkcert root CA,
  and Node, unlike a browser, does not use the operating system's trust store unless told to.
  `npm run dev` starts Node with `--use-system-ca` (Node 22.15 or newer), which reads the store
  `mkcert -install` filled. On an older Node, set `NODE_EXTRA_CA_CERTS` to the `rootCA.pem` in the
  folder `mkcert -CAROOT` prints. If it fails, `/api/*` answers 502 with a message saying so.

## What LAN mode does

- The API listens on all interfaces but answers only loopback and the names in
  `DIYA_ALLOWED_HOSTS` (plain names or IPv4 addresses, no port or wildcard). Any other `Host` gets a 400.
- It accepts browser origins `https://<allowed name>:<DIYA_FRONTEND_PORT>` (default 3000) and
  refuses others with a 403. CORS names those origins; it is never `*`. The UI no longer makes
  such cross-origin calls itself, so these matter for a page that calls the API directly.
- The server refuses to start with a non-loopback `DIYA_HOST` and no `DIYA_LAN=1`, or with
  `DIYA_LAN=1` and no allowed hosts.
- `npm run dev` listens on 127.0.0.1 only; `npm run dev:lan` on all interfaces. Neither turns LAN
  mode on for the API: step 4 does, and the UI does not need it.

**The API requires its access token by default.** Anything that calls it directly (curl, a script)
sends `Authorization: Bearer <token>`; another process on this computer, or a device on the LAN that
merely knows an allowed `Host`, is refused with a 401, docs pages included. `DIYA_REQUIRE_TOKEN=0` is
the explicit opt-out for anyone who deliberately wants the old unauthenticated API (the token is still
generated, so turning the requirement back on needs nothing new); with it, use LAN mode only on a
network you trust, and set `DIYA_REQUIRE_TOKEN=0` for the UI too if you want its startup hint gone.
