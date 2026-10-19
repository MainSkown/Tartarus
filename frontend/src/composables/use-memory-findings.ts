import { computed, watch } from 'vue'
import { eventsSearch } from '@/api'
import { useAnalysisView } from '@/composables/use-analysis-view'
import { findingFromEvent, memoryFindingsRequest, type MemoryFinding } from '@/services/memory-findings'
import { QUIET_ON_EVENT_FAILURES } from '@/stores/events'

interface Loaded {
  findings: MemoryFinding[]
  total: number
}

const NOTHING: Loaded = { findings: [], total: 0 }

/**
 * The Volatility findings of an analysis, in one request: they are few, and the groups' counts
 * would be wrong if only a page of them were here. With no dump to read (`enabled` false) it asks
 * for nothing.
 */
export function useMemoryFindings(analysisId: () => number, enabled: () => boolean) {
  const view = useAnalysisView<Loaded>(analysisId, async (id) => {
    if (!enabled()) return { data: NOTHING }
    const { data, error } = await eventsSearch({
      path: { analysis_id: id },
      body: memoryFindingsRequest(),
      meta: QUIET_ON_EVENT_FAILURES,
    })
    return data ? { data: { findings: data.events.map(findingFromEvent), total: data.total } } : { error }
  })

  watch(enabled, () => void view.reload())

  const findings = computed(() => view.data.value?.findings ?? [])
  const total = computed(() => view.data.value?.total ?? 0)
  return {
    findings,
    total,
    truncated: computed(() => total.value > findings.value.length),
    counted: computed(() => (enabled() && view.data.value ? findings.value.length : undefined)),
    loading: view.loading,
    error: view.error,
    reload: view.reload,
  }
}
