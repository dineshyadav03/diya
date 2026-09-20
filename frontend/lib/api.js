// The Python/FastAPI backend (diya_web.py) always runs on port 8080 -- same
// host as this frontend, just a different port, so it works whether this
// page was opened as localhost or the LAN IP (phone testing) without any
// hardcoded address.
export function apiBase() {
  return `https://${window.location.hostname}:8080`
}
