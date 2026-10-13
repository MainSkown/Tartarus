import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LiveDesktopSlot from '@/components/LiveDesktopSlot.vue'
import { analysisWithStatus } from './analysis-fixtures'

describe('LiveDesktopSlot', () => {
  it('marks its root as the desktop of the live tab, for the panel that will fill it', () => {
    const wrapper = mount(LiveDesktopSlot, { props: { analysis: analysisWithStatus('running', { options: { interactive: true } }) } })
    expect(wrapper.attributes('data-live')).toBe('desktop')
    expect(wrapper.find('.pane-heading').text()).toBe('DESKTOP')
  })

  it('says the desktop panel arrives in the next step', () => {
    const wrapper = mount(LiveDesktopSlot, { props: { analysis: analysisWithStatus('running', { options: { interactive: true } }) } })
    expect(wrapper.text()).toContain('desktop panel arrives in the next step')
  })
})
