import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { FACET_PANEL_STORAGE_KEY } from '@/composables/use-facet-panel'
import { analysisWithStatus } from './analysis-fixtures'
import { eventDetail, eventFixture, eventList, eventPage, facetFixture, facetsResponse } from './events-fixtures'

const eventsSearchMock = vi.fn()
const eventsFacetsMock = vi.fn()
const eventsDetailMock = vi.fn()
vi.mock('@/api', () => ({
  eventsSearch: (...args: unknown[]) => eventsSearchMock(...args),
  eventsFacets: (...args: unknown[]) => eventsFacetsMock(...args),
  eventsDetail: (...args: unknown[]) => eventsDetailMock(...args),
  queryFields: vi.fn().mockResolvedValue({ data: [] }),
}))

const { default: EventsTab } = await import('@/components/tabs/EventsTab.vue')
const { useQueryStateStore } = await import('@/stores/query-state')

const QDialogStub = defineComponent({
  props: { modelValue: Boolean },
  setup(props, { slots }) {
    return () => h('div', { class: 'dialog-stub' }, props.modelValue ? slots.default?.() : [])
  },
})

let query: ReturnType<typeof useQueryStateStore>

async function mountTab(warnings?: string[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  query = useQueryStateStore()
  query.bindTo(45)
  const wrapper = mount(EventsTab, {
    attachTo: document.body,
    props: { analysis: analysisWithStatus('done', warnings ? { summary: { warnings } } : {}) },
    global: { plugins: [Quasar, pinia], stubs: { QDialog: QDialogStub } },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  document.body.innerHTML = ''
  eventsSearchMock.mockReset()
  eventsSearchMock.mockResolvedValue({ data: eventPage(eventList(5), { total: 5 }), response: { status: 200 } })
  eventsFacetsMock.mockReset()
  eventsFacetsMock.mockResolvedValue({ data: facetsResponse([facetFixture('process.name', [['cmd.exe', 5]])]), response: { status: 200 } })
  eventsDetailMock.mockReset()
  eventsDetailMock.mockImplementation(async ({ path }: { path: { event_id: string } }) => ({
    data: eventDetail(eventFixture({ id: path.event_id })),
    response: { status: 200 },
  }))
})

afterEach(() => window.localStorage.clear())

describe('EventsTab', () => {
  it('has its marker, the facet panel and the table', async () => {
    const wrapper = await mountTab()
    expect(wrapper.attributes('data-tab')).toBe('events')
    expect(wrapper.find('.event-facets').exists()).toBe(true)
    expect(wrapper.find('.event-table').exists()).toBe(true)
  })

  it('says above the table what the ingest warned about, so a missing Sysmon lane is explained where it is looked at', async () => {
    const warning = 'Sysmon events were not exported: the guest did not answer within 120 s'
    const wrapper = await mountTab([warning])
    expect(wrapper.find('.analysis-warnings .live-notice__text').text()).toBe(warning)
    expect(wrapper.find('.events-tab__main').element.firstElementChild).toBe(wrapper.find('.analysis-warnings').element)
  })

  it('has no notice when the analysis has no warnings', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('.analysis-warnings').exists()).toBe(false)
  })

  it('loads the events and the facets of the analysis', async () => {
    const wrapper = await mountTab()
    expect(eventsSearchMock.mock.calls[0]![0].path).toEqual({ analysis_id: 45 })
    expect(eventsFacetsMock.mock.calls[0]![0].path).toEqual({ analysis_id: 45 })
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(5)
    expect(wrapper.find('.facet-value__name').text()).toBe('cmd.exe')
  })

  it('stops following the filter once it is gone, so another tab does not pay for it', async () => {
    const wrapper = await mountTab()
    wrapper.unmount()
    query.setText('x')
    await new Promise((resolve) => setTimeout(resolve, 80))
    expect(eventsSearchMock).toHaveBeenCalledTimes(1)
    expect(eventsFacetsMock).toHaveBeenCalledTimes(1)
  })

  it('asks again when the shared filter changes', async () => {
    await mountTab()
    query.setText('lane:file')
    await new Promise((resolve) => setTimeout(resolve, 80))
    await flushPromises()
    expect(eventsSearchMock).toHaveBeenCalledTimes(2)
    expect(eventsSearchMock.mock.lastCall![0].body.query).toBe('lane:file')
  })

  it('asks again with the other sort when the time header is clicked', async () => {
    const wrapper = await mountTab()
    await wrapper.find('.event-table__sort').trigger('click')
    await new Promise((resolve) => setTimeout(resolve, 80))
    expect(eventsSearchMock.mock.lastCall![0].body.sort).toBe('-@timestamp')
  })
})

