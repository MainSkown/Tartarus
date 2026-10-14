import { computed, ref, watch } from 'vue'
import { eventsDetail } from '@/api'
import type { EventDetail } from '@/api'
import { errorMessage } from '@/services/api-error'
import { NOT_FOUND_STATUS, quietOn } from '@/services/quiet-statuses'
import { createRequestSequence } from '@/services/request-sequence'

/**
 * The whole document of the open event with its related events. While the next event loads the
 * previous one stays on show (stepping through a list would otherwise flash empty at every step),
 * and an answer for an event that is no longer open is dropped.
 */
export function useEventDetail(analysisId: () => number | undefined, eventId: () => string | null) {
  const detail = ref<EventDetail>()
  const loading = ref(false)
  const error = ref<string>()
  const status = ref<number>()
  const requests = createRequestSequence()

  const notFound = computed(() => status.value === NOT_FOUND_STATUS)

  async function reload(): Promise<void> {
    const analysis = analysisId()
    const id = eventId()
    const request = requests.next()
    if (analysis === undefined || id === null) {
      detail.value = undefined
      loading.value = false
      error.value = undefined
      status.value = undefined
      return
    }
    loading.value = true
    error.value = undefined
    status.value = undefined
    const { data, error: failure, response } = await eventsDetail({
      path: { analysis_id: analysis, event_id: id },
      meta: quietOn(NOT_FOUND_STATUS),
    })
    if (!requests.isCurrent(request)) return
    loading.value = false
    detail.value = data
    if (!data) {
      error.value = errorMessage(failure)
      status.value = response?.status
    }
  }

  watch([analysisId, eventId], () => void reload(), { immediate: true })

  return { detail, loading, error, notFound, reload }
}
