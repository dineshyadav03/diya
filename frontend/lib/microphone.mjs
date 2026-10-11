// The microphone, for the message box's "Hold to talk" (docs/VOICE_DESIGN.md). Browser code with no address or token in it, and plain enough to be run under Node by the tests.

const SAVED_DEVICE = 'diya_mic_device'

// Why the microphone did not start, in words that say what to do. The browser's own message ("Permission denied", "Requested device not found") is the reason; these are the fix.
export function describeMicrophoneFailure(error) {
  const name = error?.name || ''
  if (name === 'InsecureContext') {
    return 'Microphone: the browser only allows the microphone on a secure address. Open Diya at https://localhost:3000 (not http://, and not an IP address), then try again.'
  }
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return 'Microphone: the browser is not letting this page use it. Click the icon at the left of the address bar (the lock or the sliders), set Microphone to Allow for this site, and reload. If it already says Allow, check Windows Settings, Privacy and security, Microphone.'
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'Microphone: no microphone was found. Plug one in, or pick one in the Windows sound settings (Input), then try again.'
  }
  if (name === 'NotReadableError' || name === 'AbortError') {
    return 'Microphone: it exists but would not start. Usually another app is using it, or the default microphone is a headset that is not connected or a virtual device with nothing on it. Close the other app, or choose a different default Input in the Windows sound settings, then try again.'
  }
  return `Microphone: it did not start (${name || 'unknown problem'}). Try again, or type your message.`
}

function savedDevice() {
  try {
    return localStorage.getItem(SAVED_DEVICE) || ''
  } catch {
    return ''
  }
}

function saveDevice(deviceId) {
  try {
    if (deviceId) localStorage.setItem(SAVED_DEVICE, deviceId)
    else localStorage.removeItem(SAVED_DEVICE)
  } catch {
    // a browser that will not keep a setting just asks again next time
  }
}

// Open a microphone. The default one first (or the one that worked last time); if that will not start, which is what happens when the default is a disconnected headset or a virtual cable,
// each real microphone in turn, remembering the first that works. A refusal (the person said no, or the browser did) is not retried: another device would be refused too.
// `media` is navigator.mediaDevices, passed in so a test can stand in for it.
export async function openMicrophone(media = globalThis.navigator?.mediaDevices) {
  if (!media?.getUserMedia) throw Object.assign(new Error('no secure context'), { name: 'InsecureContext' })
  const saved = savedDevice()
  const first = saved ? [{ audio: { deviceId: { exact: saved } } }, { audio: true }] : [{ audio: true }]
  let lastError
  for (const constraints of first) {
    try {
      return await media.getUserMedia(constraints)
    } catch (error) {
      lastError = error
      if (error?.name === 'NotAllowedError' || error?.name === 'SecurityError') throw error
    }
  }
  if (saved) saveDevice('') // the one that worked before does not any more
  let devices = []
  try {
    devices = (await media.enumerateDevices()).filter((d) => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications')
  } catch {
    devices = []
  }
  for (const device of devices) {
    try {
      const stream = await media.getUserMedia({ audio: { deviceId: { exact: device.deviceId } } })
      saveDevice(device.deviceId)
      return stream
    } catch (error) {
      lastError = error
    }
  }
  throw lastError
}

// How loud the microphone is right now, 0 to 1, for the listening orb. Returns a stop function. Quiet failure: no meter is better than no recording.
export function watchLevel(stream, onLevel) {
  try {
    const Context = globalThis.AudioContext || globalThis.webkitAudioContext
    if (!Context) return () => {}
    const context = new Context()
    const analyser = context.createAnalyser()
    analyser.fftSize = 256
    context.createMediaStreamSource(stream).connect(analyser)
    const samples = new Uint8Array(analyser.frequencyBinCount)
    let frame = 0
    let last = 0
    const tick = (now) => {
      if (now - last > 60) {
        last = now
        analyser.getByteTimeDomainData(samples)
        let peak = 0
        for (const value of samples) peak = Math.max(peak, Math.abs(value - 128))
        onLevel(Math.min(1, peak / 64))
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(frame)
      context.close().catch(() => {})
      onLevel(0)
    }
  } catch {
    return () => {}
  }
}
