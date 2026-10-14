import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { useFilterEvents } from '@/composables/use-filter-events'
import { useQueryUrlSync } from '@/composables/use-query-url-sync'
import { useQueryStateStore } from '@/stores/query-state'

let router: Router
let store: ReturnType<typeof useQueryStateStore>
let filterEvents: ReturnType<typeof useFilterEvents>

// The page owns the URL sync, as AnalysisPage does, so these tests would catch it undoing a navigation.
async function openAt(path: string) {
  router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { render: () => null } }],
  })
  await router.push(path)
  const pinia = createPinia()
  setActivePinia(pinia)
  store = useQueryStateStore()
  const Host = defineComponent({
    setup() {
      useQueryUrlSync(() => 7)
      filterEvents = useFilterEvents()
      return () => h('div')
    },
  })
  mount(Host, { global: { plugins: [router, pinia] } })
  await flushPromises()
}

const shown = () => router.currentRoute.value

beforeEach(() => {
  filterEvents = undefined as never
})

describe('filterOnEvents', () => {
  it('adds the chip and lands on the Events tab of the same analysis with the chip in the URL', async () => {
    await openAt('/analyses/7/network')
    await filterEvents.filterOnEvents({ field: 'dns.question.name', value: 'evil.example' })
    await flushPromises()
    expect(shown().params).toEqual({ id: '7', tab: 'events' })
    expect(shown().query).toEqual({ f: ['dns.question.name:evil.example'] })
    expect(store.chips).toEqual([{ field: 'dns.question.name', value: 'evil.example', negate: false }])
  })

  it('adds every chip it is given', async () => {
    await openAt('/analyses/7/network')
    await filterEvents.filterOnEvents(
      { field: 'destination.ip', value: '203.0.113.9' },
      { field: 'destination.port', value: 443 },
    )
    await flushPromises()
    expect(shown().query).toEqual({ f: ['destination.ip:203.0.113.9', 'destination.port:443'] })
  })

  it('keeps a negation', async () => {
    await openAt('/analyses/7/artifacts')
    await filterEvents.filterOnEvents({ field: 'file.path', value: 'C:\\a.exe', negate: true })
    await flushPromises()
    expect(store.chips).toEqual([{ field: 'file.path', value: 'C:\\a.exe', negate: true }])
    expect(shown().query).toEqual({ f: ['-file.path:C:\\a.exe'] })
  })

  it('keeps what the query already holds and any other param', async () => {
    await openAt('/analyses/7/artifacts?q=lane%3Afile&f=api%3AWriteFile&pid=12&t=2026-10-13T12%3A00%3A01Z..&x=1')
    await filterEvents.filterOnEvents({ field: 'registry.key', value: 'Software\\Run' })
    await flushPromises()
    expect(shown().params.tab).toBe('events')
    expect(shown().query).toEqual({
      q: 'lane:file',
      f: ['api:WriteFile', 'registry.key:Software\\Run'],
      pid: ['12'],
      t: '2026-10-13T12:00:01Z..',
      x: '1',
    })
  })
})

describe('showProcessEvents', () => {
  it('replaces the processes the query was limited to with this one', async () => {
    await openAt('/analyses/7/network?pid=1&pid=2')
    await filterEvents.showProcessEvents(4120)
    await flushPromises()
    expect(store.pids).toEqual([4120])
    expect(shown().params.tab).toBe('events')
    expect(shown().query).toEqual({ pid: ['4120'] })
  })

  it('leaves the text and the chips alone', async () => {
    await openAt('/analyses/7/processes?q=lane%3Afile&f=api%3AWriteFile')
    await filterEvents.showProcessEvents(4120)
    await flushPromises()
    expect(shown().query).toEqual({ q: 'lane:file', f: ['api:WriteFile'], pid: ['4120'] })
  })
})

describe('showEventsMatching', () => {
  it('replaces the query text and clears nothing else', async () => {
    await openAt('/analyses/7/detections?q=old&f=api%3AWriteFile&pid=12')
    await filterEvents.showEventsMatching('event.id:(a OR b)')
    await flushPromises()
    expect(shown().params.tab).toBe('events')
    expect(shown().query).toEqual({ q: 'event.id:(a OR b)', f: ['api:WriteFile'], pid: ['12'] })
    expect(store.text).toBe('event.id:(a OR b)')
  })
})

describe('showEvent', () => {
  it('lands on the Events tab with the event open in the drawer, keeping the rest of the query', async () => {
    await openAt('/analyses/7/notes?q=process.name:cmd.exe')
    await filterEvents.showEvent('abc123')
    await flushPromises()
    expect(shown().params).toEqual({ id: '7', tab: 'events' })
    expect(shown().query).toEqual({ q: 'process.name:cmd.exe', e: 'abc123' })
    expect(store.eventId).toBe('abc123')
  })
})
