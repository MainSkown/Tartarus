import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import type { FilterChip } from '@/api'
import FacetGroup from '@/components/FacetGroup.vue'
import { facetFixture } from './events-fixtures'

type Props = InstanceType<typeof FacetGroup>['$props']

const PROCESS = facetFixture('process.name', [
  ['cmd.exe', 40],
  ['svchost.exe', 20],
  ['notepad.exe', 1234],
])

function mountGroup(props: Partial<Props> = {}) {
  return mount(FacetGroup, {
    global: { plugins: [Quasar] },
    props: { field: 'process.name', facet: PROCESS, loading: false, chips: [] as FilterChip[], ...props },
  })
}

describe('FacetGroup', () => {
  it('has the field as its heading, with how many events have a value', () => {
    const heading = mountGroup().find('.facet-group__heading')
    expect(heading.text()).toContain('PROCESS')
    expect(heading.attributes('title')).toBe('process.name')
  })

  it('lists each value with its count, grouped thousands', () => {
    const rows = mountGroup().findAll('.facet-value')
    expect(rows.map((row) => row.find('.facet-value__name').text())).toEqual(['cmd.exe', 'svchost.exe', 'notepad.exe'])
    expect(rows.map((row) => row.find('.facet-value__count').text())).toEqual(['40', '20', '1,234'])
  })

  it('draws a bar as wide as the value is common, next to the most common one', () => {
    const bars = mountGroup().findAll('.facet-value__bar')
    expect(bars[2]!.attributes('style')).toContain('width: 100%')
    expect(bars[0]!.attributes('style')).toMatch(/width: 3\.2/)
  })

  it('shows the lane icon beside a lane value', () => {
    const wrapper = mountGroup({ field: 'tartarus.lane', facet: facetFixture('tartarus.lane', [['file', 3]]) })
    expect(wrapper.find('.facet-value .q-icon').text()).toBe('description')
  })

  it('has no icon for a value of another field', () => {
    expect(mountGroup().find('.facet-value__pick .q-icon').exists()).toBe(false)
  })

  it('asks to filter on a value that is clicked', async () => {
    const wrapper = mountGroup()
    await wrapper.findAll('.facet-value__pick')[1]!.trigger('click')
    expect(wrapper.emitted('pick')).toEqual([['svchost.exe', false]])
  })

  it('asks to filter out a value that is alt-clicked', async () => {
    const wrapper = mountGroup()
    await wrapper.findAll('.facet-value__pick')[1]!.trigger('click', { altKey: true })
    expect(wrapper.emitted('pick')).toEqual([['svchost.exe', true]])
  })

  it('asks to filter out from the minus button, which keyboard and touch users can reach', async () => {
    const wrapper = mountGroup()
    const minus = wrapper.findAll('.facet-value__exclude')[0]!
    expect(minus.attributes('aria-label')).toBe('Filter out process.name: cmd.exe')
    await minus.trigger('click')
    expect(wrapper.emitted('pick')).toEqual([['cmd.exe', true]])
  })

  it('marks a value that has a chip, and one that has a negated chip', () => {
    const chips: FilterChip[] = [
      { field: 'process.name', value: 'cmd.exe', negate: false },
      { field: 'process.name', value: 'svchost.exe', negate: true },
    ]
    const rows = mountGroup({ chips }).findAll('.facet-value')
    expect(rows[0]!.classes()).toContain('is-included')
    expect(rows[1]!.classes()).toContain('is-excluded')
    expect(rows[2]!.classes()).not.toContain('is-included')
    expect(rows[0]!.find('.facet-value__pick').attributes('aria-pressed')).toBe('true')
    expect(rows[2]!.find('.facet-value__pick').attributes('aria-pressed')).toBe('false')
  })

  it('shows placeholder lines while loading with nothing yet, keeping the heading', () => {
    const wrapper = mountGroup({ facet: undefined, loading: true })
    expect(wrapper.find('.facet-group__heading').text()).toContain('PROCESS')
    expect(wrapper.findAll('.facet-value--skeleton').length).toBeGreaterThan(2)
  })

  it('dims the old counts while new ones load', () => {
    expect(mountGroup({ loading: true }).find('.facet-group').classes()).toContain('is-stale')
  })

  it('says a field has no values', () => {
    const wrapper = mountGroup({ facet: facetFixture('process.name', []) })
    expect(wrapper.text()).toContain('no values')
  })
})
