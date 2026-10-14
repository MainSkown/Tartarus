import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import type { Histogram, HistogramDetection } from '@/api'
import Timeline from '@/components/Timeline.vue'
import { spanToQueryRange } from '@/services/timeline-brush'
import { analysisWithStatus } from './analysis-fixtures'
import { eventDetail, eventFixture, eventList, eventPage } from './events-fixtures'

const eventsSearchMock = vi.fn()
const eventsHistogramMock = vi.fn()
const eventsDetailMock = vi.fn()
vi.mock('@/api', () => ({
  eventsSearch: (...args: unknown[]) => eventsSearchMock(...args),
  eventsHistogram: (...args: unknown[]) => eventsHistogramMock(...args),
  eventsDetail: (...args: unknown[]) => eventsDetailMock(...args),
  queryFields: vi.fn().mockResolvedValue({ data: [] }),
}))

const { default: TimelineTab } = await import('@/components/tabs/TimelineTab.vue')
const { useQueryStateStore } = await import('@/stores/query-state')
const { useEventsStore } = await import('@/stores/events')
const { useTimelineStore, TIMELINE_DEBOUNCE_MS } = await import('@/stores/timeline')

const QDialogStub = defineComponent({
  props: { modelValue: Boolean },
  setup(props, { slots }) {
    return () => h('div', { class: 'dialog-stub' }, props.modelValue ? slots.default?.() : [])
  },
})

const FIRST = Date.parse('2026-10-13T15:39:34.123Z')
const LAST = Date.parse('2026-10-13T15:40:34.123Z')
const iso = (ms: number): string => new Date(ms).toISOString()
const ok = <T>(data: T) => ({ data, error: undefined, response: { status: 200 } })
const failure = (status: number, message: string) => ({ data: undefined, error: { error: { code: 'search_timeout', message, details: {} } }, response: { status } })

function histogram(overrides: Partial<Histogram> = {}): Histogram {
  return { interval_ms: 1000, from: iso(FIRST), to: iso(LAST), total: 5, buckets: [], detections: [], ...overrides }
}

function detection(id: string): HistogramDetection {
  return { id, time: iso(FIRST + 2000), name: id, severity: 'high', ruleset: 'cape' }
}

let query: ReturnType<typeof useQueryStateStore>
let events: ReturnType<typeof useEventsStore>
let timeline: ReturnType<typeof useTimelineStore>

async function settle() {
  await vi.advanceTimersByTimeAsync(0)
}

async function pause() {
  await vi.advanceTimersByTimeAsync(TIMELINE_DEBOUNCE_MS + 1)
}

async function mountTab() {
  const pinia = createPinia()
  setActivePinia(pinia)
  query = useQueryStateStore()
  events = useEventsStore()
  timeline = useTimelineStore()
  query.bindTo(45)
  const wrapper = mount(TimelineTab, {
    attachTo: document.body,
    props: { analysis: analysisWithStatus('done') },
    global: { plugins: [Quasar, pinia], stubs: { QDialog: QDialogStub } },
  })
  await settle()
  return wrapper
}

const TABLE_PAGE_SIZE = 100

/** The searches the events table made, as opposed to the canvas loading its own events (a larger page). */
function searchBodies(): Record<string, unknown>[] {
  return eventsSearchMock.mock.calls.map(([call]) => call.body).filter((body) => body.size === TABLE_PAGE_SIZE)
}

beforeEach(() => {
  vi.useFakeTimers()
  document.body.innerHTML = ''
  eventsSearchMock.mockReset()
  eventsSearchMock.mockResolvedValue(ok(eventPage(eventList(5), { total: 5 })))
  eventsHistogramMock.mockReset()
  eventsHistogramMock.mockImplementation(async () => ok(histogram()))
  eventsDetailMock.mockReset()
  eventsDetailMock.mockImplementation(async ({ path }: { path: { event_id: string } }) => ok(eventDetail(eventFixture({ id: path.event_id }))))
})

