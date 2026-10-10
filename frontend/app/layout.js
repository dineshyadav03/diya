import './globals.css'
import AppShell from '../components/AppShell'

export const metadata = {
  title: 'Diya',
}

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  // The page colour of each theme (--bg in globals.css): what a phone's status bar takes on.
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f6f5f4' },
    { media: '(prefers-color-scheme: dark)', color: '#0a0a0a' },
  ],
  colorScheme: 'light dark',
}

// Runs before the page paints, so a person who chose Light or Dark never sees the other for a moment. The choice lives in this
// browser only (localStorage); with none, the operating system's setting decides (globals.css). Written as a fixed string.
const THEME_BEFORE_PAINT = "try{var t=localStorage.getItem('diya_theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}"

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BEFORE_PAINT }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  )
}
