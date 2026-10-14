import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import FilterEventsButton from '@/components/FilterEventsButton.vue'
import type { EventsTarget } from '@/services/events-filters'
import { useQueryStateStore } from '@/stores/query-state'

async function mountButton(target: EventsTarget, options: { label?: string; slot?: string } = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/analyses/:id/:tab?', name: 'analysis-workspace', component: { render: () => null } }],
  })
  await router.push('/analyses/9/network')
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useQueryStateStore()
  const wrapper = mount(FilterEventsButton, {
    props: { target, ...(options.label && { label: options.label }) },
    slots: options.slot ? { default: options.slot } : {},
    global: { plugins: [Quasar, router, pinia] },
  })
  return { wrapper, store, router }
}

describe('FilterEventsButton', () => {
  it('is an icon button labelled with what it shows events for', async () => {
    const { wrapper } = await mountButton({ chips: [{ field: 'dns.question.name', value: 'evil.example' }] })
    const button = wrapper.get('button')
    expect(button.attributes('aria-label')).toBe('Show events with dns.question.name: evil.example')
    expect(button.attributes('title')).toBe('Show events')
    expect(button.find('.q-icon').exists()).toBe(true)
  })

  it('applies the chips and opens the Events tab on click', async () => {
    const { wrapper, store, router } = await mountButton({
      chips: [
        { field: 'destination.ip', value: '1.2.3.4' },
        { field: 'destination.port', value: 443 },
      ],
    })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(store.chips.map((chip) => `${chip.field}:${chip.value}`)).toEqual(['destination.ip:1.2.3.4', 'destination.port:443'])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })

  it('limits the events to the process of a pid target', async () => {
    const { wrapper, store, router } = await mountButton({ pid: 4120 })
    expect(wrapper.get('button').attributes('aria-label')).toBe('Show events with pid: 4120')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(store.pids).toEqual([4120])
    expect(router.currentRoute.value.params.tab).toBe('events')
  })

  it('sets the query text of a text target', async () => {
    const { wrapper, store } = await mountButton({ text: 'event.id:(a OR b)' }, { label: 'the 2 triggering events' })
    expect(wrapper.get('button').attributes('aria-label')).toBe('Show events with the 2 triggering events')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(store.text).toBe('event.id:(a OR b)')
  })

  it('shows its content instead of the icon when it has some', async () => {
    const { wrapper } = await mountButton({ pid: 7 }, { slot: 'benign.exe (7)' })
    expect(wrapper.get('button').text()).toBe('benign.exe (7)')
    expect(wrapper.find('.q-icon').exists()).toBe(false)
    expect(wrapper.get('button').attributes('aria-label')).toBe('Show events with pid: 7')
  })

  it('renders nothing for chips that came out empty, so a caller needs no check of its own', async () => {
    const { wrapper } = await mountButton({ chips: [] })
    expect(wrapper.find('button').exists()).toBe(false)
  })
})
