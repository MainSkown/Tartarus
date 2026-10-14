import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { eventsSearch } from '@/api'
import type { Event, EventPage, SortOrder } from '@/api'
import { debounced } from '@/services/debounced'
import { createRequestSequence } from '@/services/request-sequence'
import { quietOn } from '@/services/quiet-statuses'
import { searchFailure, type SearchFailure } from '@/services/search-failure'
import { useEventColumnsStore } from '@/stores/event-columns'
import { useQueryStateStore } from '@/stores/query-state'

export const EVENTS_PAGE_SIZE = 100
export const EVENTS_DEBOUNCE_MS = 50
// The tab shows these failures itself, with a retry; a toast on top would say it twice.
export const QUIET_ON_EVENT_FAILURES = quietOn(422, 502, 504)

type Step = 1 | -1

/**
 * The events the Events tab lists: the current analysis filtered by the shared query state, in
 * pages of `EVENTS_PAGE_SIZE` that follow the server's cursor. It asks again when the filter, the
 * sort or the analysis changes, and only while a view is showing it (`activate`/`deactivate`); an
 * answer to a request that a newer one has replaced is dropped.
 */
export const useEventsStore = defineStore('events', () => {
  const query = useQueryStateStore()
  const columns = useEventColumnsStore()
  const events = ref<Event[]>([])
  const total = ref(0)
  const nextCursor = ref<string | null>(null)
  const sort = ref<SortOrder>('@timestamp')
  const loading = ref(false)
  const loadingMore = ref(false)
  const loaded = ref(false)
  const error = ref<SearchFailure>()
  const loadMoreError = ref<string>()
  const active = ref(false)

  const requests = createRequestSequence()
  let loadedKey: string | undefined
  let requestedKey: string | undefined
  let requestedAnalysisId: number | undefined

  const hasMore = computed(() => nextCursor.value !== null)
  const requestKey = computed(() =>
    query.analysisId === undefined ? undefined : JSON.stringify([query.analysisId, query.searchFilter, sort.value, columns.chosen]),
  )

  function search(analysisId: number, searchAfter?: string) {
    return eventsSearch({
      path: { analysis_id: analysisId },
      body: {
        ...query.searchFilter,
        sort: sort.value,
        size: EVENTS_PAGE_SIZE,
        ...(columns.chosen.length > 0 && { columns: [...columns.chosen] }),
        ...(searchAfter && { search_after: searchAfter }),
      },
      meta: QUIET_ON_EVENT_FAILURES,
    })
  }

  function applyFirstPage(page: EventPage): void {
    events.value = page.events
    total.value = page.total
    nextCursor.value = page.next_cursor
    loaded.value = true
  }

  async function load(): Promise<void> {
    if (requestKey.value === undefined || query.analysisId === undefined) return
    const request = requests.next()
    requestedKey = requestKey.value
    requestedAnalysisId = query.analysisId
    loading.value = true
    loadingMore.value = false
    error.value = undefined
    loadMoreError.value = undefined
    await columns.validate()
    if (!requests.isCurrent(request)) return
    const key = requestKey.value
    requestedKey = key
    if (key === undefined || query.analysisId === undefined) return
    const { data, error: failure, response } = await search(query.analysisId)
    if (!requests.isCurrent(request)) return
    loading.value = false
    if (data) {
      applyFirstPage(data)
      loadedKey = key
      return
    }
    events.value = []
    total.value = 0
    nextCursor.value = null
    loadedKey = undefined
    error.value = searchFailure(failure, response)
  }

  async function loadMore(): Promise<void> {
    const cursor = nextCursor.value
    if (query.analysisId === undefined || cursor === null || loading.value || loadingMore.value) return
    const request = requests.next()
    loadingMore.value = true
    loadMoreError.value = undefined
    const { data, error: failure, response } = await search(query.analysisId, cursor)
    if (!requests.isCurrent(request)) return
    loadingMore.value = false
    if (data) {
      events.value = [...events.value, ...data.events]
      total.value = data.total
      nextCursor.value = data.next_cursor
    } else {
      loadMoreError.value = searchFailure(failure, response).message
    }
  }

  const reloadSoon = debounced(() => void load(), EVENTS_DEBOUNCE_MS)

  function forgetEverything(): void {
    requests.invalidate()
    events.value = []
    total.value = 0
    nextCursor.value = null
    error.value = undefined
    loadMoreError.value = undefined
    loadingMore.value = false
    loaded.value = false
    loadedKey = undefined
    requestedKey = undefined
    requestedAnalysisId = undefined
  }

  watch(
    () => query.analysisId,
    (analysisId) => {
      if (analysisId !== requestedAnalysisId) forgetEverything()
    },
  )
  watch(requestKey, (key) => {
    if (!active.value || key === undefined || key === requestedKey) return
    requests.invalidate()
    loadingMore.value = false
    loading.value = true
    reloadSoon()
  })

  function activate(): void {
    active.value = true
    if (requestKey.value === undefined || requestKey.value === loadedKey) return
    reloadSoon.cancel()
    void load()
  }

  function deactivate(): void {
    active.value = false
    reloadSoon.cancel()
  }

  function toggleSort(): void {
    sort.value = sort.value === '@timestamp' ? '-@timestamp' : '@timestamp'
  }

  function indexOfEvent(id: string): number {
    return events.value.findIndex((event) => event.id === id)
  }

  /** Whether `neighbour` can find something: the next one also counts a page not yet loaded. */
  function hasNeighbour(id: string, step: Step): boolean {
    const index = indexOfEvent(id)
    if (index < 0) return false
    return step === -1 ? index > 0 : index < events.value.length - 1 || hasMore.value
  }

  /** The id of the event before or after `id` in the list, loading the next page when `id` is the last one loaded. */
  async function neighbour(id: string, step: Step): Promise<string | undefined> {
    const index = indexOfEvent(id)
    if (index < 0) return undefined
    const target = index + step
    if (target >= events.value.length && hasMore.value) await loadMore()
    return events.value[target]?.id
  }

  return {
    events,
    total,
    sort,
    loading,
    loadingMore,
    loaded,
    error,
    loadMoreError,
    hasMore,
    activate,
    deactivate,
    load,
    retry: load,
    loadMore,
    toggleSort,
    hasNeighbour,
    neighbour,
  }
})
