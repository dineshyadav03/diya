import './globals.css'

export const metadata = {
  title: 'Diya',
}

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  // The app's one surface (--bg in globals.css): what the phone's status bar takes on.
  themeColor: '#25221d',
  colorScheme: 'dark',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
