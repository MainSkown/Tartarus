import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSystemHealthClient, parseHealthMessage } from '@/services/ws'
import type { HealthMessage } from '@/api'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  closed = false

  constructor(readonly url: string) {
    FakeWebSocket.instances.push(this)
  }

  close(): void {
    if (this.closed) return
    this.closed = true
    this.onclose?.()
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
