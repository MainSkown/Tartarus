import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LiveDetectionsPanel from '@/components/LiveDetectionsPanel.vue'

describe('LiveDetectionsPanel', () => {
  it('says why there is nothing: signatures run after the analysis and live rules come with Sigma', () => {
    const wrapper = mount(LiveDetectionsPanel)
    expect(wrapper.find('.pane-heading').text()).toBe('DETECTIONS')
    expect(wrapper.text()).toContain('signatures run after the analysis')
    expect(wrapper.text()).toContain('live rules arrive with Sigma')
  })
})
