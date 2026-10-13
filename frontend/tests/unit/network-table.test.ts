import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import NetworkTable, { type NetworkColumn, type NetworkTableRow } from '@/components/NetworkTable.vue'

const ROWS: NetworkTableRow[] = [
  { key: 'a', cells: ['first', 10], process: { pid: 7, name: 'cmd.exe' } },
  { key: 'b', cells: ['second', 20], process: null },
]

const COLUMNS: NetworkColumn[] = [{ label: 'NAME' }, { label: 'SIZE', numeric: true }]

function mountTable(
  props: Partial<{ withProcess: boolean; simulated: boolean; total: number; rows: NetworkTableRow[] }> = {},
) {
  return mount(NetworkTable, {
    props: { columns: COLUMNS, rows: ROWS, total: ROWS.length, ...props },
    global: { plugins: [Quasar] },
  })
}

describe('NetworkTable', () => {
  it('renders a header per column and a row per item', () => {
    const wrapper = mountTable()
    expect(wrapper.findAll('th').map((th) => th.text())).toEqual(['NAME', 'SIZE'])
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.findAll('tbody tr')[0]!.findAll('td').map((td) => td.text())).toEqual(['first', '10'])
  })

  it('shows a dash for an absent value', () => {
    const wrapper = mountTable({ rows: [{ key: 'c', cells: [null, 1] }] })
    expect(wrapper.find('tbody td').text()).toBe('–')
  })

  it('gives every value its text as a title so a truncated one can be read', () => {
    const wrapper = mountTable()
    expect(wrapper.find('tbody td .cell-value').attributes('title')).toBe('first')
  })

  it('right-aligns a numeric column', () => {
    const wrapper = mountTable()
    expect(wrapper.findAll('th')[1]!.classes()).toContain('num')
    expect(wrapper.findAll('tbody tr')[0]!.findAll('td')[1]!.classes()).toContain('num')
  })

  it('adds a process column rendered as a process chip', () => {
    const wrapper = mountTable({ withProcess: true })
    expect(wrapper.findAll('th').map((th) => th.text())).toEqual(['NAME', 'SIZE', 'PROCESS'])
    const chips = wrapper.findAll('.process-chip')
    expect(chips.map((chip) => chip.text())).toEqual(['cmd.exe (7)', '–'])
  })

  it('has no process column by default', () => {
    expect(mountTable().find('.process-chip').exists()).toBe(false)
  })

  it('says how many of the total are listed', () => {
    expect(mountTable({ total: 214 }).find('.network-table__count').text()).toBe('listed 2 of 214')
  })

  it('marks the table as answered by inetsim only when simulated', () => {
    expect(mountTable({ simulated: true }).find('.network-table__inetsim').text()).toBe('inetsim')
    expect(mountTable({ simulated: false }).find('.network-table__inetsim').exists()).toBe(false)
  })

  it('scrolls inside its own container', () => {
    expect(mountTable().find('.tt-table-scroll .tt-table').exists()).toBe(true)
  })
})
