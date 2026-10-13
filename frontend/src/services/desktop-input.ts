export const ESCAPE_KEYSYM = 0xff1b

const CONTROL_L = 0xffe3
const ALT_L = 0xffe9
const DELETE = 0xffff

export interface KeyEvent {
  pressed: 0 | 1
  keysym: number
}

export const CTRL_ALT_DEL: readonly KeyEvent[] = [
  { pressed: 1, keysym: CONTROL_L },
  { pressed: 1, keysym: ALT_L },
  { pressed: 1, keysym: DELETE },
  { pressed: 0, keysym: DELETE },
  { pressed: 0, keysym: ALT_L },
  { pressed: 0, keysym: CONTROL_L },
]

/** Detects a key pressed twice quickly; the caller supplies the clock so it can be tested. */
export class DoublePress {
  private lastPressAt: number | undefined
  private held = false

  constructor(private readonly windowMs: number) {}

  keyDown(at: number): boolean {
    // Guacamole's keyboard repeats a held key with more keydowns and no keyup between them.
    if (this.held) return false
    this.held = true
    const double = this.lastPressAt !== undefined && at - this.lastPressAt <= this.windowMs
    this.lastPressAt = double ? undefined : at
    return double
  }

  keyUp(): void {
    this.held = false
  }

  otherKey(): void {
    this.lastPressAt = undefined
  }
}
