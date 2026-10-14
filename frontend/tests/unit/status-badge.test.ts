import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import StatusBadge from '@/components/StatusBadge.vue'
import { ANALYSIS_STATUSES, analysisStatusMeta } from '@/services/analysis-status'
import { VALIDITIES, validityMeta } from '@/services/rule-view'

function mountBadge(status: (typeof ANALYSIS_STATUSES)[number]) {
  return mount(StatusBadge, { global: { plugins: [Quasar] }, props: { status } })
}

describe('StatusBadge', () => {
  it.each(ANALYSIS_STATUSES)('shows the label and the icon of %s', (status) => {
    const wrapper = mountBadge(status)
    const meta = analysisStatusMeta(status)
    expect(wrapper.text()).toContain(meta.label)
    expect(wrapper.find('.q-icon').text()).toBe(meta.icon)
  })

  it.each(ANALYSIS_STATUSES)('shows the live dot for %s only while the status is active', (status) => {
    const wrapper = mountBadge(status)
    expect(wrapper.find('.live-dot').exists()).toBe(analysisStatusMeta(status).active)
  })

  it.each(ANALYSIS_STATUSES)('colours %s with its status token', (status) => {
    const wrapper = mountBadge(status)
    expect(wrapper.attributes('style')).toContain(`var(${analysisStatusMeta(status).color})`)
    expect(wrapper.classes()).toContain(`status-badge--${status}`)
  })

  it('is red for failed and report_failed, green for done and muted for cancelled', () => {
    expect(mountBadge('failed').attributes('style')).toContain('--status-critical')
    expect(mountBadge('report_failed').attributes('style')).toContain('--status-critical')
    expect(mountBadge('done').attributes('style')).toContain('--status-success')
    expect(mountBadge('cancelled').attributes('style')).toContain('--text-gray-dark')
  })

  it('hides the decorative dot and icon from assistive tech but keeps the label readable', () => {
    const wrapper = mountBadge('running')
    expect(wrapper.find('.live-dot').attributes('aria-hidden')).toBe('true')
    expect(wrapper.find('.q-icon').attributes('aria-hidden')).toBe('true')
  })

  it('follows a changing status', async () => {
    const wrapper = mountBadge('running')
    await wrapper.setProps({ status: 'done' })
    expect(wrapper.text()).toContain('DONE')
    expect(wrapper.find('.live-dot').exists()).toBe(false)
  })
})

describe('StatusBadge for a rule validity', () => {
  it.each(VALIDITIES)('shows the label, icon and colour of %s', (validity) => {
    const wrapper = mount(StatusBadge, { global: { plugins: [Quasar] }, props: { validity } })
    const meta = validityMeta(validity)
    expect(wrapper.text()).toContain(meta.label)
    expect(wrapper.find('.q-icon').text()).toBe(meta.icon)
    expect(wrapper.attributes('style')).toContain(`var(${meta.color})`)
    expect(wrapper.classes()).toContain(`status-badge--${validity}`)
    expect(wrapper.find('.live-dot').exists()).toBe(false)
  })
})
