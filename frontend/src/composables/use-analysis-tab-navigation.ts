import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'

/** Moves between the tabs of the open analysis; the query params (`q`, `f`, `pid`, `t`...) go along unless another query is given. */
export function useAnalysisTabNavigation() {
  const route = useRoute()
  const router = useRouter()

  async function openTab(tab: string, query: LocationQueryRaw = route.query): Promise<void> {
    await router.push({ name: 'analysis-workspace', params: { id: String(route.params.id), tab }, query })
  }

  return { openTab }
}
