import { ref, type Ref } from 'vue'
import type { HealthMessage } from '@/api'

export type WsConnectionState = 'connecting' | 'open' | 'reconnecting' | 'closed'

type MessageParser<T> = (raw: unknown) => T | undefined
type MessageHandler<T> = (message: T) => void
type CloseHandler = (code: number) => void
type WebSocketFactory = (url: string) => WebSocket

const SOCKET_OPEN = 1
// What a browser reports for a socket that died without a close frame.
const ABNORMAL_CLOSE = 1006

const MIN_BACKOFF_MS = 500
const MAX_BACKOFF_MS = 30_000

export function resolveWsUrl(path: string): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}${path}`
}

function backoffDelayMs(attempt: number): number {
  const ceiling = Math.min(MIN_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS)
  // Half-jitter: spreads reconnects from many tabs instead of all retrying in lockstep,
  // while keeping a floor so the delay never collapses to near-zero.
  return ceiling / 2 + Math.random() * (ceiling / 2)
}

/**
 * A typed WebSocket client that reconnects with capped exponential backoff and stays
 * connected until the caller explicitly calls `disconnect()`. Connection state and the last
 * received message are exposed as Vue refs so a component or store can react to them directly.
 */
export class ReconnectingWebSocketClient<T> {
  readonly state: Ref<WsConnectionState> = ref('closed')
  readonly lastMessage: Ref<T | undefined> = ref(undefined)

  private socket: WebSocket | undefined
  private attempt = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined
  private explicitlyDisconnected = false
  private readonly subscribers = new Set<MessageHandler<T>>()
  private readonly closeHandlers = new Set<CloseHandler>()

  constructor(
    private readonly path: string,
    private readonly parseMessage: MessageParser<T>,
    private readonly webSocketFactory: WebSocketFactory = (url) => new WebSocket(url),
  ) {}

  connect(): void {
    this.explicitlyDisconnected = false
    this.open()
  }

  disconnect(): void {
    this.explicitlyDisconnected = true
    clearTimeout(this.reconnectTimer)
    this.socket?.close()
    this.state.value = 'closed'
  }

  subscribe(handler: MessageHandler<T>): () => void {
    this.subscribers.add(handler)
    return () => this.subscribers.delete(handler)
  }

  /** Calls `handler` with the close code each time the socket closes; it may `disconnect()` to stop the reconnect. */
  onClose(handler: CloseHandler): () => void {
    this.closeHandlers.add(handler)
    return () => this.closeHandlers.delete(handler)
  }

  /** Writes `payload` as JSON; false when there is no open socket, in which case nothing is queued. */
  send(payload: unknown): boolean {
    if (this.socket?.readyState !== SOCKET_OPEN) return false
    this.socket.send(JSON.stringify(payload))
    return true
  }

  private open(): void {
    this.state.value = this.attempt === 0 ? 'connecting' : 'reconnecting'
    const socket = this.webSocketFactory(resolveWsUrl(this.path))
    this.socket = socket
    socket.onopen = () => {
      this.attempt = 0
      this.state.value = 'open'
    }
    socket.onmessage = (event: MessageEvent) => this.handleRawMessage(event.data)
    socket.onclose = (event?: CloseEvent) => {
      this.scheduleReconnect()
      for (const handler of this.closeHandlers) handler(event?.code ?? ABNORMAL_CLOSE)
    }
    // The close event that follows carries the failure; nothing further to do here.
    socket.onerror = () => undefined
  }

  private handleRawMessage(raw: unknown): void {
    let parsed: unknown
    try {
      parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    } catch {
      return
    }
    const message = this.parseMessage(parsed)
    if (message === undefined) return
    this.lastMessage.value = message
    for (const subscriber of this.subscribers) subscriber(message)
  }

  private scheduleReconnect(): void {
    this.socket = undefined
    if (this.explicitlyDisconnected) {
      this.state.value = 'closed'
      return
    }
    this.state.value = 'reconnecting'
    const delay = backoffDelayMs(this.attempt)
    this.attempt += 1
    this.reconnectTimer = setTimeout(() => this.open(), delay)
  }
}

function hasComponentHealth(data: Record<string, unknown>, key: string): boolean {
  const component = data[key]
  return (
    typeof component === 'object' &&
    component !== null &&
    typeof (component as Record<string, unknown>).status === 'string'
  )
}

const HEALTH_COMPONENTS = ['postgres', 'opensearch', 'cape', 'guest'] as const

/**
 * Validates the shape of a `/ws/system` push at runtime: the generated `HealthMessage` type
 * (`src/api/types.gen.ts`) only checks types at compile time and vanishes once the JSON is
 * parsed, so a malformed payload must be caught here instead of trusted with `as`.
 */
export function parseHealthMessage(raw: unknown): HealthMessage | undefined {
  if (typeof raw !== 'object' || raw === null) return undefined
  const { type, ts, data } = raw as Record<string, unknown>
  if (type !== 'health' || typeof ts !== 'string') return undefined
  if (typeof data !== 'object' || data === null) return undefined
  const healthData = data as Record<string, unknown>
  if (!HEALTH_COMPONENTS.every((key) => hasComponentHealth(healthData, key))) return undefined
  return raw as HealthMessage
}

export function createSystemHealthClient(
  webSocketFactory?: WebSocketFactory,
): ReconnectingWebSocketClient<HealthMessage> {
  return new ReconnectingWebSocketClient('/ws/system', parseHealthMessage, webSocketFactory)
}
