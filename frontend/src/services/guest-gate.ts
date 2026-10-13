import { computed, type ComputedRef } from 'vue'
import { useSystemStore } from '@/stores/system'

/** Why nothing can be submitted right now; `undefined` once the analysis guest is ready. */
export function useGuestBlockReason(): ComputedRef<string | undefined> {
  const system = useSystemStore()
  return computed(() => (system.guestReady ? undefined : (system.guestMessage ?? 'checking guest status…')))
}
