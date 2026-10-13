import { describe, expect, it } from 'vitest'
import {
  NO_FILTER,
  appendBounded,
  describeLiveError,
  applyProcessDelta,
  eventsPerMinute,
  matchesSubscription,
  processRoots,
  processesEmptyMessage,
  streamEmptyMessage,
  subscriptionOf,
  treeRows,
} from '@/services/live-state'
import type { LiveProcessNode } from '@/services/live-messages'
import { liveEvent, liveProcess } from './live-fixtures'

function processMap(...nodes: LiveProcessNode[]): Map<number, LiveProcessNode> {
  return new Map(nodes.map((node) => [node.pid, node]))
}

describe('subscriptionOf', () => {
  it('leaves every list out when nothing is chosen, because an empty list would match nothing', () => {
    expect(subscriptionOf(NO_FILTER)).toEqual({ include_api: false })
  })

  it('sends the chosen lanes and pids', () => {
    expect(subscriptionOf({ lanes: ['file', 'network'], pids: [4, 8], includeApi: false })).toEqual({
      lanes: ['file', 'network'],
      pids: [4, 8],
      include_api: false,
    })
  })

  it('adds the api lane to a lane choice when API calls are shown, since the server filters lanes first', () => {
    expect(subscriptionOf({ lanes: ['file'], pids: [], includeApi: true })).toEqual({ lanes: ['file', 'api'], include_api: true })
  })

  it('does not name the api lane when no lane is chosen', () => {
    expect(subscriptionOf({ lanes: [], pids: [], includeApi: true })).toEqual({ include_api: true })
  })
})

describe('matchesSubscription', () => {
  const api = liveEvent({ lane: 'api' })
  const file = liveEvent({ lane: 'file', pid: 12 })

  it('hides the api lane unless asked for', () => {
    expect(matchesSubscription(api, { include_api: false })).toBe(false)
    expect(matchesSubscription(api, { include_api: true })).toBe(true)
    expect(matchesSubscription(file, { include_api: false })).toBe(true)
  })

  it('lets the api lane through when a lane choice names it', () => {
    expect(matchesSubscription(api, { lanes: ['api'] })).toBe(true)
  })

  it('keeps only the chosen lanes', () => {
    expect(matchesSubscription(file, { lanes: ['network'] })).toBe(false)
    expect(matchesSubscription(file, { lanes: ['file'] })).toBe(true)
  })

  it('keeps only the chosen pids, and drops an event with no process', () => {
    expect(matchesSubscription(file, { pids: [12] })).toBe(true)
    expect(matchesSubscription(file, { pids: [13] })).toBe(false)
    expect(matchesSubscription({ ...file, process: undefined }, { pids: [12] })).toBe(false)
  })
})

describe('applyProcessDelta', () => {
  it('adds a process without touching the map it was given', () => {
    const before = processMap()
    const after = applyProcessDelta(before, { op: 'add', node: liveProcess(4) })
    expect(before.size).toBe(0)
    expect([...after.keys()]).toEqual([4])
  })

  it('replaces the node on update and on end, which carry the whole node', () => {
    let map = applyProcessDelta(processMap(), { op: 'add', node: liveProcess(4, { name: null }) })
    map = applyProcessDelta(map, { op: 'update', node: liveProcess(4, { name: 'a.exe' }) })
    expect(map.get(4)?.name).toBe('a.exe')
    map = applyProcessDelta(map, { op: 'end', node: liveProcess(4, { name: 'a.exe', end: '2026-10-13T15:39:52Z' }) })
    expect(map.get(4)?.end).toBe('2026-10-13T15:39:52Z')
  })

  it('learns a process from an update or end it never saw added', () => {
    expect(applyProcessDelta(processMap(), { op: 'end', node: liveProcess(9) }).has(9)).toBe(true)
  })
})

describe('processRoots and treeRows', () => {
  it('nests children under their parent, ordered by start then pid', () => {
    const map = processMap(
      liveProcess(1, { start: '2026-10-13T15:39:50Z' }),
      liveProcess(3, { ppid: 1, start: '2026-10-13T15:39:52Z' }),
      liveProcess(2, { ppid: 1, start: '2026-10-13T15:39:51Z' }),
      liveProcess(4, { ppid: 2, start: '2026-10-13T15:39:53Z' }),
    )
    const rows = treeRows(processRoots(map))
    expect(rows.map((row) => [row.process.pid, row.depth])).toEqual([
      [1, 0],
      [2, 1],
      [4, 2],
      [3, 1],
    ])
  })

  it('makes a root of a process whose parent is unknown or itself', () => {
    const map = processMap(liveProcess(5, { ppid: 999 }), liveProcess(6, { ppid: 6 }))
    expect(processRoots(map).map((root) => root.process.pid)).toEqual([5, 6])
  })

  it('does not loop on a parent cycle, and shows what is reachable', () => {
    const map = processMap(liveProcess(1, { ppid: 2 }), liveProcess(2, { ppid: 1 }), liveProcess(7))
    expect(treeRows(processRoots(map)).map((row) => row.process.pid)).toEqual([7])
  })

  it('puts a process with no start time after the ones that have one', () => {
    const map = processMap(liveProcess(1, { start: null }), liveProcess(2, { start: '2026-10-13T15:39:50Z' }))
    expect(processRoots(map).map((root) => root.process.pid)).toEqual([2, 1])
  })
})

