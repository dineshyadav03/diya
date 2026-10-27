'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'

// The weather, for the whole app (docs/HOME_DESIGN.md): the panel on Home reads it, and the colour of the sky behind every page follows it (<html data-sky="rain" data-daytime="night">; the colours are in
// globals.css). It is asked for ten minutes apart. The place is only ever one the person shared with the button on Home: the browser asks them, the API keeps it (rounded) on this computer, and only the
// weather service gets it. Without one there is no weather and the sky is the usual one. Every word shown came from the API as data and is rendered as text.

const REFRESH_MS = 10 * 60_000
const SKIES = ['clear', 'cloudy', 'fog', 'rain', 'snow', 'storm']
const WeatherContext = createContext({ weather: null, problem: '', share: () => {}, forget: () => {} })

export function useWeather() {
  return useContext(WeatherContext)
}

export default function WeatherProvider({ children }) {
  const [weather, setWeather] = useState(null) // null = not asked yet
  const [problem, setProblem] = useState('') // why sharing the place did not work

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/weather')
      const body = response.ok ? await response.json().catch(() => null) : null
      if (body && typeof body.known === 'boolean') setWeather(body)
    } catch {}
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') load()
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  // The sky follows the weather; with none known it is the usual one.
  useEffect(() => {
    const root = document.documentElement
    if (weather && weather.known && SKIES.includes(weather.sky)) {
      root.dataset.sky = weather.sky
      root.dataset.daytime = weather.day ? 'day' : 'night'
    } else {
      delete root.dataset.sky
      delete root.dataset.daytime
    }
  }, [weather])

  const share = useCallback(() => {
    setProblem('')
    if (!navigator.geolocation) {
      setProblem('This browser cannot tell where you are.')
      return
    }
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const response = await fetch('/api/weather', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat: position.coords.latitude, lon: position.coords.longitude }),
          })
          const body = response.ok ? await response.json().catch(() => null) : null
          if (body && typeof body.known === 'boolean') setWeather(body)
          else setProblem('Diya could not keep your location. Nothing was changed.')
        } catch {
          setProblem('Diya could not keep your location. Nothing was changed.')
        }
      },
      () => setProblem('The browser did not share your location. Allow it for this site, then try again.'),
      { maximumAge: 600_000, timeout: 15_000 }
    )
  }, [])

  const forget = useCallback(async () => {
    try {
      const response = await fetch('/api/weather', { method: 'DELETE' })
      if (response.ok) setWeather({ known: false })
    } catch {}
  }, [])

  return <WeatherContext.Provider value={{ weather, problem, share, forget }}>{children}</WeatherContext.Provider>
}