afterEach(() => {
  vi.useRealTimers()
  window.localStorage.clear()
})

describe('the Timeline tab', () => {
  it('has its marker, a zoom toolbar, the canvas and the events table', async () => {
    const wrapper = await mountTab()
    expect(wrapper.attributes('data-tab')).toBe('timeline')
    expect(wrapper.find('.timeline-tab__toolbar').exists()).toBe(true)
    expect(wrapper.findComponent(Timeline).exists()).toBe(true)
    expect(wrapper.find('.event-table').exists()).toBe(true)
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(5)
  })

  it('has no facet panel: the query bar above is the filter', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('.event-facets').exists()).toBe(false)
  })

  it('shows the whole range, in UTC, as the visible range', async () => {
    const wrapper = await mountTab()
    expect(wrapper.find('.timeline-tab__range').text()).toMatch(/^2026-10-13 15:39:\d\d\.\d{3} - 15:40:\d\d\.\d{3} UTC · 1m /)
  })

  it('stops following things once it is gone', async () => {
    const wrapper = await mountTab()
    wrapper.unmount()
    eventsHistogramMock.mockClear()
    eventsSearchMock.mockClear()
    query.setText('x')
    await vi.advanceTimersByTimeAsync(300)
    expect(eventsHistogramMock).not.toHaveBeenCalled()
    expect(eventsSearchMock).not.toHaveBeenCalled()
  })
})

describe('the zoom radio', () => {
  it('offers FIT, 1M, 10S and 1S, with fit checked at first', async () => {
    const wrapper = await mountTab()
    const labels = wrapper.findAll('.timeline-tab__zoom .radio-label').map((label) => label.text())
    expect(labels).toEqual(['FIT', '1M', '10S', '1S'])
    const checked = wrapper.findAll<HTMLInputElement>('.timeline-tab__zoom input').map((input) => input.element.checked)
    expect(checked).toEqual([true, false, false, false])
  })

  it('zooms to the preset, centred on the current view, and shows it as the visible range', async () => {
    const wrapper = await mountTab()
    await wrapper.find('input[value="10s"]').setValue(true)
    expect(timeline.view!.end - timeline.view!.start).toBe(10_000)
    expect(timeline.preset).toBe('10s')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.timeline-tab__range').text()).toContain('10.0 s')
    expect(wrapper.find<HTMLInputElement>('input[value="10s"]').element.checked).toBe(true)
  })

  it('centres the preset on the selected event when there is one', async () => {
    const wrapper = await mountTab()
    query.openEvent('e3')
    await settle()
    await wrapper.find('input[value="1s"]').setValue(true)
    const e3 = Date.parse(eventList(5)[2]!.time)
    expect((timeline.view!.start + timeline.view!.end) / 2).toBeCloseTo(e3, 0)
  })

  it('goes back to the whole range with FIT', async () => {
    const wrapper = await mountTab()
    await wrapper.find('input[value="1s"]').setValue(true)
    await wrapper.find('input[value="fit"]').setValue(true)
    expect(timeline.preset).toBe('fit')
  })

  it('has none checked for a range made with the wheel', async () => {
    const wrapper = await mountTab()
    timeline.zoomAt(FIRST + 5000, 0.37)
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll<HTMLInputElement>('.timeline-tab__zoom input').some((input) => input.element.checked)).toBe(false)
  })
})

