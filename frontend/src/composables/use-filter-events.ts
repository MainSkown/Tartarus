import { nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAnalysisTabNavigation } from '@/composables/use-analysis-tab-navigation'
import type { EventsFilter } from '@/services/events-filters'
import { withQueryState } from '@/services/query-url'
import { useQueryStateStore } from '@/stores/query-state'

const EVENTS_TAB = 'events'

/**
 * The actions that take an analyst from any tab to the Events tab with the shared query changed:
 * a chip per field value, one process, or a whole query text. Each changes only what it names.
 */
export function useFilterEvents() {
  const route = useRoute()
  const query = useQueryStateStore()
  const { openTab } = useAnalysisTabNavigation()

  async function goToEvents(): Promise<void> {
    // The URL sync writes the changed state to the current tab's route in a flush that is still
    // pending; navigating before it ran would be cancelled by that write, so let it run first.
    await nextTick()
    await openTab(EVENTS_TAB, withQueryState(route.query, query.urlState))
  }

  async function filterOnEvents(...filters: EventsFilter[]): Promise<void> {
    for (const { field, value, negate = false } of filters) query.addChip({ field, value: String(value), negate })
    await goToEvents()
  }

  async function showProcessEvents(pid: number): Promise<void> {
    query.setPids([pid])
    await goToEvents()
  }

  async function showEventsMatching(text: string): Promise<void> {
    query.setText(text)
    await goToEvents()
  }

  return { filterOnEvents, showProcessEvents, showEventsMatching }
}
