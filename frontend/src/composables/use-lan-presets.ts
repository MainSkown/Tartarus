import { ref } from 'vue'
import { lanPresetsList } from '@/api'
import type { LanPreset } from '@/api'
import { errorMessage } from '@/services/api-error'
import { REFUSALS_SHOWN_INLINE } from '@/services/quiet-statuses'

/**
 * The fake local networks the backend offers, asked for when `load` is first called and again only on
 * `retry`: a failure is shown where the presets would be, so it needs no toast on top.
 */
export function useLanPresets() {
  const presets = ref<LanPreset[]>([])
  const loading = ref(false)
  const error = ref<string>()
  let loaded = false

  async function retry(): Promise<void> {
    loading.value = true
    error.value = undefined
    const { data, error: failure } = await lanPresetsList({ meta: REFUSALS_SHOWN_INLINE })
    loading.value = false
    if (failure || !data) {
      error.value = errorMessage(failure)
      return
    }
    presets.value = data
    loaded = true
  }

  async function load(): Promise<void> {
    if (loaded || loading.value) return
    await retry()
  }

  return { presets, loading, error, load, retry }
}
