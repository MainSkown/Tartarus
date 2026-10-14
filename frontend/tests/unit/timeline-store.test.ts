import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Histogram, HistogramBucket, HistogramDetection } from '@/api'
import { NO_EVENTS } from '@/services/range-override'
import { spanToQueryRange } from '@/services/timeline-brush'
import { spanLength, type Span } from '@/services/timeline-scale'
import { eventList, eventPage } from './events-fixtures'

const histogramMock = vi.fn()
const searchMock = vi.fn()
vi.mock('@/api', () => ({
  eventsHistogram: (...args: unknown[]) => histogramMock(...args),
  eventsSearch: (...args: unknown[]) => searchMock(...args),
}))

const { useTimelineStore, TIMELINE_DEBOUNCE_MS, TIMELINE_PAGE_SIZE, DETECTION_LIMIT } = await import('@/stores/timeline')
const { useQueryStateStore } = await import('@/stores/query-state')
const { QUIET_ON_EVENT_FAILURES } = await import('@/stores/events')

const FIRST = Date.parse('2026-10-13T15:39:50.000Z')
const LAST = Date.parse('2026-10-13T15:40:40.000Z')
const FULL: Span = { start: FIRST - 500, end: LAST + 500 }
const iso = (ms: number): string => new Date(ms).toISOString()

let timeline: ReturnType<typeof useTimelineStore>
let query: ReturnType<typeof useQueryStateStore>

interface HistogramBody {
  query?: string
  filters?: unknown[]
  pids?: number[]
  time_range?: { from?: string; to?: string }
  interval?: number | 'auto'
}

const ok = <T>(data: T) => ({ data, error: undefined, response: { status: 200 } })
const failed = (status: number, code: string, message: string) => ({ data: undefined, error: { error: { code, message, details: {} } }, response: { status } })

function histogram(overrides: Partial<Histogram> = {}): Histogram {
  return { interval_ms: 500, from: iso(FIRST), to: iso(LAST), total: 3, buckets: [], detections: [], ...overrides }
}

function bucket(time: number, total: number): HistogramBucket {
  return { time: iso(time), total, by_lane: { file: total } }
}

function detection(id: string, time = FIRST + 1000): HistogramDetection {
  return { id, time: iso(time), name: id, severity: 'high', ruleset: 'cape' }
}

/** What the next data histograms say about the events in whatever range is asked for. */
let viewTotal = 3
let viewDetections: HistogramDetection[] = []
let viewBuckets: HistogramBucket[] = []

function histogramCalls(): { path: { analysis_id: number }; body: HistogramBody }[] {
  return histogramMock.mock.calls.map(([call]) => call)
}

function searchCalls(): { path: { analysis_id: number }; body: HistogramBody & { sort: string; size: number; search_after?: string } }[] {
  return searchMock.mock.calls.map(([call]) => call)
}

function dataHistogramCalls() {
  return histogramCalls().filter((call) => call.body.time_range !== undefined)
}

async function settle() {
  await vi.advanceTimersByTimeAsync(0)
}

async function afterDebounce() {
  await vi.advanceTimersByTimeAsync(TIMELINE_DEBOUNCE_MS + 1)
}

async function open(analysisId = 7) {
  query.bindTo(analysisId)
  timeline.activate()
  await settle()
}

function deferred<T>() {
  let resolve: (value: T) => void = () => undefined
  const promise = new Promise<T>((done) => (resolve = done))
  return { promise, resolve }
}

beforeEach(() => {
  vi.useFakeTimers()
  histogramMock.mockReset()
  searchMock.mockReset()
  viewTotal = 3
  viewDetections = []
  viewBuckets = []
  histogramMock.mockImplementation(async ({ body }: { body: HistogramBody }) =>
    ok(body.time_range ? histogram({ total: viewTotal, detections: viewDetections, buckets: viewBuckets }) : histogram({ total: 500 })),
  )
  searchMock.mockImplementation(async () => ok(eventPage(eventList(3))))
  setActivePinia(createPinia())
  query = useQueryStateStore()
  timeline = useTimelineStore()
})