describe('the table below', () => {
  it('lists everything at the fit view, with no range of its own', async () => {
    await mountTab()
    expect(searchBodies().every((body) => body.time_range === undefined)).toBe(true)
  })

  it('is restricted to the visible range once zoomed, after the pause', async () => {
    const wrapper = await mountTab()
    await wrapper.find('input[value="10s"]').setValue(true)
    await pause()
    await vi.advanceTimersByTimeAsync(100)
    const last = searchBodies().at(-1)!
    expect(last.time_range).toEqual({ from: iso(Math.floor(timeline.view!.start)), to: iso(Math.ceil(timeline.view!.end)) })
  })

  it('is cut down to the time-range chip too', async () => {
    const wrapper = await mountTab()
    query.setTimeRange({ from: iso(FIRST + 20_000), to: iso(FIRST + 50_000) })
    await wrapper.find('input[value="10s"]').setValue(true)
    timeline.setView({ start: FIRST + 15_000, end: FIRST + 25_000 })
    await pause()
    await vi.advanceTimersByTimeAsync(100)
    expect(searchBodies().at(-1)!.time_range).toEqual({ from: iso(FIRST + 20_000), to: iso(FIRST + 25_000) })
  })

  it('is left alone, without a range of its own, once the tab is left: the Events tab lists everything again', async () => {
    const wrapper = await mountTab()
    timeline.setView({ start: FIRST + 15_000, end: FIRST + 25_000 })
    await pause()
    await vi.advanceTimersByTimeAsync(100)
    wrapper.unmount()
    eventsSearchMock.mockClear()
    events.activate()
    await settle()
    expect(searchBodies().at(-1)!.time_range).toBeUndefined()
  })

  it('says it is filtered when the range narrows it, so an empty list offers to clear it', async () => {
    eventsSearchMock.mockResolvedValue(ok(eventPage([], { total: 0 })))
    const wrapper = await mountTab()
    timeline.setView({ start: FIRST + 15_000, end: FIRST + 25_000 })
    await pause()
    await vi.advanceTimersByTimeAsync(100)
    expect(wrapper.text()).toContain('no event matches this query')
  })
})

describe('what the canvas is given', () => {
  it('is the view, the full range, the chip as a span and the data', async () => {
    const wrapper = await mountTab()
    query.setTimeRange({ from: iso(FIRST + 5000), to: iso(FIRST + 9000) })
    await settle()
    const canvas = wrapper.findComponent(Timeline)
    expect(canvas.props('chip')).toEqual({ start: FIRST + 5000, end: FIRST + 9000 })
    expect(canvas.props('full')).toEqual(timeline.full)
    expect(canvas.props('view')).toEqual(timeline.view)
    expect(canvas.props('data')).toMatchObject({ mode: 'events' })
  })

  it('has no chip when there is no time-range chip', async () => {
    const wrapper = await mountTab()
    expect(wrapper.findComponent(Timeline).props('chip')).toBeNull()
  })

  it('draws the detections of the histogram', async () => {
    eventsHistogramMock.mockImplementation(async () => ok(histogram({ detections: [detection('d1')] })))
    const wrapper = await mountTab()
    expect(wrapper.findComponent(Timeline).props('data')).toMatchObject({ detections: [{ id: 'd1' }] })
  })
})

describe('what the canvas asks for', () => {
  it('opens an event in the drawer and selects it', async () => {
    const wrapper = await mountTab()
    wrapper.findComponent(Timeline).vm.$emit('open-event', 'e2')
    await settle()
    expect(query.eventId).toBe('e2')
    expect(wrapper.find('[data-event-id="e2"]').classes()).toContain('is-selected')
    expect(wrapper.findComponent(Timeline).props('selectedId')).toBe('e2')
  })

  it('sets the time-range chip from a brushed range', async () => {
    const wrapper = await mountTab()
    const span = { start: FIRST + 5000, end: FIRST + 9000 }
    wrapper.findComponent(Timeline).vm.$emit('select-range', span)
    expect(query.timeRange).toEqual(spanToQueryRange(span))
  })

  it('clears the time-range chip', async () => {
    const wrapper = await mountTab()
    query.setTimeRange({ from: iso(FIRST), to: iso(FIRST + 1000) })
    wrapper.findComponent(Timeline).vm.$emit('clear-range')
    expect(query.timeRange).toBeNull()
  })

  it('moves the view for a navigation', async () => {
    const wrapper = await mountTab()
    wrapper.findComponent(Timeline).vm.$emit('navigate', { kind: 'view', span: { start: FIRST + 1000, end: FIRST + 3000 } })
    expect(timeline.view).toEqual({ start: FIRST + 1000, end: FIRST + 3000 })
    wrapper.findComponent(Timeline).vm.$emit('navigate', { kind: 'fit' })
    expect(timeline.preset).toBe('fit')
  })
})

