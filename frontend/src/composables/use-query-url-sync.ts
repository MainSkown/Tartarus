import { computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { decodeQueryState, encodeQueryState, withQueryState, type QueryUrlState } from '@/services/query-url'
import { useQueryStateStore } from '@/stores/query-state'

const signatureOf = (state: QueryUrlState): string => JSON.stringify(encodeQueryState(state))

/**
 * Keeps the shared query state and the URL query (`q`, `f`, `pid`, `t`) the same thing: the route
 * fills the store when the page opens and on back and forward, and a store change is written
 * back, as a new history entry when the applied text changed and in place for chips, pids and
 * the time range. Each side acts only when the other differs, which is what stops a loop.
 */
export function useQueryUrlSync(analysisId: () => number | undefined): void {
  const route = useRoute()
  const router = useRouter()
  const store = useQueryStateStore()

  const storeSignature = computed(() => signatureOf(store.urlState))
  const routeSignature = computed(() => signatureOf(decodeQueryState(route.query)))

  function readRoute(): void {
    store.restore(decodeQueryState(route.query))
  }

  function bindToAnalysisAndReadRoute(): void {
    store.bindTo(analysisId())
    readRoute()
  }

  function writeRoute(): void {
    const textChanged = decodeQueryState(route.query).text !== store.text
    const location = { query: withQueryState(route.query, store.urlState) }
    void (textChanged ? router.push(location) : router.replace(location))
  }

  bindToAnalysisAndReadRoute()
  watch(analysisId, bindToAnalysisAndReadRoute)
  watch(routeSignature, (signature) => {
    if (signature !== storeSignature.value) readRoute()
  })
  watch(storeSignature, (signature) => {
    if (signature !== routeSignature.value) writeRoute()
  })
}
