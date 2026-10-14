import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { EventPage } from '@/api'
import { eventList, eventPage } from './events-fixtures'

const eventsSearchMock = vi.fn()
vi.mock('@/api', () => ({ eventsSearch: (...args: unknown[]) => eventsSearchMock(...args) }))

const { useEventsStore, EVENTS_PAGE_SIZE, EVENTS_DEBOUNCE_MS } = await import('@/stores/events')
const { useQueryStateStore } = await import('@/stores/query-state')

let events: ReturnType<typeof useEventsStore>
let query: ReturnType<typeof useQueryStateStore>

function ok(page: EventPage) {
  return { data: page, error: undefined, response: { status: 200 } }
}

function failed(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
  return { data: undefined, error: { error: { code, message, details } }, response: { status } }
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

function lastRequest() {
  return eventsSearchMock.mock.lastCall![0] as { path: { analysis_id: number }; body: Record<string, unknown> }
}

async function startOn(analysisId = 7) {
  query.bindTo(analysisId)
  events.activate()
  await settle()
}

async function settle() {
  await vi.advanceTimersByTimeAsync(0)
}

async function afterDebounce() {
  await vi.advanceTimersByTimeAsync(EVENTS_DEBOUNCE_MS + 1)
}

beforeEach(() => {
  vi.useFakeTimers()
  eventsSearchMock.mockReset()
  eventsSearchMock.mockResolvedValue(ok(eventPage(eventList(3))))
  setActivePinia(createPinia())
  query = useQueryStateStore()
  events = useEventsStore()
})

afterEach(() => vi.useRealTimers())

describe('the first page', () => {
  it('asks for the first page of the analysis with the oldest first', async () => {
    await startOn(7)
    expect(eventsSearchMock).toHaveBeenCalledTimes(1)
    expect(lastRequest().path).toEqual({ analysis_id: 7 })
    expect(lastRequest().body).toEqual({ sort: '@timestamp', size: EVENTS_PAGE_SIZE })
    expect(EVENTS_PAGE_SIZE).toBe(100)
  })

  it('sends the filter of the shared query state with it', async () => {
    query.bindTo(7)
    query.setText('lane:file')
    query.addChip({ field: 'process.name', value: 'cmd.exe', negate: true })
    query.setPids([2476])
    query.setTimeRange({ from: '2026-10-13T15:39:34Z', to: null })
    events.activate()
    await settle()
    expect(lastRequest().body).toEqual({
      sort: '@timestamp',
      size: EVENTS_PAGE_SIZE,
      query: 'lane:file',
      filters: [{ field: 'process.name', value: 'cmd.exe', negate: true }],
      pids: [2476],
      time_range: { from: '2026-10-13T15:39:34Z' },
    })
  })

  it('does not ask while no analysis is bound', async () => {
    events.activate()
    await settle()
    expect(eventsSearchMock).not.toHaveBeenCalled()
  })

  it('holds the events, the exact total and whether more follow', async () => {
    eventsSearchMock.mockResolvedValue(ok(eventPage(eventList(100), { total: 4321, next_cursor: 'c1' })))
    await startOn()
    expect(events.events).toHaveLength(100)
    expect(events.total).toBe(4321)
    expect(events.hasMore).toBe(true)
    expect(events.loading).toBe(false)
  })

  it('is loading until the page arrives', async () => {
    const pending = deferred<unknown>()
    eventsSearchMock.mockReturnValue(pending.promise)
    await startOn()
    expect(events.loading).toBe(true)
    pending.resolve(ok(eventPage(eventList(2))))
    await settle()
    expect(events.loading).toBe(false)
  })

  it('knows when it has loaded once, so an empty answer is told from not having asked', async () => {
    expect(events.loaded).toBe(false)
    await startOn()
    expect(events.loaded).toBe(true)
  })
})

describe('more pages', () => {
  beforeEach(() => {
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(100), { total: 250, next_cursor: 'c1' })))
  })

  it('follows the cursor and appends the next page', async () => {
    await startOn()
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(100, 101), { total: 250, next_cursor: 'c2' })))
    await events.loadMore()
    expect(lastRequest().body).toMatchObject({ search_after: 'c1', size: EVENTS_PAGE_SIZE, sort: '@timestamp' })
    expect(events.events).toHaveLength(200)
    expect(events.events[100]!.id).toBe('e101')
    expect(events.hasMore).toBe(true)
  })

  it('stops when the last page has no cursor', async () => {
    await startOn()
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(50, 101), { total: 150, next_cursor: null })))
    await events.loadMore()
    expect(events.hasMore).toBe(false)
    await events.loadMore()
    expect(eventsSearchMock).toHaveBeenCalledTimes(2)
  })

  it('does not ask for a second page while one is on its way', async () => {
    await startOn()
    const pending = deferred<unknown>()
    eventsSearchMock.mockReturnValueOnce(pending.promise)
    const first = events.loadMore()
    expect(events.loadingMore).toBe(true)
    await events.loadMore()
    expect(eventsSearchMock).toHaveBeenCalledTimes(2)
    pending.resolve(ok(eventPage(eventList(10, 101), { next_cursor: null })))
    await first
    expect(events.loadingMore).toBe(false)
  })

  it('keeps the rows it has when a further page fails, and offers to try again', async () => {
    await startOn()
    eventsSearchMock.mockResolvedValueOnce(failed(504, 'search_timeout', 'the search took too long'))
    await events.loadMore()
    expect(events.events).toHaveLength(100)
    expect(events.error).toBeUndefined()
    expect(events.loadMoreError).toBe('the search took too long')
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(5, 101), { next_cursor: null })))
    await events.loadMore()
    expect(events.loadMoreError).toBeUndefined()
    expect(events.events).toHaveLength(105)
  })

  it('drops a further page that arrives after the filter changed', async () => {
    await startOn()
    const pending = deferred<unknown>()
    eventsSearchMock.mockReturnValueOnce(pending.promise)
    const more = events.loadMore()
    eventsSearchMock.mockResolvedValue(ok(eventPage(eventList(2), { total: 2 })))
    query.setText('lane:file')
    await afterDebounce()
    pending.resolve(ok(eventPage(eventList(100, 101), { next_cursor: 'c2' })))
    await more
    expect(events.events).toHaveLength(2)
    expect(events.loadingMore).toBe(false)
  })
})