describe('selecting a row of the table', () => {
  it('selects the event on the canvas without moving the view when it is in view', async () => {
    const wrapper = await mountTab()
    timeline.setView({ start: FIRST, end: FIRST + 10_000 })
    const view = timeline.view
    await wrapper.find('[data-event-id="e3"]').trigger('click')
    await settle()
    expect(wrapper.findComponent(Timeline).props('selectedId')).toBe('e3')
    expect(wrapper.findComponent(Timeline).props('selectedTime')).toBe(Date.parse(eventList(5)[2]!.time))
    expect(timeline.view).toEqual(view)
  })

  it('brings an event that is out of view into view', async () => {
    const wrapper = await mountTab()
    timeline.setView({ start: FIRST + 30_000, end: FIRST + 32_000 })
    await wrapper.find('[data-event-id="e3"]').trigger('click')
    await settle()
    const e3 = Date.parse(eventList(5)[2]!.time)
    expect((timeline.view!.start + timeline.view!.end) / 2).toBe(e3)
  })
})

describe('states', () => {
  it('shows the loader in the canvas box while the range loads, and the table loads on its own', async () => {
    eventsHistogramMock.mockReturnValue(new Promise(() => undefined))
    const wrapper = await mountTab()
    expect(wrapper.find('.timeline-tab__canvas .loader').exists()).toBe(true)
    expect(wrapper.findComponent(Timeline).exists()).toBe(false)
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(5)
  })

  it('says there are no events for an analysis with none', async () => {
    eventsHistogramMock.mockResolvedValue(ok(histogram({ from: null, to: null, total: 0 })))
    eventsSearchMock.mockResolvedValue(ok(eventPage([])))
    const wrapper = await mountTab()
    expect(wrapper.find('.timeline-tab__canvas').text()).toContain('> no events in this analysis')
    expect(wrapper.find('.timeline-tab__range').text()).toBe('')
  })

  it('says the histogram failed, with a retry, while the table is unaffected', async () => {
    eventsHistogramMock.mockResolvedValueOnce(failure(504, 'the search took too long'))
    const wrapper = await mountTab()
    expect(wrapper.find('.timeline-tab__canvas').text()).toContain('failed to load: the search took too long')
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(5)
    eventsHistogramMock.mockImplementation(async () => ok(histogram()))
    await wrapper.find('.timeline-tab__canvas .retry-btn').trigger('click')
    await settle()
    expect(wrapper.findComponent(Timeline).exists()).toBe(true)
  })

  it('says the table failed, with a retry, while the canvas is unaffected', async () => {
    eventsSearchMock.mockImplementation(async ({ body }: { body: { size: number } }) =>
      body.size === TABLE_PAGE_SIZE ? failure(504, 'the search took too long') : ok(eventPage(eventList(5))),
    )
    const wrapper = await mountTab()
    expect(wrapper.find('.event-table').text()).toContain('failed to load: the search took too long')
    expect(wrapper.findComponent(Timeline).exists()).toBe(true)
  })

  it('has the zoom radio disabled until there is something to zoom', async () => {
    eventsHistogramMock.mockResolvedValue(ok(histogram({ from: null, to: null, total: 0 })))
    const wrapper = await mountTab()
    expect(wrapper.findAll<HTMLInputElement>('.timeline-tab__zoom input').every((input) => input.element.disabled)).toBe(true)
  })
})
