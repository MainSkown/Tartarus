import { ref, watch } from 'vue'
import { isExtraColumn } from '@/services/event-columns'
import { readStored, writeStored } from '@/services/viewer-storage'

export const COLUMNS_STORAGE_KEY = 'tartarus.events.columns'

function isListOfNames(value: unknown): value is unknown[] {
  return Array.isArray(value)
}

/** The extra table columns this viewer chose, in order, remembered between visits. */
export function useEventColumns() {
  const remembered = readStored<unknown[]>(COLUMNS_STORAGE_KEY, [], isListOfNames)
  const chosen = ref<string[]>(remembered.filter((name): name is string => typeof name === 'string' && isExtraColumn(name)))

  watch(chosen, (names) => writeStored(COLUMNS_STORAGE_KEY, names), { deep: true })

  const isChosen = (field: string): boolean => chosen.value.includes(field)

  function toggle(field: string): void {
    chosen.value = isChosen(field) ? chosen.value.filter((name) => name !== field) : [...chosen.value, field]
  }

  function clear(): void {
    chosen.value = []
  }

  return { chosen, isChosen, toggle, clear }
}
