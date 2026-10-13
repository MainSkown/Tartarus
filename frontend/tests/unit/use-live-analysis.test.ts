import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, type EffectScope } from 'vue'
import { MAX_BUFFERED_EVENTS, useLiveAnalysis } from '@/composables/use-live-analysis'
import { FakeWebSocket, fakeSocketFactory } from './fake-websocket'
import { liveEvent, liveProcess } from './live-fixtures'

const STATUS = { status: 'running', phase: 'live', elapsed_s: 10, remaining_s: 170 }
const FINISHED = { status: 'done', phase: 'live', elapsed_s: 180, remaining_s: 0 }

let scope: EffectScope

function start(analysisId = 42) {
  scope = effectScope()
  const live = scope.run(() => useLiveAnalysis(analysisId, { webSocketFactory: fakeSocketFactory() }))!
  return live
}

function connect(live = start()) {
  FakeWebSocket.latest.serverOpens()
  return live
}

const socket = () => FakeWebSocket.latest
const ids = (live: ReturnType<typeof start>) => live.events.value.map((event) => event.event.id)
const sendEvents = (events: ReturnType<typeof liveEvent>[], dropped = 0) => socket().serverSends('events', { events, dropped })

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-13T15:40:00Z'))
  FakeWebSocket.reset()
})

afterEach(() => {
  scope.stop()
  vi.useRealTimers()
})

