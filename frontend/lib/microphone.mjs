// The microphone, for the message box's "Tap to talk" (docs/VOICE_DESIGN.md). Browser code with no address or token in it, and plain enough to be run under Node by the tests.

const SAVED_DEVICE = 'diya_mic_device'
// The loudest the microphone got during a recording, 0 to 1 on watchLevel's scale: under this nothing was said, or this is not the microphone that was spoken into. (Speech into a laptop
// microphone reaches 0.2 or more; a silent virtual cable, a muted device and a disconnected headset stay at 0.)
export const SILENT_BELOW = 0.04
const silent = new Set() // devices that gave no sound this session, by id and by group (one physical microphone shows up under several ids)

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
  if (name === 'NoSoundAnywhere') {
    return 'Microphone: none of the microphones this browser can see picked up any sound. In Windows Settings, System, Sound, Input, speak and watch the bar move: pick the device whose bar moves, make it the default, then tap the mic and try again.'
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

// Which device a stream is from: its id, its group (the same physical microphone under another id) and its name, for words like "nothing was heard from X". A stand-in stream without
// tracks, as the tests use, has none of these.
export function deviceOf(stream) {
  try {
    const track = stream?.getAudioTracks?.()[0]
    const settings = track?.getSettings?.() || {}
    return { id: settings.deviceId || '', groupId: settings.groupId || '', label: track?.label || '' }
  } catch {
    return { id: '', groupId: '', label: '' }
  }
}

function isSilent(id, groupId) {
  return (!!id && silent.has(id)) || (!!groupId && silent.has('group:' + groupId))
}

// This stream picked up nothing: do not offer that microphone again this session (nor the same one under another id), and forget it if it was the remembered one.
export function markSilent(stream) {
  const { id, groupId } = deviceOf(stream)
  if (id) silent.add(id)
  if (groupId) silent.add('group:' + groupId)
  if (id && savedDevice() === id) saveDevice('')
}

// This stream picked up sound: if it is a particular microphone and not "whatever the default is", remember it, so it is the first one tried next time.
export function markWorking(stream) {
  const { id } = deviceOf(stream)
  if (id && id !== 'default' && id !== 'communications') saveDevice(id)
}

// Forget which microphones were silent (a test, or a new session of use).
export function forgetSilent() {
  silent.clear()
}

// Open a microphone. The default one first (or the one that worked last time); if that will not start, which is what happens when the default is a disconnected headset or a virtual cable,
// each real microphone in turn, remembering the first that works; one that was heard to give no sound (markSilent) is not offered again, so each silent try moves on to the next microphone, and
// when none is left that is its own error (NoSoundAnywhere) rather than a loop. A refusal (the person said no, or the browser did) is not retried: another device would be refused too.
// `media` is navigator.mediaDevices, passed in so a test can stand in for it.
export async function openMicrophone(media = globalThis.navigator?.mediaDevices) {
  if (!media?.getUserMedia) throw Object.assign(new Error('no secure context'), { name: 'InsecureContext' })
  const saved = savedDevice()
  const first = []
  if (saved && !isSilent(saved, '')) first.push({ audio: { deviceId: { exact: saved } } })
  if (!isSilent('default', '')) first.push({ audio: true })
  let lastError
  let offered = first.length
  for (const constraints of first) {
    try {
      const stream = await media.getUserMedia(constraints)
      const got = deviceOf(stream)
      if (!isSilent(got.id, got.groupId)) return stream
      stream.getTracks?.().forEach((track) => track.stop()) // the default turned out to be a microphone already heard to be silent
      offered -= 1
    } catch (error) {
      lastError = error
      if (error?.name === 'NotAllowedError' || error?.name === 'SecurityError') throw error
    }
  }
  if (saved && first.length) saveDevice('') // the one that worked before does not any more
  let devices = []
  try {
    devices = (await media.enumerateDevices()).filter((d) => d.kind === 'audioinput' && d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications')
  } catch {
    devices = []
  }
  for (const device of devices) {
    if (isSilent(device.deviceId, device.groupId)) continue
    offered += 1
    try {
      const stream = await media.getUserMedia({ audio: { deviceId: { exact: device.deviceId } } })
      saveDevice(device.deviceId)
      return stream
    } catch (error) {
      lastError = error
    }
  }
  if (offered === 0 && silent.size) {
    silent.clear() // start over next time, rather than refusing for good
    throw Object.assign(new Error('no microphone gave any sound'), { name: 'NoSoundAnywhere' })
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
