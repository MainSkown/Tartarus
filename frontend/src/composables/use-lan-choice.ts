import { computed, ref, watch, type Ref } from 'vue'
import type { Route } from '@/api'
import { useLanPresets } from '@/composables/use-lan-presets'
import { t } from '@/i18n'

const REFUSED_ROUTE: Route = 'internet'

/**
 * The Submit dialog's SIMULATE LOCAL NETWORK control: whether it is on, which preset is chosen (the only
 * preset there is, else the analyst's pick), and what keeps the form from being submitted. The presets are
 * asked for the first time the switch goes on, so a dialog that never uses it never asks.
 */
export function useLanChoice(route: Readonly<Ref<Route>>) {
  const presets = useLanPresets()
  const enabled = ref(false)
  const presetId = ref<string | null>(null)

  const routeRefused = computed(() => route.value === REFUSED_ROUTE)

  const blockReason = computed(() => {
    if (!enabled.value) return undefined
    if (presets.loading.value) return t('submit.blocked.lanLoading')
    if (presets.error.value) return t('submit.blocked.lanUnavailable')
    if (presets.presets.value.length === 0) return t('submit.blocked.lanNone')
    return presetId.value ? undefined : t('submit.blocked.lanPreset')
  })

  const optionPayload = computed(() => (enabled.value && presetId.value ? { lan_preset: presetId.value } : {}))

  watch(enabled, (on) => {
    if (on) void presets.load()
  })

  watch(routeRefused, (refused) => {
    if (refused) enabled.value = false
  })

  watch(presets.presets, (listed) => {
    const stillListed = listed.some((preset) => preset.id === presetId.value)
    if (!stillListed) presetId.value = listed.length === 1 ? listed[0]!.id : null
  })

  return { enabled, presetId, presets, routeRefused, blockReason, optionPayload }
}
