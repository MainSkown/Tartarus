import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatTile from '@/components/StatTile.vue'

describe('StatTile', () => {
  it('shows the label and the value', () => {
    const wrapper = mount(StatTile, { props: { label: 'PROCESSES', value: 5 } })
    expect(wrapper.text()).toContain('PROCESSES')
    expect(wrapper.text()).toContain('5')
  })

  it('shows a dash when there is no value yet', () => {
    const wrapper = mount(StatTile, { props: { label: 'SCORE', value: null } })
    expect(wrapper.find('.stat-tile__value').text()).toBe('–')
  })

  it('keeps a zero as a zero', () => {
    const wrapper = mount(StatTile, { props: { label: 'FILES', value: 0 } })
    expect(wrapper.find('.stat-tile__value').text()).toBe('0')
  })
})
