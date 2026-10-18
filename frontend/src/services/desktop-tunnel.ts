import type { Tunnel } from 'guacamole-common-js'
import { t } from '@/i18n'
import type { GuacamoleModule } from '@/services/desktop-guacamole'

type SocketFactory = (url: string) => WebSocket
type Library = Pick<GuacamoleModule, 'Parser' | 'Tunnel'>

const INTERNAL_OPCODE = ''
const PING_INTERVAL_MS = 500
const SOCKET_OPEN = 1
const CLOSE_NORMAL = 1000
const CLOSE_PROTOCOL_ERROR = 1002
const CLOSE_ABNORMAL = 1006
const SUBPROTOCOL = 'guacamole'

function encodeInstruction(elements: unknown[]): string {
  return elements.map((element) => `${String(element).length}.${String(element)}`).join(',') + ';'
}

/**
 * A Guacamole tunnel over a WebSocket, written against the library's Tunnel contract because
 * its own WebSocketTunnel hides the close code: it turns a close reason into `parseInt(reason)`,
 * which is NaN for the backend's human reasons, and offers no way to read the code itself.
 */
export class DesktopTunnel implements Tunnel {
  receiveTimeout = 15_000
  unstableThreshold = 1_500
  state: Tunnel['state']
  uuid: string | null = null
  onuuid: Tunnel['onuuid'] = null
  onerror: Tunnel['onerror'] = null
  onstatechange: Tunnel['onstatechange'] = null
  oninstruction: Tunnel['oninstruction'] = null
  /** Called once when the far end or the network ends the tunnel; not for a `disconnect()` of our own. */
  onclose: ((code: number, reason: string) => void) | null = null

  private socket: WebSocket | undefined
  private receiveTimer: ReturnType<typeof setTimeout> | undefined
  private unstableTimer: ReturnType<typeof setTimeout> | undefined
  private pingTimer: ReturnType<typeof setTimeout> | undefined
  private lastPingAt = 0
  private readonly parser: InstanceType<Library['Parser']>
  private readonly states: Library['Tunnel']['State']

  constructor(
    library: Library,
    private readonly url: string,
    private readonly socketFactory: SocketFactory = (url) => new WebSocket(url, SUBPROTOCOL),
  ) {
    this.states = library.Tunnel.State
    this.state = this.states.CLOSED
    this.parser = new library.Parser()
    this.parser.oninstruction = (opcode, args) => this.handleInstruction(opcode, args as string[])
  }

  connect(): void {
    this.setState(this.states.CONNECTING)
    this.resetTimers()
    const socket = this.socketFactory(this.url)
    this.socket = socket
    socket.onopen = () => this.resetTimers()
    socket.onmessage = (event) => this.receive(String(event.data))
    socket.onclose = (event) => {
      if (this.shutdown(false)) this.onclose?.(event.code, event.reason)
    }
  }

  disconnect(): void {
    this.shutdown(true)
  }

  isConnected(): boolean {
    return this.state === this.states.OPEN || this.state === this.states.UNSTABLE
  }

  sendMessage(...elements: unknown[]): void {
    if (!this.isConnected() || elements.length === 0 || this.socket?.readyState !== SOCKET_OPEN) return
    this.socket.send(encodeInstruction(elements))
  }

  private setState(state: Tunnel['state']): void {
    if (state === this.state) return
    this.state = state
    this.onstatechange?.(state)
  }

  private receive(frame: string): void {
    this.resetTimers()
    try {
      this.parser.receive(frame)
    } catch {
      this.fail(CLOSE_PROTOCOL_ERROR, t('live.desktop.tunnel.malformed'))
    }
  }

  private handleInstruction(opcode: string, args: string[]): void {
    if (this.uuid === null) {
      if (opcode === INTERNAL_OPCODE && args.length === 1) {
        this.uuid = args[0]!
        this.onuuid?.(this.uuid)
      }
      this.setState(this.states.OPEN)
    }
    if (opcode !== INTERNAL_OPCODE) this.oninstruction?.(opcode, args)
  }

  // The server echoes each ping, and every frame re-arms the next one: the loop is the keep-alive,
  // and its silence is how a dead connection is noticed.
  private resetTimers(): void {
    this.clearTimers()
    if (this.state === this.states.UNSTABLE) this.setState(this.states.OPEN)
    this.receiveTimer = setTimeout(() => this.fail(CLOSE_ABNORMAL, t('live.desktop.tunnel.noData')), this.receiveTimeout)
    this.unstableTimer = setTimeout(() => this.setState(this.states.UNSTABLE), this.unstableThreshold)
    this.pingTimer = setTimeout(() => this.sendPing(), Math.max(this.lastPingAt + PING_INTERVAL_MS - Date.now(), 0))
  }

  private sendPing(): void {
    this.lastPingAt = Date.now()
    this.sendMessage(INTERNAL_OPCODE, 'ping', this.lastPingAt)
  }

  private clearTimers(): void {
    clearTimeout(this.receiveTimer)
    clearTimeout(this.unstableTimer)
    clearTimeout(this.pingTimer)
  }

  private fail(code: number, reason: string): void {
    if (this.shutdown(true)) this.onclose?.(code, reason)
  }

  /** Stops the tunnel; true when it was still running, so a close is reported once. */
  private shutdown(closeSocket: boolean): boolean {
    this.clearTimers()
    const wasRunning = this.socket !== undefined
    if (closeSocket) this.socket?.close(CLOSE_NORMAL)
    this.socket = undefined
    this.setState(this.states.CLOSED)
    return wasRunning
  }
}
