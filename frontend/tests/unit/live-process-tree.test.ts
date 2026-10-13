import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LiveProcessTree from '@/components/LiveProcessTree.vue'
import { processRoots } from '@/services/live-state'
import { liveProcess } from './live-fixtures'

const ROOTS = processRoots(
  new Map([
    [10, liveProcess(10, { name: 'benign.exe', start: '2026-10-13T15:39:50.000Z' })],
    [
      11,
      liveProcess(11, { ppid: 10, name: 'cmd.exe', start: '2026-10-13T15:39:51.000Z', end: '2026-10-13T15:39:52.300Z' }),
    ],
    [12, liveProcess(12, { ppid: 11, name: null, start: '2026-10-13T15:39:51.500Z' })],
  ]),
)

function mountTree(props: Partial<InstanceType<typeof LiveProcessTree>['$props']> = {}) {
  return mount(LiveProcessTree, {
    global: { plugins: [Quasar] },
    props: { roots: ROOTS, emptyMessage: 'starting the guest...', ...props },
  })
}

describe('LiveProcessTree', () => {
  it('lists every process, indented under its parent, with the count in the heading', () => {
    const wrapper = mountTree()
    const rows = wrapper.findAll('.live-process')
    expect(rows.map((row) => row.find('.process-chip').text())).toEqual(['benign.exe (10)', 'cmd.exe (11)', 'pid 12'])
    expect(rows.map((row) => row.attributes('data-depth'))).toEqual(['0', '1', '2'])
    expect(wrapper.find('.pane-heading').text()).toContain('PROCESSES')
    expect(wrapper.find('.pane-heading').text()).toContain('3')
  })

  it('marks the processes that are still running and dims the ones that ended, with how long they lived', () => {
    const rows = mountTree().findAll('.live-process')
    expect(rows[0]!.find('.live-dot').exists()).toBe(true)
    expect(rows[0]!.classes()).not.toContain('live-process--ended')
    expect(rows[1]!.find('.live-dot').exists()).toBe(false)
    expect(rows[1]!.classes()).toContain('live-process--ended')
    expect(rows[1]!.find('.live-process__lifetime').text()).toBe('1.3s')
  })

  it('names the state in words as well, for a reader who cannot tell the dot from its absence', () => {
    const rows = mountTree().findAll('.live-process')
    expect(rows[0]!.find('.live-process__state').text()).toBe('running')
    expect(rows[1]!.find('.live-process__state').text()).toBe('ended')
  })

  it('shows a process with no end time as ended, not running, once the run is over', () => {
    const rows = mountTree({ runOver: true }).findAll('.live-process')
    expect(rows.map((row) => row.find('.live-process__state').text())).toEqual(['ended', 'ended', 'ended'])
    expect(rows.some((row) => row.find('.live-dot').exists())).toBe(false)
    expect(rows[0]!.find('.live-process__lifetime').exists()).toBe(false)
    expect(rows[1]!.find('.live-process__lifetime').text()).toBe('1.3s')
  })

  it('selects a process on click', async () => {
    const wrapper = mountTree()
    await wrapper.findAll('.live-process')[1]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[11]])
  })

  it('clears the selection when the selected process is clicked again', async () => {
    const wrapper = mountTree({ selectedPid: 11 })
    await wrapper.findAll('.live-process')[1]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([[undefined]])
  })

  it('marks the selected process', () => {
    const rows = mountTree({ selectedPid: 10 }).findAll('.live-process')
    expect(rows.map((row) => row.attributes('aria-pressed'))).toEqual(['true', 'false', 'false'])
  })

  it('says why there is no process yet', () => {
    const wrapper = mountTree({ roots: [] })
    expect(wrapper.find('.live-process').exists()).toBe(false)
    expect(wrapper.text()).toContain('starting the guest...')
  })
})
