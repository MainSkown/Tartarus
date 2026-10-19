import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { findingFromEvent } from '@/services/memory-findings'
import { filterEventsPlugins } from './filter-events-plugins'
import { findingDetail, findingEvent, hollowEvent } from './memory-fixtures'

const eventsDetail = vi.hoisted(() => vi.fn())
vi.mock('@/api', () => ({ eventsDetail }))

const { default: MemoryFindingRow } = await import('@/components/MemoryFindingRow.vue')
const { plugins } = await filterEventsPlugins()

function mountRow(event = findingEvent('1e3eba60000')) {
  return mount(MemoryFindingRow, {
    global: { plugins },
    attachTo: document.createElement('table'),
    props: { analysisId: 45, finding: findingFromEvent(event) },
  })
}

type Row = ReturnType<typeof mountRow>

async function expand(wrapper: Row): Promise<void> {
  await wrapper.find('.finding-toggle').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  eventsDetail.mockReset()
  eventsDetail.mockImplementation(async ({ path }: { path: { event_id: string } }) => ({
    data: findingDetail(findingEvent(path.event_id)),
    response: { status: 200 },
  }))
})

describe('MemoryFindingRow', () => {
  it('shows the severity, the process with its pid, the address, the protection and the note', () => {
    const wrapper = mountRow()
    const row = wrapper.find('tr.finding-row')
    expect(row.find('.severity-badge').text()).toContain('HIGH')
    expect(row.find('.process-chip').text()).toBe('notepad.exe (2184)')
    expect(row.find('.finding-address').text()).toBe('0x1e3eba60000')
    expect(row.text()).toContain('PAGE_EXECUTE_READWRITE')
    expect(row.text()).toContain('MZ header')
  })

  it('has a copy button for the address and an action to filter the events on the finding', () => {
    const wrapper = mountRow()
    expect(wrapper.find('.copy-button').attributes('aria-label')).toContain('address')
    const filter = wrapper.find('.filter-events-button')
    expect(filter.attributes('aria-label')).toContain('tartarus.memory.address: 0x1e3eba60000')
    expect(filter.attributes('aria-label')).toContain('process.pid: 2184')
  })

  it('shows a dash for what the finding does not have, and no copy button without an address', () => {
    const wrapper = mountRow(findingEvent('x', { process: null }, { 'tartarus.memory.address': '', 'tartarus.memory.protection': '', 'tartarus.memory.note': '' }))
    expect(wrapper.find('.process-chip').text()).toBe('–')
    expect(wrapper.findAll('.cell-empty')).toHaveLength(3)
    expect(wrapper.find('.copy-button').exists()).toBe(false)
  })

  it('keeps one cell per column, whatever the length of the process name, address and note', () => {
    const wrapper = mountRow(
      findingEvent('x', { process: { pid: 7, name: `${'a_very_long_process_name_'.repeat(8)}.exe`, entity_id: null } }, {
        'tartarus.memory.address': `0x${'f'.repeat(120)}`,
        'tartarus.memory.note': 'a very long note '.repeat(40),
      }),
    )
    expect(wrapper.findAll('tr.finding-row > td')).toHaveLength(6)
    expect(wrapper.find('.process-chip').attributes('title')).toContain('a_very_long_process_name_')
  })

  describe('details', () => {
    it('are not fetched until the row is opened', () => {
      const wrapper = mountRow()
      expect(eventsDetail).not.toHaveBeenCalled()
      expect(wrapper.find('.finding-toggle').attributes('aria-expanded')).toBe('false')
      expect(wrapper.find('.finding-detail').exists()).toBe(false)
    })

    it('are fetched from the event detail endpoint when the row is opened', async () => {
      const wrapper = mountRow()
      await expand(wrapper)
      expect(eventsDetail).toHaveBeenCalledTimes(1)
      expect(eventsDetail.mock.calls[0]![0].path).toEqual({ analysis_id: 45, event_id: '1e3eba60000' })
    })

    it('show the hex preview with offsets and characters, the disassembly and the command line', async () => {
      const wrapper = mountRow()
      await expand(wrapper)
      expect(wrapper.find('.finding-toggle').attributes('aria-expanded')).toBe('true')
      const detail = wrapper.find('.finding-detail')
      expect(detail.text()).toContain('FIRST 64 BYTES OF THE REGION')
      expect(detail.findAll('.hex-row')).toHaveLength(4)
      expect(detail.find('.hex-row').text()).toContain('0000')
      expect(detail.find('.hex-row').text()).toContain('4d 5a')
      expect(detail.find('.hex-row').text()).toContain('MZ')
      expect(detail.text()).toContain('0x1e3eba60001:  mov  rax, qword ptr [rcx]')
      expect(detail.text()).toContain('C:\\Windows\\System32\\notepad.exe C:\\Users\\Analyst\\a.txt')
    })

    it('say so for a plugin that reads no bytes', async () => {
      eventsDetail.mockResolvedValue({ data: findingDetail(hollowEvent('h1'), { PID: 6304, Notes: 'x' }), response: { status: 200 } })
      const wrapper = mountRow(hollowEvent('h1'))
      await expand(wrapper)
      expect(wrapper.find('.finding-detail').text()).toContain('this plugin does not read the bytes of the region')
      expect(wrapper.find('.hex-row').exists()).toBe(false)
    })

    it('show a skeleton while loading', async () => {
      eventsDetail.mockReturnValue(new Promise(() => undefined))
      const wrapper = mountRow()
      await expand(wrapper)
      expect(wrapper.find('.finding-detail [aria-busy="true"]').exists()).toBe(true)
    })

    it('show the error with a retry that asks again', async () => {
      eventsDetail.mockResolvedValueOnce({ error: { error: { code: 'x', message: 'index is down' } }, response: { status: 502 } })
      const wrapper = mountRow()
      await expand(wrapper)
      expect(wrapper.find('.finding-detail').text()).toContain('index is down')
      await wrapper.find('.finding-detail .retry-btn').trigger('click')
      await flushPromises()
      expect(eventsDetail).toHaveBeenCalledTimes(2)
      expect(wrapper.find('.hex-row').exists()).toBe(true)
    })

    it('close when the row is toggled again', async () => {
      const wrapper = mountRow()
      await expand(wrapper)
      await wrapper.find('.finding-toggle').trigger('click')
      expect(wrapper.find('.finding-detail').exists()).toBe(false)
      expect(wrapper.find('.finding-toggle').attributes('aria-expanded')).toBe('false')
    })
  })
})
