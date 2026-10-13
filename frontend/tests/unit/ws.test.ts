import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSystemHealthClient, parseHealthMessage } from '@/services/ws'
import type { HealthMessage } from '@/api'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: ((event?: { code: number }) => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  readyState = 0
  sent: string[] = []

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this)
  }

  open(): void {
    this.readyState = 1
    this.onopen?.()
  }

  send(data: string): void {
    this.sent.push(data)
  }

  close(code?: number): void {
    if (this.closed) return
    this.closed = true
    this.readyState = 3
    this.onclose?.(code === undefined ? undefined : { code })
  }

  serverPush(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }

  serverPushRaw(raw: string): void {
    this.onmessage?.({ data: raw })
  }
}

function fakeFactory(): (url: string) => WebSocket {
  return (url: string) => new FakeWebSocket(url) as unknown as WebSocket
}

const HEALTH_MESSAGE: HealthMessage = {
  type: 'health',
  ts: '2026-10-12T12:00:00Z',
  data: {
    postgres: { status: 'ok', message: null },
    opensearch: { status: 'ok', message: null },
    cape: { status: 'down', message: 'not set up yet' },
    guest: { status: 'down', message: 'not set up yet' },
  },
}

beforeEach(() => {
  FakeWebSocket.instances = []
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('parseHealthMessage', () => {
  it('accepts a well-formed health message', () => {
    expect(parseHealthMessage(HEALTH_MESSAGE)).toEqual(HEALTH_MESSAGE)
  })

  it('rejects a message missing "data"', () => {
    expect(parseHealthMessage({ type: 'health', ts: HEALTH_MESSAGE.ts })).toBeUndefined()
  })

  it('rejects a message missing "type"', () => {
    expect(parseHealthMessage({ ts: HEALTH_MESSAGE.ts, data: HEALTH_MESSAGE.data })).toBeUndefined()
  })

  it('rejects a non-object payload', () => {
    expect(parseHealthMessage('not an object')).toBeUndefined()
  })
})

describe('createSystemHealthClient', () => {
  it('delivers a parsed health message to subscribers', () => {
    const client = createSystemHealthClient(fakeFactory())
    const received: HealthMessage[] = []
    client.subscribe((message) => received.push(message))

    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()
    FakeWebSocket.instances[0]?.serverPush(HEALTH_MESSAGE)

    expect(received).toEqual([HEALTH_MESSAGE])
    expect(client.lastMessage.value).toEqual(HEALTH_MESSAGE)
  })

  it('does not deliver or throw on a malformed message', () => {
    const client = createSystemHealthClient(fakeFactory())
    const received: HealthMessage[] = []
    client.subscribe((message) => received.push(message))

    client.connect()
    expect(() => FakeWebSocket.instances[0]?.serverPush({ type: 'health' })).not.toThrow()
    expect(() => FakeWebSocket.instances[0]?.serverPushRaw('{not json')).not.toThrow()

    expect(received).toEqual([])
  })

  it('starts in "connecting" and moves to "open" on connect', () => {
    const client = createSystemHealthClient(fakeFactory())
    client.connect()
    expect(client.state.value).toBe('connecting')

    FakeWebSocket.instances[0]?.onopen?.()
    expect(client.state.value).toBe('open')
  })

  it('transitions through "reconnecting" and opens a new socket after the backoff delay', () => {
    const client = createSystemHealthClient(fakeFactory())
    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()

    FakeWebSocket.instances[0]?.close()
    expect(client.state.value).toBe('reconnecting')
    expect(FakeWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(5000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('increases backoff across consecutive failures and caps it', () => {
    const client = createSystemHealthClient(fakeFactory())
    const setTimeoutSpy = vi.spyOn(globalThis, 'setTimeout')

    client.connect()
    for (let round = 0; round < 8; round += 1) {
      FakeWebSocket.instances[round]?.close()
      const delay = Number(setTimeoutSpy.mock.calls.at(-1)?.[1])
      vi.advanceTimersByTime(delay)
    }

    const delays = setTimeoutSpy.mock.calls.map((call) => Number(call[1]))
    expect(delays[0]).toBeLessThan(delays[1]!)
    expect(delays[1]).toBeLessThan(delays[2]!)
    for (const delay of delays) {
      expect(delay).toBeLessThanOrEqual(30000)
    }
  })

  it('stops reconnecting once disconnect() is called', () => {
    const client = createSystemHealthClient(fakeFactory())
    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()

    client.disconnect()
    expect(client.state.value).toBe('closed')

    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})

describe('ReconnectingWebSocketClient sending', () => {
  it('writes a JSON message to an open socket', () => {
    const client = createSystemHealthClient(fakeFactory())
    client.connect()
    FakeWebSocket.instances[0]!.open()

    expect(client.send({ type: 'ping' })).toBe(true)
    expect(FakeWebSocket.instances[0]!.sent).toEqual(['{"type":"ping"}'])
  })

  it('sends nothing, and says so, while the socket is not open', () => {
    const client = createSystemHealthClient(fakeFactory())
    expect(client.send({ type: 'ping' })).toBe(false)

    client.connect()
    expect(client.send({ type: 'ping' })).toBe(false)
    expect(FakeWebSocket.instances[0]!.sent).toEqual([])
  })
})

describe('ReconnectingWebSocketClient close handlers', () => {
  it('tells a handler the close code and still reconnects', () => {
    const client = createSystemHealthClient(fakeFactory())
    const codes: number[] = []
    client.onClose((code) => codes.push(code))
    client.connect()

    FakeWebSocket.instances[0]!.close(1012)
    expect(codes).toEqual([1012])

    vi.advanceTimersByTime(5000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('stops reconnecting when a handler disconnects the client', () => {
    const client = createSystemHealthClient(fakeFactory())
    client.onClose(() => client.disconnect())
    client.connect()

    FakeWebSocket.instances[0]!.close(4404)
    expect(client.state.value).toBe('closed')

    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('stops calling a handler that unsubscribed', () => {
    const client = createSystemHealthClient(fakeFactory())
    const codes: number[] = []
    const unsubscribe = client.onClose((code) => codes.push(code))
    unsubscribe()
    client.connect()

    FakeWebSocket.instances[0]!.close(1000)
    expect(codes).toEqual([])
  })
})
