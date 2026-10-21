import { computed, type ComputedRef } from 'vue'
import { useNow } from '@/composables/use-now'
import { ACTIVITY_TICK_MS, activityAgeSeconds, activityNotice, type ActivityNotice } from '@/services/build-activity'

/** How long ago the running step last did anything, counted on each second between two answers of the server. */
export function useActivityAge(lastActivity: () => string | null | undefined): ComputedRef<ActivityNotice | undefined> {
  const now = useNow(ACTIVITY_TICK_MS)

  return computed(() => {
    const age = activityAgeSeconds(lastActivity(), now.value)
    return age === undefined ? undefined : activityNotice(age)
  })
}