afterEach(() => vi.useRealTimers())

describe('opening', () => {
  it('asks for the bounds of the whole analysis with no filter, then for the whole range', async () => {
    await open(7)
    const calls = histogramCalls()
    expect(calls[0]).toEqual({ path: { analysis_id: 7 }, body: { interval: 'auto' }, meta: expect.anything() })
    expect(calls[1]!.body).toEqual({ interval: 'auto', time_range: spanToQueryRangeForApi(FULL) })
  })

  it('shows the whole range, padded, as the view', async () => {
    await open()
    expect(timeline.full).toEqual(FULL)
    expect(timeline.view).toEqual(FULL)
    expect(timeline.preset).toBe('fit')
    expect(timeline.status).toBe('ready')
  })

  it('does not ask while no analysis is bound', async () => {
    timeline.activate()
    await settle()
    expect(histogramMock).not.toHaveBeenCalled()
    expect(timeline.status).toBe('loading')
  })

  it('is loading until the first answers arrive', async () => {
    const pending = deferred<unknown>()
    histogramMock.mockReturnValueOnce(pending.promise)
    await open()
    expect(timeline.status).toBe('loading')
    pending.resolve(ok(histogram({ total: 500 })))
    await settle()
    expect(timeline.status).toBe('ready')
  })
})

function spanToQueryRangeForApi(span: Span) {
  const range = spanToQueryRange(span)
  return { from: range.from, to: range.to }
}

describe('an analysis without events', () => {
  it('is empty, and asks for nothing more', async () => {
    histogramMock.mockResolvedValue(ok(histogram({ from: null, to: null, total: 0 })))
    await open()
    expect(timeline.status).toBe('empty')
    expect(timeline.full).toBeNull()
    expect(histogramMock).toHaveBeenCalledTimes(1)
    expect(searchMock).not.toHaveBeenCalled()
  })

  it('draws a single event on a span of one second around it', async () => {
    histogramMock.mockImplementation(async ({ body }: { body: HistogramBody }) =>
      ok(histogram({ from: iso(FIRST), to: iso(FIRST), total: body.time_range ? 1 : 1 })),
    )
    await open()
    expect(spanLength(timeline.full!)).toBe(1000)
    expect(timeline.status).toBe('ready')
  })
})

describe('individual events', () => {
  it('are loaded for a range holding no more than 2000, sorted by time with the largest page', async () => {
    await open()
    expect(timeline.data?.mode).toBe('events')
    expect(searchCalls()).toHaveLength(1)
    expect(searchCalls()[0]!.body).toMatchObject({ sort: '@timestamp', size: TIMELINE_PAGE_SIZE, time_range: spanToQueryRangeForApi(FULL) })
    expect(TIMELINE_PAGE_SIZE).toBe(500)
    expect(timeline.data).toMatchObject({ mode: 'events', events: expect.arrayContaining([expect.objectContaining({ id: 'e1' })]) })
    expect(timeline.total).toBe(3)
  })

  it('are paged by the cursor until the range is complete', async () => {
    viewTotal = 1200
    searchMock.mockImplementation(async ({ body }: { body: { search_after?: string } }) => {
      const page = body.search_after ? Number(body.search_after) : 0
      const sizes = [500, 500, 200]
      const events = eventList(sizes[page]!, page * 500 + 1)
      return ok(eventPage(events, { total: 1200, next_cursor: page < 2 ? String(page + 1) : null }))
    })
    await open()
    expect(searchCalls().map((call) => call.body.search_after)).toEqual([undefined, '1', '2'])
    expect(timeline.data?.mode === 'events' && timeline.data.events).toHaveLength(1200)
  })

  it('stop at 2000 even if the cursor goes on', async () => {
    viewTotal = 2000
    searchMock.mockImplementation(async ({ body }: { body: { search_after?: string } }) => {
      const page = body.search_after ? Number(body.search_after) : 0
      return ok(eventPage(eventList(500, page * 500 + 1), { total: 2600, next_cursor: String(page + 1) }))
    })
    await open()
    expect(searchCalls()).toHaveLength(4)
    expect(timeline.data?.mode === 'events' && timeline.data.events).toHaveLength(2000)
  })

  it('come with the detections of the histogram', async () => {
    viewDetections = [detection('d1')]
    await open()
    expect(timeline.data?.detections.map((d) => d.id)).toEqual(['d1'])
  })
})

