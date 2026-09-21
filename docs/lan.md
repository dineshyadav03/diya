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
3. Start the API in LAN mode with that same name or address.
   PowerShell: `$env:DIYA_LAN = "1"; $env:DIYA_ALLOWED_HOSTS = "<name-or-ip>"; python diya_web.py`
   POSIX: `DIYA_LAN=1 DIYA_ALLOWED_HOSTS=<name-or-ip> python diya_web.py`
4. Start the UI with `npm run dev:lan` (in `frontend/`), open `https://<name-or-ip>:3000` on the
   device, and allow inbound TCP 8080 and 3000 in the operating system's firewall.

## What LAN mode does

- The API listens on all interfaces but answers only loopback and the names in
  `DIYA_ALLOWED_HOSTS` (plain names or IPv4 addresses, no port or wildcard). Any other `Host` gets a 400.
- It accepts browser origins `https://<allowed name>:<DIYA_FRONTEND_PORT>` (default 3000) and
  refuses others with a 403. CORS names those origins; it is never `*`.
- The server refuses to start with a non-loopback `DIYA_HOST` and no `DIYA_LAN=1`, or with
  `DIYA_LAN=1` and no allowed hosts.
- `npm run dev` listens on 127.0.0.1 only; `npm run dev:lan` on all interfaces. `npm run dev:lan` does
  not turn LAN mode on for the API: step 3 does.
- The UI calls the API at `https://<page hostname>:8080`. That port is fixed in `frontend/lib/api.js`.

**There is no login yet.** In LAN mode, any device that can reach the port and sends an allowed
`Host` can use the API. Use it on a network you trust. The per-install token is on the
[roadmap](../ROADMAP.md).
