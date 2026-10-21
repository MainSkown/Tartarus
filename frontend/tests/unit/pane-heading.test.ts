import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import PaneHeading from '@/components/PaneHeading.vue'

describe('PaneHeading', () => {
  it('shows its label in the heading style shared by the panes of a tab', () => {
    const wrapper = mount(PaneHeading, { props: { label: 'DESCRIPTION' } })
    expect(wrapper.text()).toBe('DESCRIPTION')
    expect(wrapper.classes()).toContain('pane-heading')
  })

  it('keeps the label in a heading element, so the page outline does not change', () => {
    const wrapper = mount(PaneHeading, { props: { label: 'STEPS' } })
    expect(wrapper.find('h3.pane-heading__title').text()).toBe('STEPS')
  })

  it('has no actions area when it has no actions', () => {
    const wrapper = mount(PaneHeading, { props: { label: 'STEPS' } })
    expect(wrapper.find('.pane-heading__actions').exists()).toBe(false)
  })

  it('puts the title on the left and the actions it was given on the right, in one row', () => {
    const wrapper = mount(PaneHeading, { props: { label: 'BUILD LOG' }, slots: { default: '<button>[COPY LOG]</button><button>[PAUSE FOLLOW]</button>' } })
    const [title, actions] = Array.from((wrapper.element as HTMLElement).children)
    expect(title?.className).toContain('pane-heading__title')
    expect(actions?.className).toContain('pane-heading__actions')
    expect(Array.from(actions!.querySelectorAll('button'), (button) => button.textContent)).toEqual(['[COPY LOG]', '[PAUSE FOLLOW]'])
  })
})