describe('aggregation', () => {
  it('uses the buckets of the histogram, and no search, above 2000 events', async () => {
    viewTotal = 2001
    viewBuckets = [bucket(FIRST, 1000), bucket(FIRST + 500, 1001)]
    viewDetections = [detection('d1')]
    await open()
    expect(searchMock).not.toHaveBeenCalled()
    expect(timeline.data).toEqual({ mode: 'buckets', buckets: viewBuckets, intervalMs: 500, detections: viewDetections })
    expect(timeline.total).toBe(2001)
  })

  it('switches to events when zooming in leaves 2000 or fewer', async () => {
    viewTotal = 5000
    await open()
    expect(timeline.data?.mode).toBe('buckets')
    viewTotal = 40
    timeline.zoomAt(FIRST + 10_000, 0.2)
    await afterDebounce()
    expect(timeline.data?.mode).toBe('events')
  })
})

describe('the shared filter', () => {
  it('goes with the histogram and the search, the time-range chip left out and the view range in its place', async () => {
    query.bindTo(7)
    query.setText('lane:file')
    query.addChip({ field: 'process.name', value: 'cmd.exe', negate: true })
    query.setPids([2476])
    query.setTimeRange({ from: iso(FIRST + 5000), to: iso(FIRST + 6000) })
    timeline.activate()
    await settle()
    const expected = { query: 'lane:file', filters: [{ field: 'process.name', value: 'cmd.exe', negate: true }], pids: [2476], time_range: spanToQueryRangeForApi(FULL) }
    expect(dataHistogramCalls()[0]!.body).toEqual({ ...expected, interval: 'auto' })
    expect(searchCalls()[0]!.body).toMatchObject(expected)
    expect(histogramCalls()[0]!.body).toEqual({ interval: 'auto' })
  })

  it('does not ask again when only the time-range chip changes: it is drawn as a band, not applied', async () => {
    await open()
    histogramMock.mockClear()
    searchMock.mockClear()
    query.setTimeRange({ from: iso(FIRST + 5000), to: iso(FIRST + 9000) })
    await afterDebounce()
    expect(histogramMock).not.toHaveBeenCalled()
    expect(searchMock).not.toHaveBeenCalled()
    expect(timeline.chipSpan).toEqual({ start: FIRST + 5000, end: FIRST + 9000 })
  })

  it('asks again, once, for the same range when the query changes, without asking for the bounds again', async () => {
    await open()
    histogramMock.mockClear()
    searchMock.mockClear()
    query.setText('lane:file')
    query.addChip({ field: 'process.name', value: 'cmd.exe', negate: false })
    await afterDebounce()
    expect(histogramCalls()).toHaveLength(1)
    expect(histogramCalls()[0]!.body.query).toBe('lane:file')
    expect(searchCalls()).toHaveLength(1)
  })

  it('does not ask while the tab is not shown, and asks on showing it if the filter changed meanwhile', async () => {
    await open()
    timeline.deactivate()
    histogramMock.mockClear()
    query.setText('lane:file')
    await afterDebounce()
    expect(histogramMock).not.toHaveBeenCalled()
    timeline.activate()
    await settle()
    expect(histogramCalls().map((call) => call.body.query)).toEqual(['lane:file'])
  })

  it('does not ask a second time for a range that is already on its way', async () => {
    const slow = deferred<unknown>()
    query.bindTo(7)
    histogramMock.mockImplementationOnce(async () => ok(histogram({ total: 500 }))).mockReturnValueOnce(slow.promise)
    timeline.activate()
    await settle()
    timeline.deactivate()
    timeline.activate()
    await settle()
    expect(dataHistogramCalls()).toHaveLength(1)
    slow.resolve(ok(histogram({ total: 3 })))
    await settle()
    expect(timeline.status).toBe('ready')
  })

  it('keeps what it has on showing the tab again with nothing changed', async () => {
    await open()
    timeline.deactivate()
    histogramMock.mockClear()
    timeline.activate()
    await settle()
    expect(histogramMock).not.toHaveBeenCalled()
    expect(timeline.status).toBe('ready')
  })
})

