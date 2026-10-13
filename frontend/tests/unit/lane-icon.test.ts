import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LaneIcon from '@/components/LaneIcon.vue'
import { laneMeta } from '@/services/lanes'

describe('LaneIcon', () => {
  it.each(['process', 'file', 'registry', 'network', 'memory', 'api'])('draws the %s lane with its icon and colour', (lane) => {
    const wrapper = mount(LaneIcon, { global: { plugins: [Quasar] }, props: { lane } })
    expect(wrapper.text()).toBe(laneMeta(lane).icon)
    expect(wrapper.attributes('style')).toContain(`var(${laneMeta(lane).color})`)
  })

  it('is decorative: the lane label beside it carries the meaning', () => {
    const wrapper = mount(LaneIcon, { global: { plugins: [Quasar] }, props: { lane: 'file' } })
    expect(wrapper.attributes('aria-hidden')).toBe('true')
  })

  it('falls back to the neutral lane for a lane it does not know', () => {
    const wrapper = mount(LaneIcon, { global: { plugins: [Quasar] }, props: { lane: 'sysmon' } })
    expect(wrapper.attributes('style')).toContain('--cat-api')
  })
})
