import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { errorMessage } from '@/services/api-error'

interface Outcome<T> {
  data?: T
  error?: unknown
}

export interface AnalysisView<T> {
  data: Ref<T | undefined>
  loading: Ref<boolean>
  error: Ref<string | undefined>
  reload: () => Promise<void>
}

/**
 * Loads one view of an analysis (the processes, the network, ...) and reloads it when the
 * analysis changes. An answer for an analysis that is no longer shown is dropped.
 */
export function useAnalysisView<T>(
  analysisId: () => number,
  load: (analysisId: number) => Promise<Outcome<T>>,
): AnalysisView<T> {
  const data = ref<T>()
  const loading = ref(true)
  const error = ref<string>()
  let latestRequest = 0
  let active = true

  async function reload(): Promise<void> {
    const request = ++latestRequest
    loading.value = true
    error.value = undefined
    const outcome = await load(analysisId())
    if (request !== latestRequest || !active) return
    if (outcome.data === undefined) {
      data.value = undefined
      error.value = errorMessage(outcome.error)
    } else {
      data.value = outcome.data
    }
    loading.value = false
  }

  watch(analysisId, () => {
    data.value = undefined
    void reload()
  })
  onScopeDispose(() => {
    active = false
  })
  void reload()

  return { data, loading, error, reload }
}
