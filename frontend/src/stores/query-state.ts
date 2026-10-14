import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { FilterChip, SearchRequest, TimeRange } from '@/api'
import { isSameFilter, type QueryTimeRange, type QueryUrlState } from '@/services/query-url'

/** The part of a search request that the query bar, the chips and the selected process decide. */
export type SearchFilter = Pick<SearchRequest, 'query' | 'filters' | 'time_range' | 'pids'>

function hasEnd(range: QueryTimeRange | null): range is QueryTimeRange {
  return range !== null && (range.from !== null || range.to !== null)
}

function apiTimeRange({ from, to }: QueryTimeRange): TimeRange {
  return { ...(from !== null && { from }), ...(to !== null && { to }) }
}

/**
 * The one copy of what the Events and Timeline tabs are filtered by (M3 decision 10): the applied
 * query text, the chips, the selected processes and the time range. The query bar's draft is not
 * here; it becomes `text` when the user applies it.
 */
export const useQueryStateStore = defineStore('query-state', () => {
  const analysisId = ref<number>()
  const text = ref('')
  const chips = ref<FilterChip[]>([])
  const pids = ref<number[]>([])
  const timeRange = ref<QueryTimeRange | null>(null)

  const urlState = computed<QueryUrlState>(() => ({
    text: text.value,
    chips: chips.value.map((chip) => ({ ...chip })),
    pids: [...pids.value],
    timeRange: timeRange.value && { ...timeRange.value },
  }))

  // An empty list is left out, not sent: for `pids` the API reads it as "match nothing".
  const searchFilter = computed<SearchFilter>(() => ({
    ...(text.value.trim() !== '' && { query: text.value }),
    ...(chips.value.length > 0 && { filters: chips.value.map((chip) => ({ ...chip })) }),
    ...(hasEnd(timeRange.value) && { time_range: apiTimeRange(timeRange.value) }),
    ...(pids.value.length > 0 && { pids: [...pids.value] }),
  }))

  const isEmpty = computed(() => Object.keys(searchFilter.value).length === 0)

  function setText(applied: string): void {
    text.value = applied
  }

  function addChip(chip: FilterChip): void {
    const existing = chips.value.findIndex((known) => isSameFilter(known, chip))
    if (existing < 0) chips.value.push({ ...chip })
    else chips.value[existing] = { ...chip }
  }

  function toggleChip(index: number): void {
    const chip = chips.value[index]
    if (chip) chip.negate = !chip.negate
  }

  function removeChip(index: number): void {
    if (index >= 0 && index < chips.value.length) chips.value.splice(index, 1)
  }

  function setPids(selected: number[]): void {
    pids.value = [...selected]
  }

  function togglePid(pid: number): void {
    pids.value = pids.value.includes(pid) ? pids.value.filter((known) => known !== pid) : [...pids.value, pid]
  }

  function setTimeRange(range: QueryTimeRange): void {
    timeRange.value = hasEnd(range) ? { ...range } : null
  }

  function clearTimeRange(): void {
    timeRange.value = null
  }

  function restore(state: QueryUrlState): void {
    setText(state.text)
    chips.value = state.chips.map((chip) => ({ ...chip }))
    setPids(state.pids)
    timeRange.value = state.timeRange && { ...state.timeRange }
  }

  function reset(): void {
    restore({ text: '', chips: [], pids: [], timeRange: null })
  }

  function bindTo(id: number | undefined): void {
    if (analysisId.value === id) return
    reset()
    analysisId.value = id
  }

  return {
    analysisId,
    text,
    chips,
    pids,
    timeRange,
    urlState,
    searchFilter,
    isEmpty,
    setText,
    addChip,
    toggleChip,
    removeChip,
    setPids,
    togglePid,
    setTimeRange,
    clearTimeRange,
    restore,
    reset,
    bindTo,
  }
})