describe('appendBounded', () => {
  const events = (...ids: string[]) => ids.map((id) => liveEvent({ id }))
  const idsOf = (list: ReturnType<typeof events>) => list.map((event) => event.event.id)

  it('appends within the limit and trims nothing', () => {
    const result = appendBounded(events('a'), events('b', 'c'), 5)
    expect(idsOf(result.events)).toEqual(['a', 'b', 'c'])
    expect(result.trimmed).toBe(0)
  })

  it('keeps the newest events and counts the ones it let go', () => {
    const result = appendBounded(events('a', 'b', 'c'), events('d', 'e'), 4)
    expect(idsOf(result.events)).toEqual(['b', 'c', 'd', 'e'])
    expect(result.trimmed).toBe(1)
  })

  it('keeps only the newest of a batch larger than the limit', () => {
    const result = appendBounded([], events('a', 'b', 'c', 'd'), 2)
    expect(idsOf(result.events)).toEqual(['c', 'd'])
    expect(result.trimmed).toBe(2)
  })

  it('does not modify the buffer it was given', () => {
    const buffer = events('a')
    appendBounded(buffer, events('b'), 5)
    expect(idsOf(buffer)).toEqual(['a'])
  })
})

describe('eventsPerMinute', () => {
  it('is zero with no events in the last half minute', () => {
    expect(eventsPerMinute([], 100_000)).toBe(0)
    expect(eventsPerMinute([{ at: 10_000, count: 50 }], 100_000)).toBe(0)
  })

  it('divides what arrived in the window by the span it covers', () => {
    const samples = [
      { at: 70_000, count: 100 },
      { at: 85_000, count: 100 },
    ]
    expect(eventsPerMinute(samples, 100_000)).toBe(400)
  })

  it('counts a fresh stream over at least five seconds, so one early batch does not read as a flood', () => {
    expect(eventsPerMinute([{ at: 99_000, count: 10 }], 100_000)).toBe(120)
  })
})

describe('streamEmptyMessage', () => {
  const base = { status: 'running', processCount: 0, queuePosition: null, filtered: false } as const

  it('says the analysis is queued, with its place', () => {
    expect(streamEmptyMessage({ ...base, status: 'queued', queuePosition: 2 })).toBe('queued, position 2')
    expect(streamEmptyMessage({ ...base, status: 'queued' })).toBe('queued, waiting for the guest')
  })

  it('says the guest is starting until the first process appears', () => {
    expect(streamEmptyMessage({ ...base, status: 'starting' })).toBe('starting the guest...')
    expect(streamEmptyMessage({ ...base, status: 'running' })).toBe('starting the guest...')
  })

  it('says it is connected once a process exists but no event came', () => {
    expect(streamEmptyMessage({ ...base, processCount: 1 })).toBe('connected, no events yet')
  })

  it('says the filter hides everything when one is set', () => {
    expect(streamEmptyMessage({ ...base, processCount: 1, filtered: true })).toBe('no events match the filter')
  })

  it('says the run is over for a finished analysis', () => {
    expect(streamEmptyMessage({ ...base, status: 'done', processCount: 1 })).toBe('the run is over, no events were streamed')
  })
})

describe('processesEmptyMessage', () => {
  it('follows the run: queued, starting, then over', () => {
    expect(processesEmptyMessage({ status: 'queued', queuePosition: 1 })).toBe('queued, position 1')
    expect(processesEmptyMessage({ status: 'running', queuePosition: null })).toBe('starting the guest...')
    expect(processesEmptyMessage({ status: 'failed', queuePosition: null })).toBe('no process was seen before the run ended')
  })
})

describe('describeLiveError', () => {
  it('explains a live indexing failure and says the final report is not affected', () => {
    expect(describeLiveError({ code: 'live_index_failed', message: 'bulk rejected' })).toBe(
      'live indexing failed (bulk rejected); the final report is not affected',
    )
  })

  it('explains an unreadable log record', () => {
    expect(describeLiveError({ code: 'log_format', message: 'unknown message type 9' })).toBe(
      'a log record could not be read (unknown message type 9); the final report is not affected',
    )
  })

  it('shows any other error with its code and message', () => {
    expect(describeLiveError({ code: 'bad_message', message: 'not JSON' })).toBe('bad_message: not JSON')
  })
})
