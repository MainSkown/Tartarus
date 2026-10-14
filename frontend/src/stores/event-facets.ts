import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { eventsFacets } from '@/api'
import type { Facet } from '@/api'
import { debounced } from '@/services/debounced'
import { FACET_FIELDS } from '@/services/event-fields'
import { createRequestSequence } from '@/services/request-sequence'
import { quietOn } from '@/services/quiet-statuses'
import { searchFailure } from '@/services/search-failure'
import { useQueryStateStore } from '@/stores/query-state'

export const FACETS_DEBOUNCE_MS = 50
// The panel shows its own failure and the table works without it, so no toast.
const QUIET_ON_FACET_FAILURES = quietOn(422, 500, 502, 504)

/**
 * The top values of the facet fields over the events the shared query state keeps. It follows the
 * same filter as the events store but not its sort, since a sort changes no count; a failure stays
 * in this store and never reaches the table.
 */
export const useEventFacetsStore = defineStore('event-facets', () => {
  const query = useQueryStateStore()
  const facets = ref<Facet[]>([])
  const loading = ref(false)
  const error = ref<string>()
  const active = ref(false)

  const requests = createRequestSequence()
  let loadedKey: string | undefined
  let requestedKey: string | undefined
  let requestedAnalysisId: number | undefined

  const requestKey = computed(() =>
    query.analysisId === undefined ? undefined : JSON.stringify([query.analysisId, query.searchFilter]),
  )

  async function load(): Promise<void> {
    const key = requestKey.value
    if (key === undefined || query.analysisId === undefined) return
    const request = requests.next()
    requestedKey = key
    requestedAnalysisId = query.analysisId
    loading.value = true
    error.value = undefined
    const { data, error: failure, response } = await eventsFacets({
      path: { analysis_id: query.analysisId },
      body: { ...query.searchFilter, fields: FACET_FIELDS },
      meta: QUIET_ON_FACET_FAILURES,
    })
    if (!requests.isCurrent(request)) return
    loading.value = false
    if (data) {
      facets.value = data.facets
      loadedKey = key
      return
    }
    facets.value = []
    loadedKey = undefined
    error.value = searchFailure(failure, response).message
  }

  const reloadSoon = debounced(() => void load(), FACETS_DEBOUNCE_MS)

  watch(
    () => query.analysisId,
    (analysisId) => {
      if (analysisId === requestedAnalysisId) return
      requests.invalidate()
      facets.value = []
      error.value = undefined
      loadedKey = undefined
      requestedKey = undefined
      requestedAnalysisId = undefined
    },
  )
  watch(requestKey, (key) => {
    if (!active.value || key === undefined || key === requestedKey) return
    requests.invalidate()
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

  function byField(field: string): Facet | undefined {
    return facets.value.find((facet) => facet.field === field)
  }

  return { facets, loading, error, activate, deactivate, retry: load, byField }
})
