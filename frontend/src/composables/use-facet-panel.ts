import { ref, watch } from 'vue'
import { readStored, writeStored } from '@/services/viewer-storage'

export const FACET_PANEL_STORAGE_KEY = 'tartarus.events.facets-open'

/** Whether the facet panel is open, remembered for this viewer; it starts open. */
export function useFacetPanel() {
  const open = ref(readStored(FACET_PANEL_STORAGE_KEY, true, (value) => typeof value === 'boolean'))
  watch(open, (isOpen) => writeStored(FACET_PANEL_STORAGE_KEY, isOpen))

  function toggle(): void {
    open.value = !open.value
  }

  return { open, toggle }
}
