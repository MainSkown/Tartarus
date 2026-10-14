import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { eventDetail, eventFixture, eventList, eventPage } from './events-fixtures'

const eventsDetailMock = vi.fn()
const eventsSearchMock = vi.fn()
vi.mock('@/api', () => ({
  eventsDetail: (...args: unknown[]) => eventsDetailMock(...args),
  eventsSearch: (...args: unknown[]) => eventsSearchMock(...args),
  queryFields: vi.fn().mockResolvedValue({ data: [] }),
}))

const { default: EventDetailDrawer } = await import('@/components/EventDetailDrawer.vue')
const { useQueryStateStore } = await import('@/stores/query-state')
const { useEventsStore } = await import('@/stores/events')
const { useAnalysesStore } = await import('@/stores/analyses')
const { default: TargetAnnotations } = await import('@/components/TargetAnnotations.vue')
const { analysisWithStatus } = await import('./analysis-fixtures')

// QDialog teleports its content out of the wrapper; a pass-through keeps it queryable and lets the test see what it was bound to.
const QDialogStub = defineComponent({
  props: { modelValue: Boolean },
  emits: ['update:modelValue'],
  setup(props, { slots, emit }) {
    return () => h('div', { class: 'dialog-stub', 'data-open': String(props.modelValue), onHide: () => emit('update:modelValue', false) }, props.modelValue ? slots.default?.() : [])
  },
})

let query: ReturnType<typeof useQueryStateStore>
let events: ReturnType<typeof useEventsStore>

async function mountDrawer(openId: string | null = null) {
  const pinia = createPinia()
  setActivePinia(pinia)
  query = useQueryStateStore()
  events = useEventsStore()
  query.bindTo(7)
  events.activate()
  await flushPromises()
  if (openId) query.openEvent(openId)
  const wrapper = mount(EventDetailDrawer, { global: { plugins: [Quasar, pinia], stubs: { QDialog: QDialogStub } } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  eventsDetailMock.mockReset()
  eventsDetailMock.mockImplementation(async ({ path }: { path: { event_id: string } }) => ({
    data: eventDetail(eventFixture({ id: path.event_id, summary: `detail of ${path.event_id}` })),
    response: { status: 200 },
  }))
  eventsSearchMock.mockReset()
  eventsSearchMock.mockResolvedValue({ data: eventPage(eventList(3), { total: 5, next_cursor: 'c1' }), response: { status: 200 } })
})

describe('EventDetailDrawer', () => {
  it('is closed while no event is open', async () => {
    const wrapper = await mountDrawer()
    expect(wrapper.find('.dialog-stub').attributes('data-open')).toBe('false')
    expect(eventsDetailMock).not.toHaveBeenCalled()
  })

  it('opens the event named by the shared state and shows its detail', async () => {
    const wrapper = await mountDrawer('e2')
    expect(wrapper.find('.dialog-stub').attributes('data-open')).toBe('true')
    expect(eventsDetailMock.mock.calls[0]![0].path).toEqual({ analysis_id: 7, event_id: 'e2' })
    expect(wrapper.find('.event-detail__title').text()).toContain('detail of e2')
  })

  it('lets the analyst annotate the event of a finished analysis', async () => {
    const wrapper = await mountDrawer('e2')
    useAnalysesStore().current = analysisWithStatus('done', { id: 7 })
    await flushPromises()
    expect(wrapper.findComponent(TargetAnnotations).props('editable')).toBe(true)
  })

  it.each(['running', 'ingesting'] as const)('does not while the analysis is %s', async (status) => {
    const wrapper = await mountDrawer('e2')
    useAnalysesStore().current = analysisWithStatus(status, { id: 7 })
    await flushPromises()
    expect(wrapper.findComponent(TargetAnnotations).props('editable')).toBe(false)
  })

  it('closes by closing the event in the shared state', async () => {
    const wrapper = await mountDrawer('e2')
    await wrapper.find('[aria-label="Close event"]').trigger('click')
    expect(query.eventId).toBeNull()
  })

  it('moves to the next event of the table list', async () => {
    const wrapper = await mountDrawer('e2')
    await wrapper.find('[aria-label="Next event"]').trigger('click')
    await flushPromises()
    expect(query.eventId).toBe('e3')
    await wrapper.find('[aria-label="Previous event"]').trigger('click')
    await flushPromises()
    expect(query.eventId).toBe('e2')
  })

  it('loads the next page of the table when stepping past the last event it has', async () => {
    const wrapper = await mountDrawer('e3')
    eventsSearchMock.mockResolvedValueOnce({ data: eventPage(eventList(2, 4), { total: 5, next_cursor: null }), response: { status: 200 } })
    await wrapper.find('[aria-label="Next event"]').trigger('click')
    await flushPromises()
    expect(query.eventId).toBe('e4')
  })

  it('disables the arrows at the ends of the list, and for an event that is not in it', async () => {
    const first = await mountDrawer('e1')
    expect(first.find('[aria-label="Previous event"]').attributes('disabled')).toBeDefined()
    expect(first.find('[aria-label="Next event"]').attributes('disabled')).toBeUndefined()
    const elsewhere = await mountDrawer('elsewhere')
    expect(elsewhere.find('[aria-label="Previous event"]').attributes('disabled')).toBeDefined()
    expect(elsewhere.find('[aria-label="Next event"]').attributes('disabled')).toBeDefined()
  })

  it('opens a related event, which replaces the open one', async () => {
    eventsDetailMock.mockImplementation(async ({ path }: { path: { event_id: string } }) => ({
      data: eventDetail(eventFixture({ id: path.event_id }), {
        related: { references: { items: [eventFixture({ id: 'r1' })], total: 1 }, referenced_by: { items: [], total: 0 } },
      }),
      response: { status: 200 },
    }))
    const wrapper = await mountDrawer('e2')
    await wrapper.find('.related-event').trigger('click')
    expect(query.eventId).toBe('r1')
  })

  it('says the event is gone for a 404, and retries after an error', async () => {
    eventsDetailMock.mockResolvedValueOnce({ data: undefined, error: { error: { code: 'not_found', message: 'gone', details: {} } }, response: { status: 404 } })
    const gone = await mountDrawer('e2')
    expect(gone.text()).toContain('event not found')

    eventsDetailMock.mockResolvedValueOnce({ data: undefined, error: { error: { code: 'x', message: 'search failed', details: {} } }, response: { status: 502 } })
    const broken = await mountDrawer('e2')
    expect(broken.text()).toContain('failed to load: search failed')
    await broken.find('button.retry-btn').trigger('click')
    await flushPromises()
    expect(broken.find('.event-detail__title').text()).toContain('detail of e2')
  })
})
