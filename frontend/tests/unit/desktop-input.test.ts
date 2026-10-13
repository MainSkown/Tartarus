import { describe, expect, it } from 'vitest'
import { CTRL_ALT_DEL, DoublePress, ESCAPE_KEYSYM } from '@/services/desktop-input'

describe('CTRL_ALT_DEL', () => {
  it('presses Control_L, Alt_L and Delete, then lets go in the opposite order', () => {
    expect(CTRL_ALT_DEL).toEqual([
      { pressed: 1, keysym: 0xffe3 },
      { pressed: 1, keysym: 0xffe9 },
      { pressed: 1, keysym: 0xffff },
      { pressed: 0, keysym: 0xffff },
      { pressed: 0, keysym: 0xffe9 },
      { pressed: 0, keysym: 0xffe3 },
    ])
  })
})

describe('ESCAPE_KEYSYM', () => {
  it('is the X11 Escape keysym', () => {
    expect(ESCAPE_KEYSYM).toBe(0xff1b)
  })
})

describe('DoublePress', () => {
  function pressAndRelease(detector: DoublePress, at: number): boolean {
    const double = detector.keyDown(at)
    detector.keyUp()
    return double
  }

  it('does not fire on a single press', () => {
    expect(pressAndRelease(new DoublePress(400), 1000)).toBe(false)
  })

  it('fires on the second press inside the window', () => {
    const detector = new DoublePress(400)
    pressAndRelease(detector, 1000)
    expect(pressAndRelease(detector, 1300)).toBe(true)
  })

  it('does not fire when the second press comes after the window', () => {
    const detector = new DoublePress(400)
    pressAndRelease(detector, 1000)
    expect(pressAndRelease(detector, 1401)).toBe(false)
  })

  it('does not read a held key repeating as a second press', () => {
    const detector = new DoublePress(400)
    detector.keyDown(1000)
    expect(detector.keyDown(1050)).toBe(false)
    expect(detector.keyDown(1100)).toBe(false)
  })

  it('needs a fresh pair after firing, so a third press is not a second double', () => {
    const detector = new DoublePress(400)
    pressAndRelease(detector, 1000)
    expect(pressAndRelease(detector, 1200)).toBe(true)
    expect(pressAndRelease(detector, 1300)).toBe(false)
  })

  it('forgets the first press when another key was typed between', () => {
    const detector = new DoublePress(400)
    pressAndRelease(detector, 1000)
    detector.otherKey()
    expect(pressAndRelease(detector, 1200)).toBe(false)
  })
})
