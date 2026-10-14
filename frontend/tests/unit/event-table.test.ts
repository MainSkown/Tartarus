import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { Quasar, QVirtualScroll } from 'quasar'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import type { Event } from '@/api'
import { COLUMNS_STORAGE_KEY } from '@/composables/use-event-columns'
import { eventFixture, eventList } from './events-fixtures'

vi.mock('@/api', () => ({ queryFields: vi.fn().mockResolvedValue({ data: [] }) }))

const { default: EventTable } = await import('@/components/EventTable.vue')

type Props = InstanceType<typeof EventTable>['$props']

const EVENTS: Event[] = [
  eventFixture({ id: 'a', time: '2026-10-13T15:39:34.123Z', lane: 'file', action: 'file-written', summary: 'cmd.exe wrote C:\\a.ps1', file_path: 'C:\\a.ps1' }),
  eventFixture({ id: 'b', time: '2026-10-13T15:39:35.007Z', lane: 'api', action: 'NtDelayExecution', summary: 'NtDelayExecution', process: null }),
  eventFixture({
    id: 'c',
    time: '2026-10-13T15:39:36.500Z',
    lane: 'process',
    kind: 'alert',
    action: 'rule-matched',
    summary: 'Suspicious PowerShell',
    severity: 'high',
    process: { pid: 4412, name: 'powershell.exe', entity_id: null },
  }),
]

function mountTable(props: Partial<Props> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(EventTable, {
    attachTo: document.body,
    global: { plugins: [Quasar, pinia] },
    props: {
      events: EVENTS,
      total: 3,
      loading: false,
      loadingMore: false,
      hasMore: false,
      sort: '@timestamp',
      selectedId: null,
      filtered: false,
      ...props,
    },
  })
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => window.localStorage.clear())

describe('the header', () => {
  it('names the default columns', () => {
    const headers = mountTable()
      .findAll('[role="columnheader"]')
      .map((header) => header.find('button').exists() ? header.find('button').text().replace(/arrow_\w+/, '') : header.text())
    expect(headers).toEqual(['TIME', 'LANE', 'PROCESS', 'ACTION', 'SUMMARY', 'SEVERITY'])
  })

  it('says which way the time is sorted', () => {
    expect(mountTable().find('[role="columnheader"]').attributes('aria-sort')).toBe('ascending')
    expect(mountTable({ sort: '-@timestamp' }).find('[role="columnheader"]').attributes('aria-sort')).toBe('descending')
  })

  it('asks to flip the sort when the time header is clicked', async () => {
    const wrapper = mountTable()
    await wrapper.find('[role="columnheader"] button').trigger('click')
    expect(wrapper.emitted('toggle-sort')).toHaveLength(1)
  })

  it('shows how many of the events are loaded', () => {
    expect(mountTable({ events: EVENTS, total: 4321 }).text()).toContain('3 of 4,321 events')
  })

  it('counts a single event in the singular', () => {
    expect(mountTable({ events: [EVENTS[0]!], total: 1 }).text()).toContain('1 of 1 event')
  })
})

describe('the rows', () => {
  it('shows the time of day to the millisecond, with the full time on hover', () => {
    const cell = mountTable().find('[data-column="time"]')
    expect(cell.text()).toBe('15:39:34.123')
    expect(cell.attributes('title')).toBe('2026-10-13T15:39:34.123Z')
  })

  it('shows the lane as an icon with its name on hover', () => {
    const cell = mountTable().find('[data-column="lane"]')
    expect(cell.find('.q-icon').text()).toBe('description')
    expect(cell.attributes('title')).toBe('FILE')
  })

  it('shows the process by name and pid, and a dash for an event with none', () => {
    const cells = mountTable().findAll('[data-column="process"]')
    expect(cells[0]!.text()).toBe('cmd.exe (2476)')
    expect(cells[1]!.text()).toBe('–')
  })

  it('shows the action and the summary, the summary whole on hover', () => {
    const row = mountTable().find('[role="row"][data-event-id="a"]')
    expect(row.find('[data-column="action"]').text()).toBe('file-written')
    expect(row.find('[data-column="summary"]').text()).toBe('cmd.exe wrote C:\\a.ps1')
    expect(row.find('[data-column="summary"]').attributes('title')).toBe('cmd.exe wrote C:\\a.ps1')
  })

  it('shows a severity badge only where the event has a severity', () => {
    const wrapper = mountTable()
    expect(wrapper.find('[data-event-id="a"] .severity-badge').exists()).toBe(false)
    expect(wrapper.find('[data-event-id="c"] .severity-badge').text()).toContain('HIGH')
  })

  it('marks the selected row', () => {
    const wrapper = mountTable({ selectedId: 'b' })
    expect(wrapper.find('[data-event-id="b"]').classes()).toContain('is-selected')
    expect(wrapper.find('[data-event-id="b"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.find('[data-event-id="a"]').attributes('aria-selected')).toBe('false')
  })

  it('shows the extra columns the viewer chose, after the default ones', () => {
    window.localStorage.setItem(COLUMNS_STORAGE_KEY, JSON.stringify(['file.path']))
    const wrapper = mountTable()
    expect(wrapper.findAll('[role="columnheader"]').map((header) => header.text())).toContain('FILE.PATH')
    expect(wrapper.find('[data-event-id="a"] [data-column="file.path"]').text()).toBe('C:\\a.ps1')
    expect(wrapper.find('[data-event-id="b"] [data-column="file.path"]').text()).toBe('')
  })
})

describe('choosing a row', () => {
  it('selects and opens the row that is clicked', async () => {
    const wrapper = mountTable()
    await wrapper.find('[data-event-id="b"]').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['b']])
    expect(wrapper.emitted('open')).toEqual([['b']])
  })

  it('moves the selection down and up with the arrow keys', async () => {
    const wrapper = mountTable({ selectedId: 'a' })
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('select')).toEqual([['b']])
    await wrapper.setProps({ selectedId: 'c' })
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowUp' })
    expect(wrapper.emitted('select')![1]).toEqual(['b'])
  })

  it('stops at the first and the last row', async () => {
    const wrapper = mountTable({ selectedId: 'a' })
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowUp' })
    await wrapper.setProps({ selectedId: 'c' })
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it('selects the first row on the down arrow when nothing is selected', async () => {
    const wrapper = mountTable()
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('select')).toEqual([['a']])
  })

  it('opens the selected row on Enter, and does nothing on Enter without one', async () => {
    const wrapper = mountTable()
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('open')).toBeUndefined()
    await wrapper.setProps({ selectedId: 'b' })
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('open')).toEqual([['b']])
  })

  it('can be reached by the keyboard', () => {
    expect(mountTable().find('[role="grid"]').attributes('tabindex')).toBe('0')
  })
})

