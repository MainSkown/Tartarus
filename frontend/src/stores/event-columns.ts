import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { MAX_COLUMNS, offeredColumnFields } from '@/services/event-columns'
import { readStored, writeStored } from '@/services/viewer-storage'
import { useFieldCatalogStore } from '@/stores/field-catalog'

export const COLUMNS_STORAGE_KEY = 'tartarus.events.columns'

function rememberedNames(): string[] {
  const stored = readStored<unknown>(COLUMNS_STORAGE_KEY, [], Array.isArray)
  return (stored as unknown[]).filter((name): name is string => typeof name === 'string').slice(0, MAX_COLUMNS)
}

/**
 * The extra table columns this viewer chose, in order, remembered between visits. The events store
 * sends them with every search, so a change here is a new request.
 */
export const useEventColumnsStore = defineStore('event-columns', () => {
  const catalog = useFieldCatalogStore()
  const chosen = ref<string[]>(rememberedNames())

  const atLimit = computed(() => chosen.value.length >= MAX_COLUMNS)

  watch(chosen, (names) => writeStored(COLUMNS_STORAGE_KEY, names), { deep: true })

  const isChosen = (field: string): boolean => chosen.value.includes(field)

  function toggle(field: string): void {
    if (isChosen(field)) chosen.value = chosen.value.filter((name) => name !== field)
    else if (!atLimit.value) chosen.value = [...chosen.value, field]
  }

  function clear(): void {
    chosen.value = []
  }

  /**
   * Replaces remembered names by their canonical catalog field and drops those that are no longer
   * offered, so a search is never refused for a column left over from an older catalog. A catalog
   * that cannot be loaded changes nothing.
   */
  async function validate(): Promise<void> {
    if (chosen.value.length === 0) return
    await catalog.load()
    const offered = offeredColumnFields(catalog.fields)
    if (offered.length === 0) return
    const canonical = chosen.value
      .map((name) => offered.find((field) => field.name === name || field.aliases.includes(name.toLowerCase()))?.name)
      .filter((name): name is string => name !== undefined)
    chosen.value = [...new Set(canonical)]
  }

  return { chosen, atLimit, isChosen, toggle, clear, validate }
})
