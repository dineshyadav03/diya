// The orb: Diya's own sign that she is doing something (docs/UI_DESIGN.md, "The orbs are back"). Pure CSS, no library: a soft glowing sphere with a turning ring.
//   state="thinking"   breathing, with the ring turning: waiting for the model
//   state="listening"  the sphere swells with how loud the microphone is (`level`, 0 to 1)
//   state="speaking"   the ring pulses outward while a reply is read aloud
// It is decoration: hidden from screen readers, which are told in words by the element around it. With reduced motion switched on the stylesheet stops every animation, and what is left is a still sphere.
export default function Orb({ state = 'thinking', level = 0, size = 28 }) {
  return (
    <span className={`orb orb--${state}`} style={{ '--orb-size': `${size}px`, '--orb-level': String(level) }} aria-hidden="true">
      <span className="orb-core" />
      <span className="orb-ring" />
    </span>
  )
}