describe('moving the view', () => {
  it('changes the view at once but asks for the new range only after the pause', async () => {
    viewTotal = 5000
    await open()
    histogramMock.mockClear()
    timeline.zoomAt(FIRST + 20_000, 0.5)
    expect(spanLength(timeline.view!)).toBeCloseTo(spanLength(FULL) / 2, 6)
    expect(timeline.committedView).toEqual(FULL)
    expect(histogramMock).not.toHaveBeenCalled()
    await afterDebounce()
    expect(timeline.committedView).toEqual(timeline.view)
    expect(histogramMock).toHaveBeenCalledTimes(1)
  })

  it('asks once for a burst of wheel steps', async () => {
    viewTotal = 5000
    await open()
    histogramMock.mockClear()
    for (let step = 0; step < 6; step++) {
      timeline.zoomAt(FIRST + 20_000, 0.8)
      await vi.advanceTimersByTimeAsync(20)
    }
    await afterDebounce()
    expect(histogramMock).toHaveBeenCalledTimes(1)
  })

  it('keeps the view inside the full range and at least 10 ms long', async () => {
    await open()
    timeline.setView({ start: 0, end: 10 })
    expect(timeline.view!.start).toBe(FULL.start)
    expect(spanLength(timeline.view!)).toBe(10)
    timeline.setView({ start: 0, end: 1e15 })
    expect(timeline.view).toEqual(FULL)
  })

  it('draws the events it already has when zooming into them, without asking again', async () => {
    await open()
    histogramMock.mockClear()
    searchMock.mockClear()
    const first = timeline.data?.mode === 'events' ? timeline.data.events : []
    timeline.zoomAt(FIRST + 1500, 0.5)
    await afterDebounce()
    expect(histogramMock).not.toHaveBeenCalled()
    expect(searchMock).not.toHaveBeenCalled()
    expect(timeline.data?.mode).toBe('events')
    expect(timeline.data?.mode === 'events' && timeline.data.events.length).toBeLessThanOrEqual(first.length)
  })

  it('narrows the events and detections it keeps to the new range', async () => {
    searchMock.mockResolvedValue(
      ok(
        eventPage([
          ...eventList(1).map((e) => ({ ...e, id: 'early', time: iso(FIRST + 1000) })),
          ...eventList(1).map((e) => ({ ...e, id: 'late', time: iso(FIRST + 40_000) })),
        ]),
      ),
    )
    viewDetections = [detection('dEarly', FIRST + 1000), detection('dLate', FIRST + 40_000)]
    await open()
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    await afterDebounce()
    expect(timeline.data?.mode === 'events' && timeline.data.events.map((e) => e.id)).toEqual(['early'])
    expect(timeline.data?.detections.map((d) => d.id)).toEqual(['dEarly'])
  })

  it('does not ask again for a range it already loaded', async () => {
    viewTotal = 5000
    await open()
    viewTotal = 40
    const range = { start: FIRST + 20_000, end: FIRST + 30_000 }
    timeline.setView(range)
    await afterDebounce()
    histogramMock.mockClear()
    timeline.fit()
    await afterDebounce()
    timeline.setView(range)
    await afterDebounce()
    expect(histogramMock).not.toHaveBeenCalled()
  })

  it('asks again when zooming out beyond the events it has', async () => {
    viewTotal = 5000
    await open()
    viewTotal = 40
    timeline.setView({ start: FIRST + 20_000, end: FIRST + 30_000 })
    await afterDebounce()
    histogramMock.mockClear()
    timeline.setView({ start: FIRST + 10_000, end: FIRST + 40_000 })
    await afterDebounce()
    expect(histogramMock).toHaveBeenCalledTimes(1)
  })

  it('asks again for another range from buckets, which cannot be narrowed', async () => {
    viewTotal = 5000
    await open()
    histogramMock.mockClear()
    timeline.zoomAt(FIRST + 10_000, 0.5)
    await afterDebounce()
    expect(histogramMock).toHaveBeenCalledTimes(1)
  })

  it('asks again rather than narrow detections that the histogram cut off at its limit', async () => {
    viewDetections = Array.from({ length: DETECTION_LIMIT }, (_, index) => detection(`d${index}`, FIRST + index))
    await open()
    histogramMock.mockClear()
    timeline.zoomAt(FIRST + 1000, 0.5)
    await afterDebounce()
    expect(histogramMock).toHaveBeenCalledTimes(1)
  })

  it('drops the answer to a range the view has left', async () => {
    viewTotal = 5000
    await open()
    const slow = deferred<unknown>()
    histogramMock.mockReturnValueOnce(slow.promise)
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    await afterDebounce()
    histogramMock.mockImplementation(async () => ok(histogram({ total: 3, detections: [detection('fresh')] })))
    timeline.setView({ start: FIRST + 20_000, end: FIRST + 30_000 })
    await afterDebounce()
    slow.resolve(ok(histogram({ total: 3, detections: [detection('stale')] })))
    await settle()
    expect(timeline.data?.detections.map((d) => d.id)).toEqual(['fresh'])
  })

  it('is loading while the new range is on its way, with the old data still there', async () => {
    viewTotal = 5000
    await open()
    const slow = deferred<unknown>()
    histogramMock.mockReturnValueOnce(slow.promise)
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    await afterDebounce()
    expect(timeline.loading).toBe(true)
    expect(timeline.status).toBe('ready')
    expect(timeline.data).toBeDefined()
    slow.resolve(ok(histogram({ total: 3 })))
    await settle()
    expect(timeline.loading).toBe(false)
  })
})

