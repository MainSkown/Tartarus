import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { useQueryUrlSync } from '@/composables/use-query-url-sync'
import { useQueryStateStore } from '@/stores/query-state'

let router: Router
let store: ReturnType<typeof useQueryStateStore>
const analysisId = ref<number | undefined>(7)

async function mountSync(initial = '/analyses/7/events') {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/analyses/:id/:tab?', component: { render: () => null } }],
  })
  await router.push(initial)
  const pinia = createPinia()
  setActivePinia(pinia)
  store = useQueryStateStore()
  const Host = defineComponent({
    setup() {
      useQueryUrlSync(() => analysisId.value)
      return () => h('div')
    },
  })
  const wrapper = mount(Host, { global: { plugins: [router, pinia] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  analysisId.value = 7
})

describe('reading the route', () => {
  it('fills the store from the route query on mount', async () => {
    await mountSync('/analyses/7/events?q=lane%3Afile&f=-api%3ANtDelayExecution&pid=4120&t=2026-10-13T12%3A00%3A01Z..')
    expect(store.urlState).toEqual({
      text: 'lane:file',
      chips: [{ field: 'api', value: 'NtDelayExecution', negate: true }],
      pids: [4120],
      timeRange: { from: '2026-10-13T12:00:01Z', to: null },
    })
  })

  it('binds the store to the analysis of the page', async () => {
    await mountSync()
    expect(store.analysisId).toBe(7)
  })

  it('does not write to the route just because it read from it', async () => {
    const wrapper = await mountSync('/analyses/7/events?q=lane%3Afile&junk=1')
    const push = vi.spyOn(router, 'push')
    const replace = vi.spyOn(router, 'replace')
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    expect(replace).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('follows the route when it changes by back and forward', async () => {
    await mountSync('/analyses/7/events?q=one')
    store.setText('two')
    await flushPromises()
    expect(router.currentRoute.value.query.q).toBe('two')

    router.back()
    await flushPromises()
    expect(store.text).toBe('one')

    router.forward()
    await flushPromises()
    expect(store.text).toBe('two')
  })

  it('empties the store when the route loses its query', async () => {
    await mountSync('/analyses/7/events?q=one&pid=3')
    await router.push('/analyses/7/events')
    await flushPromises()
    expect(store.isEmpty).toBe(true)
  })

  it('survives a query it cannot read', async () => {
    await mountSync('/analyses/7/events?pid=abc&f=nocolon&t=zzz')
    expect(store.isEmpty).toBe(true)
  })
})

describe('writing the route', () => {
  it('pushes a history entry when the applied text changes', async () => {
    await mountSync()
    const push = vi.spyOn(router, 'push')
    const replace = vi.spyOn(router, 'replace')
    store.setText('process.name:cmd.exe')
    await flushPromises()
    expect(push).toHaveBeenCalledTimes(1)
    expect(replace).not.toHaveBeenCalled()
    expect(router.currentRoute.value.query).toEqual({ q: 'process.name:cmd.exe' })
  })

  it('replaces the entry when a chip changes', async () => {
    await mountSync()
    const push = vi.spyOn(router, 'push')
    const replace = vi.spyOn(router, 'replace')
    store.addChip({ field: 'lane', value: 'file', negate: false })
    await flushPromises()
    expect(replace).toHaveBeenCalledTimes(1)
    expect(push).not.toHaveBeenCalled()
    expect(router.currentRoute.value.query).toEqual({ f: ['lane:file'] })
  })

  it('replaces the entry for a pid and for a time range', async () => {
    await mountSync()
    const push = vi.spyOn(router, 'push')
    store.togglePid(4120)
    await flushPromises()
    store.setTimeRange({ from: '2026-10-13T12:00:01Z', to: '2026-10-13T12:00:04Z' })
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    expect(router.currentRoute.value.query).toEqual({
      pid: ['4120'],
      t: '2026-10-13T12:00:01Z..2026-10-13T12:00:04Z',
    })
  })

  it('writes one navigation for a change that touches several parts at once', async () => {
    await mountSync()
    const push = vi.spyOn(router, 'push')
    const replace = vi.spyOn(router, 'replace')
    store.setText('a')
    store.addChip({ field: 'lane', value: 'file', negate: false })
    await flushPromises()
    expect(push.mock.calls.length + replace.mock.calls.length).toBe(1)
  })

  it('keeps the params that are not its own and the tab', async () => {
    await mountSync('/analyses/7/events?other=1&other=2')
    store.setText('x')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/analyses/7/events')
    expect(router.currentRoute.value.query).toEqual({ other: ['1', '2'], q: 'x' })
  })

  it('removes a param when its part is emptied', async () => {
    await mountSync('/analyses/7/events?q=x&f=lane%3Afile')
    store.removeChip(0)
    store.setText('')
    await flushPromises()
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('does not loop: one change is one navigation', async () => {
    await mountSync()
    const push = vi.spyOn(router, 'push')
    const replace = vi.spyOn(router, 'replace')
    store.setText('x')
    await flushPromises()
    await flushPromises()
    expect(push.mock.calls.length + replace.mock.calls.length).toBe(1)
  })
})

describe('changing analysis', () => {
  it('starts from the new route when the analysis changes', async () => {
    await mountSync('/analyses/7/events?q=old')
    analysisId.value = 8
    await router.push('/analyses/8/events?q=new')
    await flushPromises()
    expect(store.analysisId).toBe(8)
    expect(store.text).toBe('new')
  })

  it('empties the store for a new analysis opened without a query', async () => {
    await mountSync('/analyses/7/events?q=old&pid=3')
    analysisId.value = 8
    await router.push('/analyses/8/events')
    await flushPromises()
    expect(store.isEmpty).toBe(true)
  })
})