describe('sorting', () => {
  it('starts oldest first and toggles to newest first and back, asking again each time', async () => {
    await startOn()
    expect(events.sort).toBe('@timestamp')
    events.toggleSort()
    await afterDebounce()
    expect(events.sort).toBe('-@timestamp')
    expect(lastRequest().body).toMatchObject({ sort: '-@timestamp' })
    events.toggleSort()
    await afterDebounce()
    expect(lastRequest().body).toMatchObject({ sort: '@timestamp' })
    expect(eventsSearchMock).toHaveBeenCalledTimes(3)
  })

  it('starts the list over rather than reusing a cursor of the other sort', async () => {
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(100), { next_cursor: 'c1' })))
    await startOn()
    events.toggleSort()
    await afterDebounce()
    expect(lastRequest().body.search_after).toBeUndefined()
  })
})

describe('refetching', () => {
  it('asks again, once, when the filter changes in a burst', async () => {
    await startOn()
    query.setText('a')
    query.setText('ab')
    query.addChip({ field: 'lane', value: 'file', negate: false })
    await afterDebounce()
    expect(eventsSearchMock).toHaveBeenCalledTimes(2)
    expect(lastRequest().body).toMatchObject({ query: 'ab', filters: [{ field: 'lane', value: 'file', negate: false }] })
  })

  it.each([
    ['the text', () => query.setText('x')],
    ['a chip', () => query.addChip({ field: 'lane', value: 'file', negate: false })],
    ['a pid', () => query.togglePid(4)],
    ['the time range', () => query.setTimeRange({ from: '2026-10-13T15:39:34Z', to: null })],
  ])('asks again when %s changes', async (_name, change) => {
    await startOn()
    change()
    await afterDebounce()
    expect(eventsSearchMock).toHaveBeenCalledTimes(2)
  })

  it('does not ask again when the open event changes, which is no part of the filter', async () => {
    await startOn()
    query.openEvent('e2')
    await afterDebounce()
    expect(eventsSearchMock).toHaveBeenCalledTimes(1)
  })

  it('drops the answer to an older filter that arrives after the answer to a newer one', async () => {
    await startOn()
    const slow = deferred<unknown>()
    eventsSearchMock.mockReturnValueOnce(slow.promise)
    query.setText('slow')
    await afterDebounce()
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(1, 50), { total: 1 })))
    query.setText('fast')
    await afterDebounce()
    expect(events.events.map((event) => event.id)).toEqual(['e50'])
    slow.resolve(ok(eventPage(eventList(9), { total: 9 })))
    await settle()
    expect(events.events.map((event) => event.id)).toEqual(['e50'])
    expect(events.total).toBe(1)
  })

  it('drops the answer to an older sort that arrives late', async () => {
    await startOn()
    const slow = deferred<unknown>()
    eventsSearchMock.mockReturnValueOnce(slow.promise)
    events.toggleSort()
    await afterDebounce()
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(1, 50), { total: 1 })))
    events.toggleSort()
    await afterDebounce()
    slow.resolve(ok(eventPage(eventList(9), { total: 9 })))
    await settle()
    expect(events.events.map((event) => event.id)).toEqual(['e50'])
  })

  it('keeps the old rows, marked loading, while the new filter is on its way', async () => {
    await startOn()
    eventsSearchMock.mockReturnValueOnce(new Promise(() => undefined))
    query.setText('x')
    await afterDebounce()
    expect(events.loading).toBe(true)
    expect(events.events).toHaveLength(3)
  })

  it('starts over for another analysis and forgets the old rows at once', async () => {
    await startOn(7)
    eventsSearchMock.mockReturnValueOnce(new Promise(() => undefined))
    query.bindTo(8)
    await vi.advanceTimersByTimeAsync(0)
    expect(events.events).toEqual([])
    await afterDebounce()
    expect(lastRequest().path).toEqual({ analysis_id: 8 })
  })
})