describe('zoom presets and panning', () => {
  it('apply a preset centred on the current centre or on a focus time', async () => {
    await open()
    timeline.applyPreset('10s')
    expect(spanLength(timeline.view!)).toBe(10_000)
    expect((timeline.view!.start + timeline.view!.end) / 2).toBeCloseTo((FULL.start + FULL.end) / 2, 6)
    expect(timeline.preset).toBe('10s')
    timeline.applyPreset('1s', FIRST + 5000)
    expect(timeline.view).toEqual({ start: FIRST + 4500, end: FIRST + 5500 })
    timeline.applyPreset('fit')
    expect(timeline.view).toEqual(FULL)
  })

  it('pan by pixels and by a fraction of the view, and jump to either end', async () => {
    await open()
    timeline.applyPreset('10s')
    const before = timeline.view!
    timeline.panByPixels(100, 1000)
    expect(timeline.view!.start).toBeCloseTo(before.start - 1000, 6)
    timeline.panByFraction(0.5)
    expect(timeline.view!.start).toBeCloseTo(before.start - 1000 + 5000, 6)
    timeline.jumpTo('start')
    expect(timeline.view!.start).toBe(FULL.start)
    timeline.jumpTo('end')
    expect(timeline.view!.end).toBe(FULL.end)
  })

  it('reveal centres a time that is outside the view and leaves a time inside it alone', async () => {
    await open()
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    const inside = timeline.view
    timeline.reveal(FIRST + 5000)
    expect(timeline.view).toEqual(inside)
    timeline.reveal(FIRST + 30_000)
    expect((timeline.view!.start + timeline.view!.end) / 2).toBe(FIRST + 30_000)
    expect(spanLength(timeline.view!)).toBe(10_000)
  })

  it('do nothing before the full range is known', () => {
    timeline.applyPreset('10s')
    timeline.panByFraction(0.5)
    timeline.reveal(5)
    expect(timeline.view).toBeNull()
  })
})

