/** @type {import('next').NextConfig} */
const nextConfig = {
  // The development server draws a floating "N" badge in the bottom-left corner of every page. It sits on top of the sidebar's
  // foot (Sign out, the theme choice) and the composer's "New chat", and this UI is only ever run in development (docs/lan.md).
  // Errors still show as an overlay.
  devIndicators: false,
}

export default nextConfig
