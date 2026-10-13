import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import type { Severity } from '@/api'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { SEVERITIES, severityMeta } from '@/services/analysis-status'

function mountBadge(severity: Severity, count?: number) {
  return mount(SeverityBadge, { global: { plugins: [Quasar] }, props: { severity, count } })
}

describe('SeverityBadge', () => {
  it.each(SEVERITIES)('is an outline badge with the icon and label of %s', (severity) => {
    const wrapper = mountBadge(severity)
    const meta = severityMeta(severity)
    expect(wrapper.classes()).toContain('q-badge--outline')
    expect(wrapper.text()).toContain(meta.label)
    expect(wrapper.find('.q-icon').text()).toBe(meta.icon)
  })

  it.each(SEVERITIES)('colours %s with its severity token', (severity) => {
    const wrapper = mountBadge(severity)
    expect(wrapper.attributes('style')).toContain(`var(${severityMeta(severity).color})`)
  })

  it('shows no count unless one is given', () => {
    expect(mountBadge('high').find('.severity-badge__count').exists()).toBe(false)
  })

  it('shows the count next to the label, including zero', () => {
    expect(mountBadge('high', 3).find('.severity-badge__count').text()).toBe('3')
    expect(mountBadge('low', 0).find('.severity-badge__count').text()).toBe('0')
  })
})
