import './globals.css'

export const metadata = {
  title: 'Diya',
}

export const viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  // The asset's cream: what the phone's status bar takes on above the header.
  themeColor: '#faf8f4',
}

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
