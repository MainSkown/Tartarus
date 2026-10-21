import { computed, onScopeDispose, ref, watch, type Ref } from 'vue'
import { queryFields, queryValues } from '@/api'
import type { FieldRead } from '@/api'
import { QUIET_ON_QUERY_FAILURES } from '@/services/quiet-statuses'
import { tokenAt, type QuerySuggestion, type QueryToken } from '@/services/query-token'
import { useFieldCatalogStore } from '@/stores/field-catalog'

export const SUGGESTION_DELAY_MS = 120
const VALUE_LIMIT = 10
const NOTHING_CHOSEN = -1

export type SuggestionItem = { kind: 'field'; field: FieldRead } | { kind: 'value'; value: string; count: number }

export function suggestionFor(item: SuggestionItem): QuerySuggestion {
  return item.kind === 'field' ? { kind: 'field', name: item.field.name } : { kind: 'value', value: item.value }
}

async function fieldItems(prefix: string): Promise<SuggestionItem[]> {
  const { data } = await queryFields({ query: { prefix }, meta: QUIET_ON_QUERY_FAILURES })
  return (data ?? []).map((field) => ({ kind: 'field', field }))
}

async function valueItems(analysisId: number, field: string, prefix: string): Promise<SuggestionItem[]> {
  const { data } = await queryValues({
    path: { analysis_id: analysisId },
    query: { field, prefix, limit: VALUE_LIMIT },
    meta: QUIET_ON_QUERY_FAILURES,
  })
  return (data?.values ?? []).map(({ value, count }) => ({ kind: 'value', value, count }))
}

/**
 * The completions for the token under the caret: field names from the catalog, and the values of a
 * keyword field from the analysis. The list is closed until the user types, so focusing the bar
 * on a finished query does not pop it open.
 */
export function useQuerySuggestions(draft: Ref<string>, caret: Ref<number>, analysisId: () => number | undefined) {
  const catalog = useFieldCatalogStore()
  const token = computed(() => tokenAt(draft.value, caret.value))
  const items = ref<SuggestionItem[]>([])
  const activeIndex = ref(NOTHING_CHOSEN)
  const dismissed = ref(true)
  const open = computed(() => !dismissed.value && items.value.length > 0)
  const active = computed(() => items.value[activeIndex.value])

  let timer: ReturnType<typeof setTimeout> | undefined
  let latestRequest = 0

  async function fetchFor(current: QueryToken): Promise<SuggestionItem[]> {
    try {
      if (current.kind === 'field') return await fieldItems(current.prefix)
      if (current.kind !== 'value') return []
      await catalog.load()
      const bound = analysisId()
      return bound !== undefined && catalog.offersValues(current.field) ? await valueItems(bound, current.field, current.prefix) : []
    } catch {
      return []
    }
  }

  function hasNothingToAsk(current: QueryToken): boolean {
    return current.kind === 'none' || (current.kind === 'field' && current.prefix === '')
  }

  const tokenIdentity = computed(() => {
    const { kind, prefix } = token.value
    return [kind, token.value.kind === 'value' ? token.value.field : '', prefix].join('\u0000')
  })

  watch(tokenIdentity, () => {
    clearTimeout(timer)
    const request = ++latestRequest
    const current = token.value
    if (hasNothingToAsk(current)) {
      items.value = []
      return
    }
    timer = setTimeout(async () => {
      const found = await fetchFor(current)
      if (request === latestRequest) items.value = found
    }, SUGGESTION_DELAY_MS)
  })

  watch(items, () => {
    activeIndex.value = NOTHING_CHOSEN
  })

  function move(delta: number): void {
    const count = items.value.length
    if (count === 0) return
    if (activeIndex.value === NOTHING_CHOSEN) activeIndex.value = delta > 0 ? 0 : count - 1
    else activeIndex.value = (activeIndex.value + delta + count) % count
  }

  const dismiss = (): void => {
    dismissed.value = true
  }
  const reveal = (): void => {
    dismissed.value = false
  }

  onScopeDispose(() => clearTimeout(timer))

  return { token, items, open, active, activeIndex, move, dismiss, reveal, suggestionFor }
}
