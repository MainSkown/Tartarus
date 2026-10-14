import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { useQueryStateStore } from '@/stores/query-state'

/** What a component with a "show events" action needs around it: Quasar, a router on an analysis tab, a Pinia with the shared query. */
export async function filterEventsPlugins(startAt = '/analyses/45/network') {
  const router: Router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { render: () => null } }],
  })
  await router.push(startAt)
  const pinia = createPinia()
  setActivePinia(pinia)
  return { plugins: [Quasar, router, pinia], router, query: useQueryStateStore() }
}
