import { NextResponse } from 'next/server'
import { guard } from './server/ui-login.mjs'

// The login in front of the UI (docs/UI_LOGIN_DESIGN.md): with DIYA_UI_PASSCODE set, a request without a good session cookie is turned
// away before any page or route runs. Without it, this lets everything through, as the UI always did. All the deciding is in
// server/ui-login.mjs; this file only hands it the request and the environment.
export async function middleware(request) {
  const turnedAway = await guard(request, process.env)
  return turnedAway ?? NextResponse.next()
}

// Everything except the framework's static files and images, which carry no data and are needed to draw the sign-in page.
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|icons/|diya-flame.svg).*)'],
}
