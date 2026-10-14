import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar } from 'quasar'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { EventDetail } from '@/api'
import { eventDetail, eventFixture } from './events-fixtures'

vi.mock('@/api', () => ({ queryFields: vi.fn().mockResolvedValue({ data: [] }) }))

const { default: EventDetailPanel } = await import('@/components/EventDetailPanel.vue')

type Props = InstanceType<typeof EventDetailPanel>['$props']

const EVENT = eventFixture({
  id: 'ev1',
  time: '2026-10-13T15:39:34.123Z',
  lane: 'api',
  action: 'NtWriteFile',
  summary: 'cmd.exe called NtWriteFile',
  severity: 'high',
  process: { pid: 2476, name: 'cmd.exe', entity_id: null },
})

const DETAIL: EventDetail = eventDetail(EVENT, {
  source: {
    '@timestamp': '2026-10-13T15:39:34.123Z',
    event: { id: 'ev1', action: 'NtWriteFile' },
    process: { pid: 2476, name: 'cmd.exe' },
    tartarus: { lane: 'api', raw: { call: 'NtWriteFile' } },
  },
  related: {
    references: { items: [eventFixture({ id: 'r1', summary: 'the trigger' })], total: 1 },
    referenced_by: { items: [eventFixture({ id: 'a1', summary: 'the alert', kind: 'alert' })], total: 120 },
  },
})

function mountPanel(props: Partial<Props> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(EventDetailPanel, {
    global: { plugins: [Quasar, pinia] },
    props: { eventId: 'ev1', detail: DETAIL, loading: false, notFound: false, hasPrevious: true, hasNext: true, ...props },
  })
}

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('the header', () => {
  it('shows the summary, the full time, the lane, the process and the severity', () => {
    const header = mountPanel().find('.event-detail__header')
    expect(header.text()).toContain('cmd.exe called NtWriteFile')
    expect(header.find('.event-detail__time').text()).toBe('2026-10-13 15:39:34.123 UTC')
    expect(header.find('.q-icon[aria-hidden]').exists()).toBe(true)
    expect(header.find('.process-chip').text()).toBe('cmd.exe (2476)')
    expect(header.find('.severity-badge').text()).toContain('HIGH')
  })

  it('leaves out the severity of an event that has none', () => {
    const wrapper = mountPanel({ detail: eventDetail(eventFixture({ id: 'ev1', severity: null })) })
    expect(wrapper.find('.event-detail__header .severity-badge').exists()).toBe(false)
  })

  it('closes from the close button', async () => {
    const wrapper = mountPanel()
    await wrapper.find('[aria-label="Close event"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('moves to the previous and next event from its arrows', async () => {
    const wrapper = mountPanel()
    await wrapper.find('[aria-label="Previous event"]').trigger('click')
    await wrapper.find('[aria-label="Next event"]').trigger('click')
    expect(wrapper.emitted('previous')).toHaveLength(1)
    expect(wrapper.emitted('next')).toHaveLength(1)
  })

  it('disables an arrow at the end of the list', () => {
    const wrapper = mountPanel({ hasPrevious: false, hasNext: false })
    expect(wrapper.find('[aria-label="Previous event"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[aria-label="Next event"]').attributes('disabled')).toBeDefined()
  })

  it('moves with the up and down keys, but not past the ends', async () => {
    const wrapper = mountPanel({ hasPrevious: false })
    await wrapper.find('.event-detail').trigger('keydown', { key: 'ArrowUp' })
    expect(wrapper.emitted('previous')).toBeUndefined()
    await wrapper.find('.event-detail').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('next')).toHaveLength(1)
  })

  it('asks the dialog around it to focus it, so the arrow keys reach it', () => {
    expect(mountPanel().find('.event-detail').attributes('data-autofocus')).toBeDefined()
  })

  it('names the event by its id while it has no detail yet', () => {
    expect(mountPanel({ detail: undefined, loading: true }).find('.event-detail__header').text()).toContain('ev1')
  })
})

describe('the fields', () => {
  it('lists the fields of the stored document, without the original record', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const names = wrapper.findAll('.field-row__name').map((name) => name.text())
    expect(names).toEqual(['@timestamp', 'event.id', 'event.action', 'process.pid', 'process.name', 'tartarus.lane'])
  })
})

describe('the raw JSON', () => {
  it('is collapsed until it is opened', async () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.event-detail__raw').exists()).toBe(false)
    const toggle = wrapper.find('.event-detail__raw-toggle')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.event-detail__raw').classes()).toContain('code-block')
    expect(JSON.parse(wrapper.find('.event-detail__raw').text())).toEqual(DETAIL.source)
  })

  it('has a button that copies it', async () => {
    const wrapper = mountPanel()
    await wrapper.find('.event-detail__raw-toggle').trigger('click')
    expect(wrapper.find('[aria-label="Copy raw JSON"]').exists()).toBe(true)
  })
})

describe('the related events', () => {
  it('lists what the event references and what references it, with the totals', () => {
    const wrapper = mountPanel()
    const headings = wrapper.findAll('.related-list__heading').map((heading) => heading.text())
    expect(headings[0]).toContain('REFERENCES')
    expect(headings[1]).toContain('REFERENCED BY')
    expect(headings[1]).toContain('showing 1 of 120')
  })

  it('opens a related event', async () => {
    const wrapper = mountPanel()
    await wrapper.findAll('.related-event')[1]!.trigger('click')
    expect(wrapper.emitted('open-event')).toEqual([['a1']])
  })

  it('says there are none when there are none', () => {
    const wrapper = mountPanel({ detail: eventDetail(EVENT) })
    expect(wrapper.text()).toContain('no related events')
  })
})

describe('states', () => {
  it('shows placeholders while the first event loads', () => {
    const wrapper = mountPanel({ detail: undefined, loading: true })
    expect(wrapper.find('.event-detail__skeleton').exists()).toBe(true)
    expect(wrapper.find('.field-row').exists()).toBe(false)
  })

  it('keeps the previous event, dimmed, while the next one loads', () => {
    const wrapper = mountPanel({ loading: true })
    expect(wrapper.find('.event-detail__body').classes()).toContain('is-stale')
    expect(wrapper.find('.event-detail__skeleton').exists()).toBe(false)
  })

  it('says the event is gone for a 404', () => {
    const wrapper = mountPanel({ detail: undefined, notFound: true })
    expect(wrapper.text()).toContain('event not found')
  })

  it('shows an error with a retry', async () => {
    const wrapper = mountPanel({ detail: undefined, error: 'search failed' })
    expect(wrapper.text()).toContain('failed to load: search failed')
    await wrapper.find('button.retry-btn').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})
