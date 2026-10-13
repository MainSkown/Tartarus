import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PaneHeading from '@/components/PaneHeading.vue'

describe('PaneHeading', () => {
  it('shows its label in the heading style shared by the panes of a tab', () => {
    const wrapper = mount(PaneHeading, { props: { label: 'DESCRIPTION' } })
    expect(wrapper.text()).toBe('DESCRIPTION')
    expect(wrapper.classes()).toContain('pane-heading')
  })
})
