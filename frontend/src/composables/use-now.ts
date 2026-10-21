import { onScopeDispose, ref, type Ref } from 'vue'

/** The current time in milliseconds, refreshed every `tickMs` until the scope ends. */
export function useNow(tickMs: number): Ref<number> {
  const now = ref(Date.now())
  const ticker = setInterval(() => (now.value = Date.now()), tickMs)
  onScopeDispose(() => clearInterval(ticker))
  return now
}