describe('being on screen', () => {
  it('does not ask while the tab is not shown', async () => {
    await startOn()
    events.deactivate()
    query.setText('x')
    await afterDebounce()
    expect(eventsSearchMock).toHaveBeenCalledTimes(1)
  })

  it('asks again, at once, on showing the tab if the filter changed meanwhile', async () => {
    await startOn()
    events.deactivate()
    query.setText('x')
    events.activate()
    await settle()
    expect(eventsSearchMock).toHaveBeenCalledTimes(2)
  })

  it('keeps what it has on showing the tab again with nothing changed', async () => {
    await startOn()
    events.deactivate()
    events.activate()
    await settle()
    expect(eventsSearchMock).toHaveBeenCalledTimes(1)
  })
})

describe('failures', () => {
  it('says so, with the first problem of a query the API refused', async () => {
    eventsSearchMock.mockResolvedValue(
      failed(422, 'invalid_query', 'The query is not valid', {
        errors: [{ start: 0, end: 4, message: "unknown field 'prcess'", suggestion: 'process', filter_index: null }],
      }),
    )
    await startOn()
    expect(events.error).toEqual({ message: "unknown field 'prcess'", status: 422 })
    expect(events.events).toEqual([])
    expect(events.loading).toBe(false)
  })

  it('names a chip that did not compile by its position', async () => {
    eventsSearchMock.mockResolvedValue(
      failed(422, 'invalid_query', 'The query is not valid', {
        errors: [{ start: 0, end: 4, message: "unknown field 'nope'", suggestion: null, filter_index: 1 }],
      }),
    )
    await startOn()
    expect(events.error?.message).toBe("filter 2: unknown field 'nope'")
  })

  it('uses the envelope message for a timeout, and retry asks again', async () => {
    eventsSearchMock.mockResolvedValueOnce(failed(504, 'search_timeout', 'the search took too long'))
    await startOn()
    expect(events.error).toEqual({ message: 'the search took too long', status: 504 })
    await events.retry()
    expect(events.error).toBeUndefined()
    expect(events.events).toHaveLength(3)
  })

  it('has a generic message for a failure without an envelope', async () => {
    eventsSearchMock.mockResolvedValue({ data: undefined, error: undefined, response: undefined })
    await startOn()
    expect(events.error?.message).toMatch(/something went wrong/i)
  })

  it('clears the error when the filter changes and the next answer is good', async () => {
    eventsSearchMock.mockResolvedValueOnce(failed(502, 'search_failed', 'search failed'))
    await startOn()
    query.setText('x')
    await afterDebounce()
    expect(events.error).toBeUndefined()
  })
})

describe('moving through the list', () => {
  beforeEach(async () => {
    eventsSearchMock.mockResolvedValue(ok(eventPage(eventList(3), { total: 5, next_cursor: 'c1' })))
    await startOn()
  })

  it('finds the previous and next event', async () => {
    expect(await events.neighbour('e2', -1)).toBe('e1')
    expect(await events.neighbour('e2', 1)).toBe('e3')
  })

  it('has no previous event before the first', async () => {
    expect(events.hasNeighbour('e1', -1)).toBe(false)
    expect(await events.neighbour('e1', -1)).toBeUndefined()
  })

  it('loads the next page when asked for the event after the last one loaded', async () => {
    expect(events.hasNeighbour('e3', 1)).toBe(true)
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(2, 4), { total: 5, next_cursor: null })))
    expect(await events.neighbour('e3', 1)).toBe('e4')
  })

  it('has no next event after the very last', async () => {
    eventsSearchMock.mockResolvedValueOnce(ok(eventPage(eventList(2, 4), { total: 5, next_cursor: null })))
    await events.loadMore()
    expect(events.hasNeighbour('e5', 1)).toBe(false)
    expect(await events.neighbour('e5', 1)).toBeUndefined()
  })

  it('has no neighbours for an event that is not in the list', async () => {
    expect(events.hasNeighbour('elsewhere', 1)).toBe(false)
    expect(events.hasNeighbour('elsewhere', -1)).toBe(false)
  })
})