describe('the range for the events table', () => {
  it('is no restriction at the fit view', async () => {
    await open()
    expect(timeline.tableRange).toBeNull()
  })

  it('follows the committed view, not the one still being dragged', async () => {
    await open()
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    expect(timeline.tableRange).toBeNull()
    await afterDebounce()
    expect(timeline.tableRange).toEqual({ from: iso(FIRST), to: iso(FIRST + 10_000) })
  })

  it('is cut down to the time-range chip', async () => {
    await open()
    query.setTimeRange({ from: iso(FIRST + 5000), to: iso(FIRST + 50_000) })
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    await afterDebounce()
    expect(timeline.tableRange).toEqual({ from: iso(FIRST + 5000), to: iso(FIRST + 10_000) })
  })

  it('has no event in it when the view is away from the chip', async () => {
    await open()
    query.setTimeRange({ from: iso(FIRST + 30_000), to: iso(FIRST + 40_000) })
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    await afterDebounce()
    expect(timeline.tableRange).toBe(NO_EVENTS)
  })
})

describe('failures', () => {
  it('says so when the bounds fail, and retry asks for them again', async () => {
    histogramMock.mockResolvedValueOnce(failed(504, 'search_timeout', 'the search took too long'))
    await open()
    expect(timeline.status).toBe('error')
    expect(timeline.error?.message).toBe('the search took too long')
    await timeline.retry()
    await settle()
    expect(timeline.status).toBe('ready')
    expect(timeline.error).toBeUndefined()
  })

  it('says so when the data of a range fails, keeping the view, and retry asks for that range again', async () => {
    viewTotal = 5000
    await open()
    histogramMock.mockResolvedValueOnce(failed(502, 'search_failed', 'search failed'))
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    await afterDebounce()
    expect(timeline.status).toBe('error')
    expect(timeline.view).toEqual({ start: FIRST, end: FIRST + 10_000 })
    await timeline.retry()
    await settle()
    expect(timeline.status).toBe('ready')
    expect(dataHistogramCalls().at(-1)!.body.time_range).toEqual(spanToQueryRangeForApi({ start: FIRST, end: FIRST + 10_000 }))
  })

  it('says so when a page of events fails', async () => {
    searchMock.mockResolvedValueOnce(failed(504, 'search_timeout', 'the search took too long'))
    await open()
    expect(timeline.status).toBe('error')
  })

  it('asks with the failure kinds the tab shows itself marked quiet, so no toast says it twice', async () => {
    await open()
    expect(histogramCalls()[0]!).toMatchObject({ meta: QUIET_ON_EVENT_FAILURES })
    expect(searchCalls()[0]!).toMatchObject({ meta: QUIET_ON_EVENT_FAILURES })
  })
})

describe('another analysis', () => {
  it('starts over: forgets everything and asks for the bounds of the new one', async () => {
    await open(7)
    timeline.applyPreset('10s')
    histogramMock.mockClear()
    const pending = deferred<unknown>()
    histogramMock.mockReturnValueOnce(pending.promise)
    query.bindTo(8)
    await settle()
    expect(timeline.full).toBeNull()
    expect(timeline.view).toBeNull()
    expect(timeline.data).toBeUndefined()
    expect(timeline.status).toBe('loading')
    expect(histogramCalls()[0]).toMatchObject({ path: { analysis_id: 8 }, body: { interval: 'auto' } })
    pending.resolve(ok(histogram({ total: 500 })))
    await settle()
    expect(timeline.status).toBe('ready')
  })
})
