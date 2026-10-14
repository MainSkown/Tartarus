import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { rulesList, rulesRead, rulesReload, rulesUpdate } from '@/api'
import type { RuleDetail, RuleRead } from '@/api'
import { errorMessage } from '@/services/api-error'
import { NOT_FOUND_STATUS, quietOn } from '@/services/quiet-statuses'

/**
 * The Sigma rules the Rules page lists, the one it has open, and the enabled switches. The
 * server owns the rules; filtering and sorting are the page's, so the list is held as received.
 */
export const useRulesStore = defineStore('rules', () => {
  const items = ref<RuleRead[]>([])
  const loading = ref(false)
  const loadError = ref<string>()
  const reloading = ref(false)

  const selectedId = ref<string>()
  const detail = ref<RuleDetail>()
  const detailLoading = ref(false)
  const detailError = ref<string>()
  const toggling = ref<ReadonlySet<string>>(new Set())

  // A detail is applied only while it is for the latest selection, so a slow read of a rule the
  // analyst has already moved off can never overwrite the one they are looking at.
  let detailRequestId = 0

  const selected = computed(() => items.value.find((rule) => rule.id === selectedId.value))

  async function load(): Promise<void> {
    loading.value = true
    const { data, error } = await rulesList()
    loading.value = false
    loadError.value = error || !data ? errorMessage(error) : undefined
    if (data && !error) items.value = data
  }

  async function reload(): Promise<boolean> {
    reloading.value = true
    const { data, error } = await rulesReload()
    reloading.value = false
    if (error || !data) return false
    items.value = data
    if (selectedId.value !== undefined) await refreshSelection(selectedId.value)
    return true
  }

  async function refreshSelection(id: string): Promise<void> {
    if (items.value.some((rule) => rule.id === id)) await select(id)
    else clearSelection()
  }

  function replace(updated: RuleRead): void {
    items.value = items.value.map((rule) => (rule.id === updated.id ? updated : rule))
  }

  function setToggling(id: string, on: boolean): void {
    const next = new Set(toggling.value)
    if (on) next.add(id)
    else next.delete(id)
    toggling.value = next
  }

  function isToggling(id: string): boolean {
    return toggling.value.has(id)
  }

  /** Flips the switch at once and puts it back if the server does not take the change. */
  async function toggleEnabled(id: string, enabled: boolean): Promise<boolean> {
    const rule = items.value.find((known) => known.id === id)
    if (!rule || isToggling(id) || (enabled && rule.validity !== 'valid')) return false
    setToggling(id, true)
    replace({ ...rule, enabled })
    const { data, error } = await rulesUpdate({ path: { rule_id: id }, body: { enabled } })
    setToggling(id, false)
    if (error || !data) {
      replace(rule)
      return false
    }
    replace(data)
    return true
  }

  async function select(id: string): Promise<void> {
    const requestId = ++detailRequestId
    selectedId.value = id
    detail.value = undefined
    detailError.value = undefined
    detailLoading.value = true
    // A rule whose file vanished is a state the pane shows, not a fault to toast about.
    const { data, error } = await rulesRead({ path: { rule_id: id }, meta: quietOn(NOT_FOUND_STATUS) })
    if (requestId !== detailRequestId) return
    detailLoading.value = false
    if (error || !data) detailError.value = errorMessage(error)
    else detail.value = data
  }

  function clearSelection(): void {
    detailRequestId++
    selectedId.value = undefined
    detail.value = undefined
    detailError.value = undefined
    detailLoading.value = false
  }

  return {
    items,
    loading,
    loadError,
    reloading,
    selectedId,
    selected,
    detail,
    detailLoading,
    detailError,
    toggling,
    isToggling,
    load,
    reload,
    toggleEnabled,
    select,
    clearSelection,
  }
})