describe('choosing a row', () => {
  it('opens the event in the drawer by naming it in the shared state', async () => {
    const wrapper = await mountTab()
    await wrapper.find('[data-event-id="e3"]').trigger('click')
    await flushPromises()
    expect(query.eventId).toBe('e3')
    expect(wrapper.find('[data-event-id="e3"]').classes()).toContain('is-selected')
    expect(wrapper.find('.event-detail').exists()).toBe(true)
  })

  it('selects with the arrow keys without opening the drawer', async () => {
    const wrapper = await mountTab()
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.find('[data-event-id="e1"]').classes()).toContain('is-selected')
    expect(query.eventId).toBeNull()
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'Enter' })
    expect(query.eventId).toBe('e1')
  })

  it('follows the selection with the drawer once it is open', async () => {
    const wrapper = await mountTab()
    await wrapper.find('[data-event-id="e1"]').trigger('click')
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowDown' })
    expect(query.eventId).toBe('e2')
  })

  it('highlights the row of an event opened from elsewhere, such as the URL', async () => {
    const wrapper = await mountTab()
    query.openEvent('e4')
    await flushPromises()
    expect(wrapper.find('[data-event-id="e4"]').classes()).toContain('is-selected')
  })
})

describe('the empty states', () => {
  it('says there are no events for an analysis with none', async () => {
    eventsSearchMock.mockResolvedValue({ data: eventPage([]), response: { status: 200 } })
    const wrapper = await mountTab()
    expect(wrapper.text()).toContain('no events')
    expect(wrapper.find('.event-table__clear').exists()).toBe(false)
  })

  it('clears the query and the chips from the empty result', async () => {
    eventsSearchMock.mockResolvedValueOnce({ data: eventPage(eventList(5), { total: 5 }), response: { status: 200 } })
    const wrapper = await mountTab()
    eventsSearchMock.mockResolvedValue({ data: eventPage([]), response: { status: 200 } })
    query.setText('lane:file')
    query.addChip({ field: 'process.name', value: 'x.exe', negate: false })
    await new Promise((resolve) => setTimeout(resolve, 80))
    await flushPromises()
    expect(wrapper.text()).toContain('no event matches this query')
    await wrapper.find('.event-table__clear').trigger('click')
    expect(query.isEmpty).toBe(true)
  })

  it('shows the error with a retry that asks again', async () => {
    eventsSearchMock.mockResolvedValueOnce({
      data: undefined,
      error: { error: { code: 'search_timeout', message: 'the search took too long', details: {} } },
      response: { status: 504 },
    })
    const wrapper = await mountTab()
    expect(wrapper.text()).toContain('the search took too long')
    await wrapper.find('button.retry-btn').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(5)
  })
})

describe('the facet panel', () => {
  it('starts open and is remembered closed', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('.event-facets').classes()).not.toContain('is-collapsed')
    await wrapper.find('.event-facets__toggle').trigger('click')
    expect(wrapper.find('.event-facets').classes()).toContain('is-collapsed')
    expect(window.localStorage.getItem(FACET_PANEL_STORAGE_KEY)).toBe('false')
  })
})