describe('useLiveAnalysis connection', () => {
  it('connects to the live socket of the analysis', () => {
    start(45)
    expect(socket().url).toContain('/ws/analyses/45/live')
  })

  it('reports the connection state of the socket', () => {
    const live = start()
    expect(live.connection.value).toBe('connecting')
    socket().serverOpens()
    expect(live.connection.value).toBe('open')
  })

  it('closes the socket when its scope ends, and does not reconnect', () => {
    const live = connect()
    scope.stop()
    expect(live.connection.value).toBe('closed')
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })

  it('reconnects after an abnormal close and says so meanwhile', () => {
    const live = connect()
    socket().serverCloses(1006)
    expect(live.connection.value).toBe('reconnecting')
    vi.advanceTimersByTime(5_000)
    expect(FakeWebSocket.instances).toHaveLength(2)
  })

  it('stops for good after a normal close, which the server sends once the analysis has ended', () => {
    const live = connect()
    socket().serverCloses(1000)
    expect(live.connection.value).toBe('closed')
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(live.notFound.value).toBe(false)
  })

  it('reports an unknown analysis on close 4404 and stops', () => {
    const live = connect()
    socket().serverCloses(4404)
    expect(live.notFound.value).toBe(true)
    vi.advanceTimersByTime(60_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})

describe('useLiveAnalysis status', () => {
  it('keeps the latest status with the moment it arrived', () => {
    const live = connect()
    socket().serverSends('status', STATUS)
    expect(live.status.value).toEqual({ ...STATUS, receivedAt: Date.now() })
    expect(live.finished.value).toBe(false)
  })

  it('is finished once a terminal status arrives', () => {
    const live = connect()
    socket().serverSends('status', FINISHED)
    expect(live.finished.value).toBe(true)
  })

  it('moves the phase to final when the server says so', () => {
    const live = connect()
    socket().serverSends('status', FINISHED)
    expect(live.phase.value).toBe('live')
    socket().serverSends('phase', { phase: 'final' })
    expect(live.phase.value).toBe('final')
  })

  it('ignores a malformed message without throwing', () => {
    const live = connect()
    expect(() => socket().onmessage?.({ data: '{"type":"status","ts":"x","data":{"status":"bogus"}}' })).not.toThrow()
    expect(live.status.value).toBeUndefined()
  })
})

describe('useLiveAnalysis process tree', () => {
  it('grows from add, update and end deltas', () => {
    const live = connect()
    socket().serverSends('process', { op: 'add', node: liveProcess(1, { name: null }) })
    socket().serverSends('process', { op: 'add', node: liveProcess(2, { ppid: 1 }) })
    socket().serverSends('process', { op: 'update', node: liveProcess(1, { name: 'benign.exe' }) })
    socket().serverSends('process', { op: 'end', node: liveProcess(2, { ppid: 1, end: '2026-10-13T15:39:52Z' }) })

    expect(live.processCount.value).toBe(2)
    expect(live.roots.value).toHaveLength(1)
    expect(live.roots.value[0]!.process.name).toBe('benign.exe')
    expect(live.roots.value[0]!.children[0]!.process.end).toBe('2026-10-13T15:39:52Z')
  })
})

describe('useLiveAnalysis event buffer', () => {
  it('shows events in arrival order and counts them', () => {
    const live = connect()
    sendEvents([liveEvent({ id: 'a' }), liveEvent({ id: 'b' })])
    sendEvents([liveEvent({ id: 'c' })])
    expect(ids(live)).toEqual(['a', 'b', 'c'])
    expect(live.received.value).toBe(3)
  })

  it('keeps only the newest events past the bound and counts the trimmed ones', () => {
    const live = connect()
    const batch = (from: number, count: number) =>
      Array.from({ length: count }, (_, index) => liveEvent({ id: `e${from + index}` }))
    sendEvents(batch(0, MAX_BUFFERED_EVENTS))
    sendEvents(batch(MAX_BUFFERED_EVENTS, 3))
    expect(live.events.value).toHaveLength(MAX_BUFFERED_EVENTS)
    expect(ids(live)[0]).toBe('e3')
    expect(ids(live).at(-1)).toBe(`e${MAX_BUFFERED_EVENTS + 2}`)
    expect(live.trimmed.value).toBe(3)
  })

  it('adds up the events the server says it skipped', () => {
    const live = connect()
    sendEvents([liveEvent({ id: 'a' })], 120)
    sendEvents([liveEvent({ id: 'b' })], 30)
    expect(live.dropped.value).toBe(150)
  })

  it('keeps the latest counts', () => {
    const live = connect()
    const counts = { by_lane: { file: 2 }, by_severity: { info: 2 }, total: 2 }
    socket().serverSends('counts', counts)
    expect(live.counts.value).toEqual(counts)
  })

  it('estimates events per minute from the recent batches', () => {
    const live = connect()
    sendEvents(Array.from({ length: 10 }, (_, index) => liveEvent({ id: `e${index}` })))
    vi.advanceTimersByTime(5_000)
    socket().serverSends('status', STATUS)
    expect(live.eventsPerMinute.value).toBe(120)
  })

  it('empties the stream and its banners on clear', () => {
    const live = connect()
    sendEvents([liveEvent({ id: 'a' })], 5)
    live.clear()
    expect(live.events.value).toEqual([])
    expect(live.dropped.value).toBe(0)
    expect(live.trimmed.value).toBe(0)
    sendEvents([liveEvent({ id: 'b' })])
    expect(ids(live)).toEqual(['b'])
  })
})

describe('useLiveAnalysis pause', () => {
  it('freezes what is displayed while the buffer keeps filling, and counts the backlog', () => {
    const live = connect()
    sendEvents([liveEvent({ id: 'a' })])
    live.pause()
    sendEvents([liveEvent({ id: 'b' }), liveEvent({ id: 'c' })])
    expect(live.paused.value).toBe(true)
    expect(ids(live)).toEqual(['a'])
    expect(live.backlog.value).toBe(2)
  })

  it('shows everything that arrived on resume and resets the backlog', () => {
    const live = connect()
    live.pause()
    sendEvents([liveEvent({ id: 'a' })])
    live.resume()
    expect(live.paused.value).toBe(false)
    expect(ids(live)).toEqual(['a'])
    expect(live.backlog.value).toBe(0)
  })

  it('starts the backlog from zero on every pause', () => {
    const live = connect()
    live.pause()
    sendEvents([liveEvent({ id: 'a' })])
    live.resume()
    live.pause()
    expect(live.backlog.value).toBe(0)
  })

  it('shows an empty stream when cleared while paused', () => {
    const live = connect()
    sendEvents([liveEvent({ id: 'a' })])
    live.pause()
    live.clear()
    expect(live.events.value).toEqual([])
  })
})

describe('useLiveAnalysis filter', () => {
  it('sends the filter as a subscribe message', () => {
    const live = connect()
    live.setFilter({ pids: [9708], lanes: ['file'] })
    expect(socket().subscribes.at(-1)).toEqual({
      type: 'subscribe',
      data: { include_api: false, lanes: ['file'], pids: [9708] },
    })
    expect(live.filter.value).toEqual({ lanes: ['file'], pids: [9708], includeApi: false })
  })

  it('changes only the parts it is given', () => {
    const live = connect()
    live.setFilter({ pids: [4] })
    live.setFilter({ includeApi: true })
    expect(live.filter.value).toEqual({ lanes: [], pids: [4], includeApi: true })
  })

  it('sends the default filter when the socket opens, and the current one again after a reconnect', () => {
    const live = start()
    live.setFilter({ lanes: ['network'] })
    expect(socket().subscribes).toEqual([])
    socket().serverOpens()
    expect(socket().subscribes).toEqual([{ type: 'subscribe', data: { include_api: false, lanes: ['network'] } }])

    socket().serverCloses(1006)
    vi.advanceTimersByTime(5_000)
    socket().serverOpens()
    expect(socket().subscribes).toEqual([{ type: 'subscribe', data: { include_api: false, lanes: ['network'] } }])
  })

  it('re-filters the events already buffered, so choosing a process shows its past events at once', () => {
    const live = connect()
    sendEvents([liveEvent({ id: 'a', pid: 1 }), liveEvent({ id: 'b', pid: 2 }), liveEvent({ id: 'c', pid: 1 })])
    live.setFilter({ pids: [1] })
    expect(ids(live)).toEqual(['a', 'c'])
    live.setFilter({ pids: [] })
    expect(ids(live)).toEqual(['a', 'b', 'c'])
  })

  it('hides buffered api events again when API calls are switched off', () => {
    const live = connect()
    live.setFilter({ includeApi: true })
    sendEvents([liveEvent({ id: 'a', lane: 'api' }), liveEvent({ id: 'b', lane: 'file' })])
    expect(ids(live)).toEqual(['a', 'b'])
    live.setFilter({ includeApi: false })
    expect(ids(live)).toEqual(['b'])
  })
})

describe('useLiveAnalysis errors', () => {
  it('collects the server errors, one per code', () => {
    const live = connect()
    socket().serverSends('error', { code: 'live_index_failed', message: 'first' })
    socket().serverSends('error', { code: 'log_format', message: 'unknown record' })
    socket().serverSends('error', { code: 'live_index_failed', message: 'second' })
    expect(live.errors.value).toEqual([
      { code: 'log_format', message: 'unknown record' },
      { code: 'live_index_failed', message: 'second' },
    ])
  })
})
