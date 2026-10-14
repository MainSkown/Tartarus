import { defineStore } from 'pinia'
import { computed, ref, shallowRef, watch } from 'vue'
import { eventsHistogram, eventsSearch } from '@/api'
import type { Event } from '@/api'
import { debounced } from '@/services/debounced'
import { createRequestSequence } from '@/services/request-sequence'
import { searchFailure, type SearchFailure } from '@/services/search-failure'
import { queryRangeToSpan, spanToQueryRange } from '@/services/timeline-brush'
import { AGGREGATION_THRESHOLD, sourceFor, type SceneData } from '@/services/timeline-layout'
import {
  activePreset,
  applyPreset as presetView,
  centreOn,
  clampView,
  isWithin,
  jumpTo as jumpedView,
  paddedFullSpan,
  panByFraction as pannedByFraction,
  panByPixels as pannedByPixels,
  zoomAround,
  type Span,
  type ZoomPreset,
} from '@/services/timeline-scale'
import { tableRangeFor } from '@/services/timeline-table-range'
import { QUIET_ON_EVENT_FAILURES } from '@/stores/events'
import { apiTimeRange, useQueryStateStore, type SearchFilter } from '@/stores/query-state'

export const TIMELINE_DEBOUNCE_MS = 120
export const TIMELINE_PAGE_SIZE = 500
/** The histogram returns at most this many detections, so a list this long may be missing some and cannot be narrowed locally. */
export const DETECTION_LIMIT = 500
const CACHE_LIMIT = 24

type DataFilter = Omit<SearchFilter, 'time_range'>
type Status = 'loading' | 'ready' | 'empty' | 'error'
type Outcome<T> = { done: T } | { failure: SearchFailure } | 'stale'

interface Loaded {
  identity: string
  analysisId: number
  filterKey: string
  span: Span
  data: SceneData
  total: number
}

/**
 * What the Timeline tab draws, loaded from the histogram and the search endpoints.
 *
 * Ranges: the canvas always spans the whole analysis (`full`, from an unfiltered histogram, so it
 * does not move when a filter thins the lanes) and the visible `view` stays inside it. The query,
 * chips and pids filter what is drawn; the time-range chip does not, it is drawn as a band over the
 * full context, and only the events table below is cut down to view and chip (`tableRange`).
 *
 * Data: the histogram of the committed view (the view after a pause of `TIMELINE_DEBOUNCE_MS`)
 * says how many events it holds. Up to the aggregation threshold the events themselves are loaded,
 * paged; above it the buckets are drawn. Answers are cached by analysis, filter and range; a view
 * inside a range whose events are already loaded is narrowed locally; a stale answer is dropped.
 */
