import { computed, onScopeDispose, ref, type ComputedRef } from 'vue'

const TICK_MS = 500
const MS_PER_SECOND = 1000

/** A figure the server sent, and when it arrived, so a display can count on from it between updates. */
export interface Reading {
  seconds: number | null | undefined
  /** `Date.now()` when the figure arrived. */
  receivedAt: number
}

export interface TickingOptions {
  direction: 1 | -1
  counting: () => boolean
}

/** Counts a server figure on between updates: up for elapsed time, down for time left. Never below zero. */
export function useTickingSeconds(reading: () => Reading | undefined, options: TickingOptions): ComputedRef<number | null> {
  const now = ref(Date.now())
  const ticker = setInterval(() => (now.value = Date.now()), TICK_MS)
  onScopeDispose(() => clearInterval(ticker))

  return computed(() => {
    const current = reading()
    if (current?.seconds == null) return null
    const sinceReceived = options.counting() ? Math.max(0, (now.value - current.receivedAt) / MS_PER_SECOND) : 0
    return Math.max(0, current.seconds + options.direction * sinceReceived)
  })
}
