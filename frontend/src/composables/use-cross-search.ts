import { computed, ref } from 'vue'
import { searchAcrossAnalyses } from '@/api'
import type { CrossSearchEvent, Event, SortOrder } from '@/api'
import { createRequestSequence } from '@/services/request-sequence'
import { searchFailure, type SearchFailure } from '@/services/search-failure'
import { QUIET_ON_EVENT_FAILURES } from '@/stores/events'
import { useEventColumnsStore } from '@/stores/event-columns'
import type { SearchFilter } from '@/stores/query-state'

export const CROSS_SEARCH_PAGE_SIZE = 100

/** An event of the search, with the analysis it came from. */
export type SearchRow = Event & { analysis_id: number }

/**
 * The events of every analysis that match one filter, in pages that follow the server's cursor.
 * A new run, sort or retry replaces what is listed; an answer to a request that a newer one has
 * replaced is dropped, as the Events tab does.
 */
function toRows(hits: CrossSearchEvent[]): SearchRow[] {
  return hits.map(({ analysis_id, event }) => ({ ...event, analysis_id }))
}

export function useCrossSearch() {
  const columns = useEventColumnsStore()
  const rows = ref<SearchRow[]>([])
  const total = ref(0)
  const nextCursor = ref<string | null>(null)
  const sort = ref<SortOrder>('@timestamp')
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref<SearchFailure>()
  const loadMoreError = ref<string>()
  const searched = ref(false)
  const hasMore = computed(() => nextCursor.value !== null)

  const requests = createRequestSequence()
  let lastFilter: SearchFilter | undefined

  function ask(filter: SearchFilter, searchAfter?: string) {
    return searchAcrossAnalyses({
      body: {
        ...filter,
        sort: sort.value,
        size: CROSS_SEARCH_PAGE_SIZE,
        ...(columns.chosen.length > 0 && { columns: [...columns.chosen] }),
        ...(searchAfter && { search_after: searchAfter }),
      },
      meta: QUIET_ON_EVENT_FAILURES,
    })
  }

  async function fetchFirstPage(filter: SearchFilter): Promise<void> {
    const request = requests.next()
    loading.value = true
    loadingMore.value = false
    error.value = undefined
    loadMoreError.value = undefined
    if (columns.chosen.length > 0) await columns.validate()
    if (!requests.isCurrent(request)) return
    const { data, error: failure, response } = await ask(filter)
    if (!requests.isCurrent(request)) return
    loading.value = false
    if (data) {
      rows.value = toRows(data.events)
      total.value = data.total
      nextCursor.value = data.next_cursor
      return
    }
    rows.value = []
    total.value = 0
    nextCursor.value = null
    error.value = searchFailure(failure, response)
  }

  async function run(filter: SearchFilter): Promise<void> {
    lastFilter = filter
    searched.value = true
    await fetchFirstPage(filter)
  }

  async function retry(): Promise<void> {
    if (lastFilter !== undefined) await fetchFirstPage(lastFilter)
  }

  async function loadMore(): Promise<void> {
    const cursor = nextCursor.value
    if (lastFilter === undefined || cursor === null || loading.value || loadingMore.value) return
    const request = requests.next()
    loadingMore.value = true
    loadMoreError.value = undefined
    const { data, error: failure, response } = await ask(lastFilter, cursor)
    if (!requests.isCurrent(request)) return
    loadingMore.value = false
    if (data) {
      rows.value = [...rows.value, ...toRows(data.events)]
      total.value = data.total
      nextCursor.value = data.next_cursor
    } else {
      loadMoreError.value = searchFailure(failure, response).message
    }
  }

  async function toggleSort(): Promise<void> {
    sort.value = sort.value === '@timestamp' ? '-@timestamp' : '@timestamp'
    await retry()
  }

  function clear(): void {
    requests.invalidate()
    lastFilter = undefined
    rows.value = []
    total.value = 0
    nextCursor.value = null
    loading.value = false
    loadingMore.value = false
    error.value = undefined
    loadMoreError.value = undefined
    searched.value = false
  }

  return {
    rows,
    total,
    sort,
    loading,
    loadingMore,
    hasMore,
    error,
    loadMoreError,
    searched,
    run,
    retry,
    loadMore,
    toggleSort,
    clear,
  }
}
