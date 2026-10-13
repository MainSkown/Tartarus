import type { Mouse } from 'guacamole-common-js'
import { DesktopTunnel } from '@/services/desktop-tunnel'
import { phaseAfterClose, phaseAfterGuacdError, type DesktopPhase } from '@/services/desktop-close'
import type { GuacamoleModule } from '@/services/desktop-guacamole'
import { CTRL_ALT_DEL, DoublePress, ESCAPE_KEYSYM } from '@/services/desktop-input'
import { fitScale, type Size } from '@/services/desktop-scale'

// Two Escapes closer together than this leave the panel; a person's double tap is well inside it.
const ESCAPE_WINDOW_MS = 500
const MOUSE_EVENTS = ['mousedown', 'mouseup', 'mousemove']

export interface DesktopState {
  phase: DesktopPhase
  reason: string
}

export interface DesktopSessionOptions {
  guacamole: GuacamoleModule
  url: string
  /** The focusable element: the keyboard listens here, so keys typed elsewhere never reach the guest. */
  panel: HTMLElement
  /** Where the guest's display is shown. */
  stage: HTMLElement
  onChange: (state: DesktopState) => void
  socketFactory?: (url: string) => WebSocket
  now?: () => number
}

type Client = InstanceType<GuacamoleModule['Client']>
type Keyboard = InstanceType<GuacamoleModule['Keyboard']>

interface Running {
  client: Client
  tunnel: DesktopTunnel
  keyboard: Keyboard
  display: HTMLElement
}

/** One connection to the guest's desktop: the tunnel, the Guacamole client and the input it forwards. */
export class DesktopSession {
  private running: Running | undefined
  private connected = false
  private captured = false
  private room: Size | undefined
  private readonly doublePress = new DoublePress(ESCAPE_WINDOW_MS)
  private readonly releaseHeldKeys = (): void => {
    if (this.captured) this.running?.keyboard.reset()
  }

  constructor(private readonly options: DesktopSessionOptions) {}

  connect(): void {
    if (this.running) return
    const { guacamole, url, panel, stage, socketFactory } = this.options
    const tunnel = new DesktopTunnel(guacamole, url, socketFactory)
    const client = new guacamole.Client(tunnel)
    const display = client.getDisplay()
    const displayElement = display.getElement()
    this.running = { client, tunnel, keyboard: new guacamole.Keyboard(panel), display: displayElement }
    this.connected = false

    displayElement.style.cursor = 'none'
    const mouse = new guacamole.Mouse(displayElement)
    mouse.onEach(MOUSE_EVENTS, (event) => {
      display.showCursor(true)
      client.sendMouseState((event as Mouse.Event).state, true)
    })
    mouse.on('mouseout', () => display.showCursor(false))
    display.onresize = () => this.refit()
    tunnel.onuuid = () => {
      if (!this.connected) this.emit('waiting')
    }
    tunnel.onclose = (code, reason) => this.end(phaseAfterClose(code, this.connected), reason)
    client.onstatechange = (state) => {
      if (state === guacamole.Client.State.CONNECTED) this.markConnected()
    }
    client.onerror = (status) => this.end(phaseAfterGuacdError(this.connected), status.message ?? '')
    window.addEventListener('blur', this.releaseHeldKeys)

    stage.append(displayElement)
    this.emit('connecting')
    this.refit()
    client.connect()
  }

  disconnect(): void {
    this.teardown()
  }

  capture(): void {
    const running = this.running
    if (!running || this.captured) return
    this.captured = true
    this.doublePress.otherKey()
    running.keyboard.onkeydown = (keysym) => this.forwardKeyDown(keysym)
    running.keyboard.onkeyup = (keysym) => this.forwardKeyUp(keysym)
  }

  release(): void {
    const running = this.running
    if (!running || !this.captured) return
    running.keyboard.reset()
    running.keyboard.onkeydown = null
    running.keyboard.onkeyup = null
    this.captured = false
  }

  sendCtrlAltDel(): void {
    if (!this.running || !this.connected) return
    for (const { pressed, keysym } of CTRL_ALT_DEL) this.running.client.sendKeyEvent(pressed, keysym)
  }

  fit(room: Size): void {
    this.room = room
    this.refit()
  }

  private forwardKeyDown(keysym: number): boolean {
    if (!this.running || !this.connected) return true
    if (keysym !== ESCAPE_KEYSYM) {
      this.doublePress.otherKey()
    } else if (this.doublePress.keyDown(this.now())) {
      // The library arms a key repeat once this handler returns; releasing inside it would leave that repeat running.
      queueMicrotask(() => this.leavePanel())
      return false
    }
    this.running.client.sendKeyEvent(1, keysym)
    return false
  }

  private leavePanel(): void {
    this.options.panel.blur()
    this.release()
  }

  private forwardKeyUp(keysym: number): void {
    if (keysym === ESCAPE_KEYSYM) this.doublePress.keyUp()
    if (this.running && this.connected) this.running.client.sendKeyEvent(0, keysym)
  }

  private refit(): void {
    if (!this.running || !this.room) return
    const display = this.running.client.getDisplay()
    const scale = fitScale(this.room, { width: display.getWidth(), height: display.getHeight() })
    if (scale !== undefined) display.scale(scale)
  }

  private markConnected(): void {
    this.connected = true
    this.emit('connected')
  }

  private end(phase: DesktopPhase, reason: string): void {
    if (!this.running) return
    this.teardown()
    this.options.onChange({ phase, reason })
  }

  private teardown(): void {
    const running = this.running
    if (!running) return
    this.release()
    this.running = undefined
    window.removeEventListener('blur', this.releaseHeldKeys)
    running.display.remove()
    running.client.onerror = null
    running.client.onstatechange = null
    running.tunnel.onclose = null
    running.client.disconnect()
  }

  private emit(phase: DesktopPhase, reason = ''): void {
    this.options.onChange({ phase, reason })
  }

  private now(): number {
    return (this.options.now ?? Date.now)()
  }
}
