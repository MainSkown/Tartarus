import type { GuacamoleModule } from '@/services/desktop-guacamole'

const CLIENT_STATE = { IDLE: 0, CONNECTING: 1, WAITING: 2, CONNECTED: 3, DISCONNECTING: 4, DISCONNECTED: 5 } as const

type Tunnel = {
  oninstruction: ((opcode: string, args: unknown[]) => void) | null
  connect(): void
  disconnect(): void
}

export class FakeDisplay {
  readonly element = document.createElement('div')
  width = 1280
  height = 800
  scales: number[] = []
  cursorShown: boolean[] = []
  onresize: ((width: number, height: number) => void) | null = null

  getElement(): HTMLElement {
    return this.element
  }
  getWidth(): number {
    return this.width
  }
  getHeight(): number {
    return this.height
  }
  showCursor(shown: boolean): void {
    this.cursorShown.push(shown)
  }
  scale(factor: number): void {
    this.scales.push(factor)
  }
  resizeGuest(width: number, height: number): void {
    this.width = width
    this.height = height
    this.onresize?.(width, height)
  }
}

export class FakeClient {
  static instances: FakeClient[] = []
  static get latest(): FakeClient {
    return FakeClient.instances.at(-1)!
  }

  readonly display = new FakeDisplay()
  state: number = CLIENT_STATE.IDLE
  onstatechange: ((state: number) => void) | null = null
  onerror: ((status: { code: number; message: string }) => void) | null = null
  keyEvents: [number, number][] = []
  mouseStates: [unknown, unknown][] = []
  disconnected = 0
  connectedWith: unknown[] = []
  clipboardStreams = 0

  constructor(readonly tunnel: Tunnel) {
    FakeClient.instances.push(this)
    tunnel.oninstruction = () => undefined
  }

  getDisplay(): FakeDisplay {
    return this.display
  }
  connect(data?: unknown): void {
    this.connectedWith.push(data)
    this.setState(CLIENT_STATE.WAITING)
    this.tunnel.connect()
  }
  disconnect(): void {
    if (this.state === CLIENT_STATE.DISCONNECTED) return
    this.disconnected += 1
    this.setState(CLIENT_STATE.DISCONNECTED)
    this.tunnel.disconnect()
  }
  sendKeyEvent(pressed: number, keysym: number): void {
    if (this.state === CLIENT_STATE.CONNECTED) this.keyEvents.push([pressed, keysym])
  }
  sendMouseState(state: unknown, applyDisplayScale?: boolean): void {
    if (this.state === CLIENT_STATE.CONNECTED) this.mouseStates.push([state, applyDisplayScale])
  }
  createClipboardStream(): never {
    this.clipboardStreams += 1
    throw new Error('the desktop panel must never open a clipboard stream')
  }

  firstFrame(): void {
    this.setState(CLIENT_STATE.CONNECTED)
  }
  guacdError(message: string, code = 0x0205): void {
    this.onerror?.({ code, message })
    this.disconnect()
  }
  private setState(state: number): void {
    this.state = state
    this.onstatechange?.(state)
  }
}

export class FakeMouse {
  static instances: FakeMouse[] = []
  static get latest(): FakeMouse {
    return FakeMouse.instances.at(-1)!
  }

  private handlers = new Map<string, (event: { state: unknown }) => void>()

  constructor(readonly element: HTMLElement) {
    FakeMouse.instances.push(this)
  }

  onEach(events: string[], handler: (event: { state: unknown }) => void): void {
    for (const name of events) this.handlers.set(name, handler)
  }
  on(event: string, handler: (event: { state: unknown }) => void): void {
    this.handlers.set(event, handler)
  }
  leave(): void {
    this.handlers.get('mouseout')?.({ state: {} })
  }
  move(state: unknown): void {
    this.handlers.get('mousemove')?.({ state })
  }
  down(state: unknown): void {
    this.handlers.get('mousedown')?.({ state })
  }
}

export class FakeKeyboard {
  static instances: FakeKeyboard[] = []
  static get latest(): FakeKeyboard {
    return FakeKeyboard.instances.at(-1)!
  }

  onkeydown: ((keysym: number) => boolean | void) | null = null
  onkeyup: ((keysym: number) => void) | null = null
  resets = 0
  private held = new Set<number>()

  constructor(readonly element: HTMLElement) {
    FakeKeyboard.instances.push(this)
  }

  /** What the browser does with the key: false when the handler cancelled it. */
  press(keysym: number): boolean | void {
    this.held.add(keysym)
    return this.onkeydown?.(keysym)
  }
  release(keysym: number): void {
    this.held.delete(keysym)
    this.onkeyup?.(keysym)
  }
  reset(): void {
    this.resets += 1
    for (const keysym of this.held) this.onkeyup?.(keysym)
    this.held.clear()
  }
}

export function resetFakeGuacamole(): void {
  FakeClient.instances = []
  FakeMouse.instances = []
  FakeKeyboard.instances = []
}

/** The real library's Parser and Tunnel, so the tunnel parses real frames, with the browser-facing pieces faked. */
export async function fakeGuacamole(): Promise<GuacamoleModule> {
  const real = ((await import('guacamole-common-js')) as unknown as { default: GuacamoleModule }).default
  return {
    Parser: real.Parser,
    Tunnel: real.Tunnel,
    Client: Object.assign(FakeClient, { State: CLIENT_STATE }),
    Mouse: FakeMouse,
    Keyboard: FakeKeyboard,
  } as unknown as GuacamoleModule
}