export const useTimelineStore = defineStore('timeline', () => {
  const query = useQueryStateStore()
  const full = ref<Span | null>(null)
  const view = ref<Span | null>(null)
  const committedView = ref<Span | null>(null)
  const loaded = shallowRef<Loaded>()
  const boundsLoaded = ref(false)
  const loading = ref(false)
  const error = ref<SearchFailure>()
  const active = ref(false)

  const boundsRequests = createRequestSequence()
  const dataRequests = createRequestSequence()
  const cache = new Map<string, Loaded>()
  let inFlight: string | undefined
  let boundsRequestedFor: number | undefined

  const dataFilter = computed<DataFilter>(() => {
    const filter: SearchFilter = { ...query.searchFilter }
    delete filter.time_range
    return filter
  })
  const filterKey = computed(() => JSON.stringify(dataFilter.value))

  const data = computed(() => loaded.value?.data)
  const total = computed(() => loaded.value?.total ?? 0)
  const preset = computed(() => (view.value && full.value ? activePreset(view.value, full.value) : null))
  const chipSpan = computed(() => (query.timeRange && full.value ? queryRangeToSpan(query.timeRange, full.value) : null))
  const tableRange = computed(() => tableRangeFor(committedView.value, full.value, query.timeRange))
  const status = computed<Status>(() => {
    if (error.value) return 'error'
    if (boundsLoaded.value && full.value === null) return 'empty'
    return loaded.value === undefined ? 'loading' : 'ready'
  })

  function identityOf(analysisId: number, span: Span): string {
    const { from, to } = spanToQueryRange(span)
    return JSON.stringify([analysisId, filterKey.value, from, to])
  }

  async function fetchEvents(analysisId: number, span: Span, request: number): Promise<Outcome<Event[]>> {
    const events: Event[] = []
    let cursor: string | undefined
    do {
      const { data: page, error: failure, response } = await eventsSearch({
        path: { analysis_id: analysisId },
        body: {
          ...dataFilter.value,
          time_range: apiTimeRange(spanToQueryRange(span)),
          sort: '@timestamp',
          size: TIMELINE_PAGE_SIZE,
          ...(cursor && { search_after: cursor }),
        },
        meta: QUIET_ON_EVENT_FAILURES,
      })
      if (!dataRequests.isCurrent(request)) return 'stale'
      if (!page) return { failure: searchFailure(failure, response) }
      events.push(...page.events)
      cursor = page.next_cursor ?? undefined
    } while (cursor !== undefined && events.length < AGGREGATION_THRESHOLD)
    return { done: events }
  }

  async function fetchRange(analysisId: number, span: Span, request: number): Promise<Outcome<{ data: SceneData; total: number }>> {
    const { data: histogram, error: failure, response } = await eventsHistogram({
      path: { analysis_id: analysisId },
      body: { ...dataFilter.value, time_range: apiTimeRange(spanToQueryRange(span)), interval: 'auto' },
      meta: QUIET_ON_EVENT_FAILURES,
    })
    if (!dataRequests.isCurrent(request)) return 'stale'
    if (!histogram) return { failure: searchFailure(failure, response) }
    const { detections } = histogram
    if (sourceFor(histogram.total) === 'buckets') {
      return { done: { data: { mode: 'buckets', buckets: histogram.buckets, intervalMs: histogram.interval_ms, detections }, total: histogram.total } }
    }
    const events = await fetchEvents(analysisId, span, request)
    if (typeof events === 'string' || 'failure' in events) return events
    return { done: { data: { mode: 'events', events: events.done, detections }, total: histogram.total } }
  }

  function remember(entry: Loaded): void {
    cache.delete(entry.identity)
    cache.set(entry.identity, entry)
    if (cache.size > CACHE_LIMIT) cache.delete(cache.keys().next().value!)
  }

  /** The events already on hand, cut down to `span`, when they were loaded for a range that contains it. */
  function narrowedFromLoaded(analysisId: number, span: Span, identity: string): Loaded | undefined {
    const current = loaded.value
    if (!current || current.analysisId !== analysisId || current.filterKey !== filterKey.value || current.data.mode !== 'events') return undefined
    if (span.start < current.span.start || span.end > current.span.end || current.data.detections.length >= DETECTION_LIMIT) return undefined
    const events = current.data.events.filter((event) => isWithin(span, Date.parse(event.time)))
    const detections = current.data.detections.filter((detection) => isWithin(span, Date.parse(detection.time)))
    return { ...current, identity, span, data: { mode: 'events', events, detections }, total: events.length }
  }

  async function loadData(force = false): Promise<void> {
    const span = committedView.value
    const analysisId = query.analysisId
    if (span === null || analysisId === undefined) return
    const identity = identityOf(analysisId, span)
    if (!force && (identity === inFlight || identity === loaded.value?.identity)) return
    const request = dataRequests.next()
    error.value = undefined
    const known = cache.get(identity) ?? narrowedFromLoaded(analysisId, span, identity)
    if (known) {
      remember(known)
      loaded.value = known
      loading.value = false
      inFlight = undefined
      return
    }
    loading.value = true
    inFlight = identity
    const outcome = await fetchRange(analysisId, span, request)
    if (outcome === 'stale') return
    loading.value = false
    inFlight = undefined
    if ('failure' in outcome) {
      error.value = outcome.failure
      return
    }
    const entry = { identity, analysisId, filterKey: filterKey.value, span, ...outcome.done }
    remember(entry)
    loaded.value = entry
  }

  async function loadBounds(): Promise<void> {
    const analysisId = query.analysisId
    if (analysisId === undefined) return
    const request = boundsRequests.next()
    boundsRequestedFor = analysisId
    error.value = undefined
    const { data: bounds, error: failure, response } = await eventsHistogram({
      path: { analysis_id: analysisId },
      body: { interval: 'auto' },
      meta: QUIET_ON_EVENT_FAILURES,
    })
    if (!boundsRequests.isCurrent(request)) return
    if (!bounds) {
      error.value = searchFailure(failure, response)
      return
    }
    boundsLoaded.value = true
    if (bounds.from === null || bounds.to === null) return
    full.value = paddedFullSpan(Date.parse(bounds.from), Date.parse(bounds.to))
    view.value = full.value
    committedView.value = full.value
    await loadData()
  }

  function forgetEverything(): void {
    boundsRequests.invalidate()
    dataRequests.invalidate()
    commitSoon.cancel()
    reloadSoon.cancel()
    cache.clear()
    full.value = null
    view.value = null
    committedView.value = null
    loaded.value = undefined
    boundsLoaded.value = false
    boundsRequestedFor = undefined
    loading.value = false
    inFlight = undefined
    error.value = undefined
  }

  const commitSoon = debounced(() => {
    committedView.value = view.value
  }, TIMELINE_DEBOUNCE_MS)
  const reloadSoon = debounced(() => void loadData(), TIMELINE_DEBOUNCE_MS)

  watch(
    () => query.analysisId,
    (analysisId) => {
      if (analysisId === boundsRequestedFor) return
      forgetEverything()
      if (active.value && analysisId !== undefined) void loadBounds()
    },
  )
  watch(committedView, () => {
    if (active.value) void loadData()
  })
  watch(filterKey, () => {
    if (active.value && committedView.value !== null) reloadSoon()
  })

  function activate(): void {
    active.value = true
    if (query.analysisId === undefined) return
    if (!boundsLoaded.value) {
      if (boundsRequestedFor !== query.analysisId || error.value) void loadBounds()
    } else if (full.value !== null) void loadData()
  }

  function deactivate(): void {
    active.value = false
    reloadSoon.cancel()
  }

  function retry(): Promise<void> {
    return boundsLoaded.value ? loadData(true) : loadBounds()
  }

  function moveTo(next: Span | null): void {
    if (next === null || full.value === null) return
    view.value = clampView(next, full.value)
    commitSoon()
  }

  function zoomAt(time: number, factor: number): void {
    if (view.value && full.value) moveTo(zoomAround(view.value, full.value, time, factor))
  }

  function panByPixels(dx: number, width: number): void {
    if (view.value && full.value) moveTo(pannedByPixels(view.value, full.value, dx, width))
  }

  function panByFraction(fraction: number): void {
    if (view.value && full.value) moveTo(pannedByFraction(view.value, full.value, fraction))
  }

  function jumpTo(edge: 'start' | 'end'): void {
    if (view.value && full.value) moveTo(jumpedView(view.value, full.value, edge))
  }

  function applyPreset(zoom: ZoomPreset, focus?: number): void {
    if (view.value && full.value) moveTo(presetView(zoom, view.value, full.value, focus))
  }

  /** Brings a time into view when it is outside it, at the same zoom; a time already in view does not move the view. */
  function reveal(time: number): void {
    if (view.value && full.value && !isWithin(view.value, time)) moveTo(centreOn(view.value, full.value, time))
  }

  return {
    full,
    view,
    committedView,
    data,
    total,
    status,
    loading,
    error,
    preset,
    chipSpan,
    tableRange,
    activate,
    deactivate,
    retry,
    setView: moveTo,
    zoomAt,
    panByPixels,
    panByFraction,
    jumpTo,
    applyPreset,
    fit: () => applyPreset('fit'),
    reveal,
  }
})
