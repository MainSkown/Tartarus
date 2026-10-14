import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { useAnalysisTabNavigation } from '@/composables/use-analysis-tab-navigation'

async function open(path: string) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { render: () => null } }],
  })
  await router.push(path)
  let navigation!: ReturnType<typeof useAnalysisTabNavigation>
  mount(
    defineComponent({
      setup() {
        navigation = useAnalysisTabNavigation()
        return () => h('div')
      },
    }),
    { global: { plugins: [router] } },
  )
  await flushPromises()
  return { router, navigation }
}

describe('openTab', () => {
  it('goes to the tab of the same analysis and keeps the query', async () => {
    const { router, navigation } = await open('/analyses/12/network?q=lane%3Afile&pid=3')
    await navigation.openTab('events')
    expect(router.currentRoute.value.fullPath).toBe('/analyses/12/events?q=lane:file&pid=3')
  })

  it('takes the query it is given instead of the current one', async () => {
    const { router, navigation } = await open('/analyses/12/network?q=old')
    await navigation.openTab('events', { q: 'new' })
    expect(router.currentRoute.value.fullPath).toBe('/analyses/12/events?q=new')
  })

  it('adds a history entry, so back returns to the tab it left', async () => {
    const { router, navigation } = await open('/analyses/12/network')
    await navigation.openTab('events')
    router.back()
    await flushPromises()
    expect(router.currentRoute.value.params.tab).toBe('network')
  })
})
