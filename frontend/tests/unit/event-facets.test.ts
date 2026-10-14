import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { facetFixture, facetsResponse } from './events-fixtures'

const eventsFacetsMock = vi.fn()
const queryFieldsMock = vi.fn()
vi.mock('@/api', () => ({
  eventsFacets: (...args: unknown[]) => eventsFacetsMock(...args),
  queryFields: (...args: unknown[]) => queryFieldsMock(...args),
}))

const { default: EventFacets } = await import('@/components/EventFacets.vue')
const { useQueryStateStore } = await import('@/stores/query-state')
const { useEventFacetsStore } = await import('@/stores/event-facets')

const FACETS = facetsResponse([
  facetFixture('process.name', [
    ['cmd.exe', 40],
    ['svchost.exe', 12],
  ]),
  facetFixture('tartarus.lane', [['file', 30]]),
  facetFixture('event.action', []),
  facetFixture('api.name', [['NtWriteFile', 9]]),
  facetFixture('destination.domain', []),
  facetFixture('rule.name', []),
])

let query: ReturnType<typeof useQueryStateStore>

async function mountPanel(open = true) {
  const pinia = createPinia()
  setActivePinia(pinia)
  query = useQueryStateStore()
  query.bindTo(7)
  const facets = useEventFacetsStore()
  facets.activate()
  const wrapper = mount(EventFacets, { props: { open }, global: { plugins: [Quasar, pinia] } })
  await flushPromises()
  return wrapper
}

const CATALOG = [
  { name: 'process.name', aliases: ['proc', 'process'] },
  { name: 'tartarus.lane', aliases: ['lane'] },
].map((entry) => ({ ...entry, type: 'keyword', description: '', example: '', lane: null, members: [], searchable: true }))

beforeEach(() => {
  queryFieldsMock.mockReset()
  queryFieldsMock.mockResolvedValue({ data: CATALOG })
  eventsFacetsMock.mockReset()
  eventsFacetsMock.mockResolvedValue({ data: FACETS, error: undefined, response: { status: 200 } })
})

describe('the panel', () => {
  it('has a group for each facet field, in order', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.findAll('.facet-group__heading').map((heading) => heading.text().replace(/\d.*/, '').trim())).toEqual([
      'PROCESS',
      'LANE',
      'ACTION',
      'API',
      'DOMAIN',
      'RULE',
    ])
  })

  it('filters on a value that is clicked, by adding a chip', async () => {
    const wrapper = await mountPanel()
    await wrapper.findAll('.facet-value__pick')[0]!.trigger('click')
    expect(query.chips).toEqual([{ field: 'process.name', value: 'cmd.exe', negate: false }])
  })

  it('filters a value out when alt-clicked', async () => {
    const wrapper = await mountPanel()
    await wrapper.findAll('.facet-value__pick')[1]!.trigger('click', { altKey: true })
    expect(query.chips).toEqual([{ field: 'process.name', value: 'svchost.exe', negate: true }])
  })

  it('removes the chip when a marked value is clicked again', async () => {
    const wrapper = await mountPanel()
    query.addChip({ field: 'process.name', value: 'cmd.exe', negate: false })
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.facet-value')[0]!.classes()).toContain('is-included')
    await wrapper.findAll('.facet-value__pick')[0]!.trigger('click')
    expect(query.chips).toEqual([])
  })

  it('turns an included value into a filter out from its minus button', async () => {
    const wrapper = await mountPanel()
    query.addChip({ field: 'process.name', value: 'cmd.exe', negate: false })
    await wrapper.vm.$nextTick()
    await wrapper.findAll('.facet-value__exclude')[0]!.trigger('click')
    expect(query.chips).toEqual([{ field: 'process.name', value: 'cmd.exe', negate: true }])
  })

  it('says when the facets could not be loaded, and asks again on retry', async () => {
    eventsFacetsMock.mockResolvedValueOnce({
      data: undefined,
      error: { error: { code: 'search_failed', message: 'search failed', details: {} } },
      response: { status: 502 },
    })
    const wrapper = await mountPanel()
    expect(wrapper.text()).toContain('search failed')
    eventsFacetsMock.mockResolvedValue({ data: FACETS, error: undefined, response: { status: 200 } })
    await wrapper.find('.event-facets__retry').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.facet-value').length).toBeGreaterThan(0)
  })
})

describe('chips typed with an alias', () => {
  it('mark the value of the field the alias stands for', async () => {
    const wrapper = await mountPanel()
    query.addChip({ field: 'proc', value: 'cmd.exe', negate: false })
    query.addChip({ field: 'lane', value: 'file', negate: true })
    await flushPromises()
    expect(wrapper.findAll('.facet-value')[0]!.classes()).toContain('is-included')
    const laneValue = wrapper.findAll('.facet-group')[1]!.find('.facet-value')
    expect(laneValue.classes()).toContain('is-excluded')
  })

  it('are removed by clicking the marked value, whatever they were typed as', async () => {
    const wrapper = await mountPanel()
    query.addChip({ field: 'proc', value: 'cmd.exe', negate: false })
    await flushPromises()
    await wrapper.findAll('.facet-value__pick')[0]!.trigger('click')
    expect(query.chips).toEqual([])
  })

  it('are turned around in place by the minus button, not duplicated', async () => {
    const wrapper = await mountPanel()
    query.addChip({ field: 'proc', value: 'cmd.exe', negate: false })
    await flushPromises()
    await wrapper.findAll('.facet-value__exclude')[0]!.trigger('click')
    expect(query.chips).toEqual([{ field: 'proc', value: 'cmd.exe', negate: true }])
  })
})

describe('collapsing', () => {
  it('shows only a strip with the expand button when collapsed', async () => {
    const wrapper = await mountPanel(false)
    expect(wrapper.find('.event-facets').classes()).toContain('is-collapsed')
    expect(wrapper.find('.facet-group').exists()).toBe(false)
    expect(wrapper.find('.event-facets__toggle').attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('.event-facets__toggle').attributes('aria-label')).toBe('Show facets')
  })

  it('asks to toggle from the button', async () => {
    const wrapper = await mountPanel()
    expect(wrapper.find('.event-facets__toggle').attributes('aria-label')).toBe('Hide facets')
    await wrapper.find('.event-facets__toggle').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })
})
