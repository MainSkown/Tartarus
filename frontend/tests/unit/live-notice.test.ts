import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import LiveNotice from '@/components/LiveNotice.vue'

describe('LiveNotice', () => {
  it('shows its message without taking over the page', () => {
    const wrapper = mount(LiveNotice, { global: { plugins: [Quasar] }, slots: { default: '12 events skipped' } })
    expect(wrapper.text()).toContain('12 events skipped')
    expect(wrapper.attributes('role')).toBe('status')
  })

  it('is an alert, in the warm scale, for a warning', () => {
    const wrapper = mount(LiveNotice, { global: { plugins: [Quasar] }, props: { level: 'warning' }, slots: { default: 'log_format' } })
    expect(wrapper.attributes('role')).toBe('alert')
    expect(wrapper.classes()).toContain('live-notice--warning')
  })
})
