'use client'

import Chat from '../page'
import HomeCards from '../../components/HomeCards'

// Home, in the shape of Hark's: the things Diya found for today at the left, the one chat beside them (docs/HOME_DESIGN.md). The chat is the same page as the Chat tab, so what is said here is said
// in the one chat, and an action waiting for your yes is asked in the strip under it. On a narrow screen only the cards are shown; the Chat tab is the chat.
export default function HomePage() {
  return (
    <main className="home-split">
      <HomeCards />
      <div className="home-chat">
        <Chat />
      </div>
    </main>
  )
}