describe('paging', () => {
  function reportScroll(wrapper: ReturnType<typeof mountTable>, to: number) {
    wrapper.findComponent(QVirtualScroll).vm.$emit('virtual-scroll', { index: 0, from: 0, to, direction: 'increase' })
  }

  it('asks for the next page when the rows near the end are on screen', async () => {
    const wrapper = mountTable({ events: eventList(100), total: 500, hasMore: true })
    reportScroll(wrapper, 90)
    expect(wrapper.emitted('load-more')).toHaveLength(1)
  })

  it('does not ask while the end is far away, nothing more is there, or a page is on its way', async () => {
    const far = mountTable({ events: eventList(100), total: 500, hasMore: true })
    reportScroll(far, 10)
    const last = mountTable({ events: eventList(100), total: 100, hasMore: false })
    reportScroll(last, 99)
    const busy = mountTable({ events: eventList(100), total: 500, hasMore: true, loadingMore: true })
    reportScroll(busy, 99)
    expect(far.emitted('load-more')).toBeUndefined()
    expect(last.emitted('load-more')).toBeUndefined()
    expect(busy.emitted('load-more')).toBeUndefined()
  })

  it('shows a footer row while the next page is loading', () => {
    const wrapper = mountTable({ events: eventList(100), total: 500, hasMore: true, loadingMore: true })
    expect(wrapper.find('.event-table__footer').text()).toContain('loading more')
  })

  it('says when the next page failed, and asks again on retry', async () => {
    const wrapper = mountTable({ events: eventList(100), total: 500, hasMore: true, loadMoreError: 'the search took too long' })
    expect(wrapper.find('.event-table__footer').text()).toContain('the search took too long')
    await wrapper.find('.event-table__footer button').trigger('click')
    expect(wrapper.emitted('load-more')).toHaveLength(1)
  })
})

describe('states', () => {
  it('shows skeleton rows while the first page loads', () => {
    const wrapper = mountTable({ events: [], total: 0, loading: true })
    expect(wrapper.findAll('.event-skeleton-row').length).toBeGreaterThan(5)
    expect(wrapper.find('[role="row"][data-event-id]').exists()).toBe(false)
  })

  it('keeps the old rows, dimmed, while a new filter loads', () => {
    const wrapper = mountTable({ loading: true })
    expect(wrapper.find('.event-table__grid').classes()).toContain('is-stale')
    expect(wrapper.findAll('[data-event-id]')).toHaveLength(3)
    expect(wrapper.findAll('.event-skeleton-row')).toHaveLength(0)
  })

  it('says there are no events when the analysis has none', () => {
    const wrapper = mountTable({ events: [], total: 0 })
    expect(wrapper.text()).toContain('no events')
    expect(wrapper.text()).not.toContain('matches')
  })

  it('says no event matches a query, and offers to clear it', async () => {
    const wrapper = mountTable({ events: [], total: 0, filtered: true })
    expect(wrapper.text()).toContain('no event matches this query')
    await wrapper.find('.event-table__clear').trigger('click')
    expect(wrapper.emitted('clear')).toHaveLength(1)
  })

  it('shows the error with a retry', async () => {
    const wrapper = mountTable({ events: [], total: 0, error: 'the search took too long' })
    expect(wrapper.text()).toContain('failed to load: the search took too long')
    await wrapper.find('button.retry-btn').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })
})

describe('the first page replaced', () => {
  it('scrolls back to the top when the list starts with another event', async () => {
    const wrapper = mountTable({ events: eventList(100), total: 100 })
    const list = wrapper.find('.event-table__list').element as HTMLElement
    list.scrollTop = 500
    await wrapper.setProps({ events: eventList(100, 200) })
    await nextTick()
    expect(list.scrollTop).toBe(0)
  })
})
