import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSystemClient, parseHealthMessage, parseJobMessage, parseQueueMessage } from '@/services/ws'
import type { HealthMessage, JobMessage, QueueMessage } from '@/api'

const QUEUE_MESSAGE: QueueMessage = {
  type: 'queue',
  ts: '2026-10-21T10:00:00Z',
  data: {
    running: [{ id: 42, filename: 'invoice.exe', guest: 'lab1', status: 'running', started_at: '2026-10-21T09:59:00Z', elapsed_s: 60 }],
    queued_count: 1,
    queued: [{ id: 43, filename: 'macro.doc', guest: 'lab1', position: 1 }],
  },
}

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

const JOB_MESSAGE: JobMessage = {
  type: 'job',
  job: {
    id: 9,
    type: 'export_report',
    analysis_id: 193,
    status: 'running',
    step: 'Rendering the PDF',
    progress: 45,
    result: null,
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

describe('parseJobMessage', () => {
  it('accepts a well-formed job message', () => {
    expect(parseJobMessage(JOB_MESSAGE)).toEqual(JOB_MESSAGE)
  })

  it('accepts a job whose analysis and result are null', () => {
    const job = { ...JOB_MESSAGE.job, analysis_id: null, result: null }
    expect(parseJobMessage({ type: 'job', job })).toEqual({ type: 'job', job })
  })

  it.each([
    ['a missing job', { type: 'job' }],
    ['another type', { type: 'health', job: JOB_MESSAGE.job }],
    ['a non-numeric id', { type: 'job', job: { ...JOB_MESSAGE.job, id: '9' } }],
    ['an unknown status', { type: 'job', job: { ...JOB_MESSAGE.job, status: 'vanished' } }],
    ['a missing progress', { type: 'job', job: { ...JOB_MESSAGE.job, progress: undefined } }],
    ['a non-object payload', 'job'],
  ])('rejects %s', (_label, raw) => {
    expect(parseJobMessage(raw)).toBeUndefined()
  })
})

describe('createSystemClient', () => {
  it('delivers a parsed job message next to the health messages, on the one socket', () => {
    const client = createSystemClient(fakeFactory())
    const received: unknown[] = []
    client.subscribe((message) => received.push(message))

    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()
    FakeWebSocket.instances[0]?.serverPush(HEALTH_MESSAGE)
    FakeWebSocket.instances[0]?.serverPush(JOB_MESSAGE)

    expect(received).toEqual([HEALTH_MESSAGE, JOB_MESSAGE])
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('delivers a parsed health message to subscribers', () => {
    const client = createSystemClient(fakeFactory())
    const received: unknown[] = []
    client.subscribe((message) => received.push(message))

    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()
    FakeWebSocket.instances[0]?.serverPush(HEALTH_MESSAGE)

    expect(received).toEqual([HEALTH_MESSAGE])
    expect(client.lastMessage.value).toEqual(HEALTH_MESSAGE)
  })

  it('does not deliver or throw on a malformed message', () => {
    const client = createSystemClient(fakeFactory())
    const received: unknown[] = []
    client.subscribe((message) => received.push(message))

    client.connect()
    expect(() => FakeWebSocket.instances[0]?.serverPush({ type: 'health' })).not.toThrow()
    expect(() => FakeWebSocket.instances[0]?.serverPushRaw('{not json')).not.toThrow()

    expect(received).toEqual([])
  })

  it('starts in "connecting" and moves to "open" on connect', () => {
    const client = createSystemClient(fakeFactory())
    client.connect()
    expect(client.state.value).toBe('connecting')

    FakeWebSocket.instances[0]?.onopen?.()
    expect(client.state.value).toBe('open')
  })

  it('transitions through "reconnecting" and opens a new socket after the backoff delay', () => {
    const client = createSystemClient(fakeFactory())
    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()

    FakeWebSocket.instances[0]?.close()
    expect(client.state.value).toBe('reconnecting')
    expect(FakeWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(5000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('increases backoff across consecutive failures and caps it', () => {
    const client = createSystemClient(fakeFactory())
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
    const client = createSystemClient(fakeFactory())
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
    const client = createSystemClient(fakeFactory())
    client.connect()
    FakeWebSocket.instances[0]!.open()

    expect(client.send({ type: 'ping' })).toBe(true)
    expect(FakeWebSocket.instances[0]!.sent).toEqual(['{"type":"ping"}'])
  })

  it('sends nothing, and says so, while the socket is not open', () => {
    const client = createSystemClient(fakeFactory())
    expect(client.send({ type: 'ping' })).toBe(false)

    client.connect()
    expect(client.send({ type: 'ping' })).toBe(false)
    expect(FakeWebSocket.instances[0]!.sent).toEqual([])
  })
})

describe('ReconnectingWebSocketClient close handlers', () => {
  it('tells a handler the close code and still reconnects', () => {
    const client = createSystemClient(fakeFactory())
    const codes: number[] = []
    client.onClose((code) => codes.push(code))
    client.connect()

    FakeWebSocket.instances[0]!.close(1012)
    expect(codes).toEqual([1012])

    vi.advanceTimersByTime(5000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('stops reconnecting when a handler disconnects the client', () => {
    const client = createSystemClient(fakeFactory())
    client.onClose(() => client.disconnect())
    client.connect()

    FakeWebSocket.instances[0]!.close(4404)
    expect(client.state.value).toBe('closed')

    vi.advanceTimersByTime(60000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('stops calling a handler that unsubscribed', () => {
    const client = createSystemClient(fakeFactory())
    const codes: number[] = []
    const unsubscribe = client.onClose((code) => codes.push(code))
    unsubscribe()
    client.connect()

    FakeWebSocket.instances[0]!.close(1000)
    expect(codes).toEqual([])
  })
})

describe('parseQueueMessage', () => {
  it('accepts a well-formed queue message', () => {
    expect(parseQueueMessage(QUEUE_MESSAGE)).toEqual(QUEUE_MESSAGE)
  })

  it('accepts an empty queue', () => {
    const empty = { type: 'queue', ts: QUEUE_MESSAGE.ts, data: { running: [], queued_count: 0, queued: [] } }
    expect(parseQueueMessage(empty)).toEqual(empty)
  })

  it('rejects a queue message whose lists are missing', () => {
    expect(parseQueueMessage({ type: 'queue', ts: QUEUE_MESSAGE.ts, data: { queued_count: 0 } })).toBeUndefined()
  })

  it('rejects a queue message with a non-numeric count', () => {
    expect(parseQueueMessage({ ...QUEUE_MESSAGE, data: { ...QUEUE_MESSAGE.data, queued_count: '1' } })).toBeUndefined()
  })
})

describe('createSystemClient queue pushes', () => {
  it('delivers a parsed queue message on the same socket', () => {
    const client = createSystemClient(fakeFactory())
    const received: unknown[] = []
    client.subscribe((message) => received.push(message))

    client.connect()
    FakeWebSocket.instances[0]?.onopen?.()
    FakeWebSocket.instances[0]?.serverPush(QUEUE_MESSAGE)

    expect(received).toEqual([QUEUE_MESSAGE])
  })
})
