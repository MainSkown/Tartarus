import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { queryFields } from '@/api'
import type { FieldRead } from '@/api'
import { QUIET_ON_QUERY_FAILURES } from '@/services/quiet-statuses'

export interface AliasRow {
  alias: string
  field: string
}

const VALUE_TYPES = new Set<FieldRead['type']>(['keyword', 'keyword_with_text'])
const COMPOSITE_JOIN = ' OR '

/**
 * The field catalog (names, aliases, types) the backend's query compiler reads, loaded once: the
 * source of truth for which fields exist, which take value suggestions and the cheat sheet's
 * alias table.
 */
export const useFieldCatalogStore = defineStore('field-catalog', () => {
  const fields = ref<FieldRead[]>([])
  let loading: Promise<void> | undefined

  async function fetchAll(): Promise<void> {
    const { data } = await queryFields({ meta: QUIET_ON_QUERY_FAILURES })
    if (data) fields.value = data
  }

  /** Asks the backend once; after a failed attempt the next call asks again. */
  async function load(): Promise<void> {
    if (fields.value.length > 0) return
    loading ??= fetchAll().finally(() => {
      loading = undefined
    })
    await loading
  }

  function find(nameOrAlias: string): FieldRead | undefined {
    const wanted = nameOrAlias.toLowerCase()
    return fields.value.find((field) => field.name.toLowerCase() === wanted || field.aliases.includes(wanted))
  }

  /** The catalog name a name or alias stands for; a name the catalog does not know comes back as it is. */
  function canonicalName(nameOrAlias: string): string {
    return find(nameOrAlias)?.name ?? nameOrAlias
  }

  function offersValues(nameOrAlias: string): boolean {
    const field = find(nameOrAlias)
    return field !== undefined && field.searchable && VALUE_TYPES.has(field.type)
  }

  const aliasRows = computed<AliasRow[]>(() => {
    const rows = fields.value.flatMap((field) =>
      field.members.length > 0
        ? [{ alias: field.name, field: field.members.join(COMPOSITE_JOIN) }]
        : field.aliases.map((alias) => ({ alias, field: field.name })),
    )
    return rows.sort((a, b) => a.alias.localeCompare(b.alias))
  })

  return { fields, load, find, canonicalName, offersValues, aliasRows }
})
