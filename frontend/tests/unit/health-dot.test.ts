import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import HealthDot from '@/components/HealthDot.vue'

describe('HealthDot', () => {
  it('marks "ok" with the success token and reports it in the accessible description', () => {
    const wrapper = mount(HealthDot, {
      global: { plugins: [Quasar] },
      props: { label: 'CAPE', status: 'ok', message: null },
    })
    expect(wrapper.classes()).toContain('health-dot--ok')
    expect(wrapper.attributes('aria-label')).toContain('CAPE')
    expect(wrapper.attributes('aria-label')).toContain('ok')
  })

  it('marks "degraded" with the medium token and includes the message', () => {
    const wrapper = mount(HealthDot, {
      global: { plugins: [Quasar] },
      props: { label: 'Store', status: 'degraded', message: 'opensearch slow' },
    })
    expect(wrapper.classes()).toContain('health-dot--degraded')
    expect(wrapper.attributes('aria-label')).toContain('opensearch slow')
  })

  it('marks "down" with the critical token and includes the message', () => {
    const wrapper = mount(HealthDot, {
      global: { plugins: [Quasar] },
      props: { label: 'Guest', status: 'down', message: 'not set up yet' },
    })
    expect(wrapper.classes()).toContain('health-dot--down')
    expect(wrapper.attributes('aria-label')).toContain('not set up yet')
  })

  it('describes each sub-component individually for the combined Store dot', () => {
    const wrapper = mount(HealthDot, {
      global: { plugins: [Quasar] },
      props: {
        label: 'Store',
        status: 'down',
        subStatuses: [
          { label: 'Postgres', status: 'ok', message: null },
          { label: 'OpenSearch', status: 'down', message: 'unreachable' },
        ],
      },
    })
    const description = wrapper.attributes('aria-label') ?? ''
    expect(description).toContain('Postgres')
    expect(description).toContain('OpenSearch')
    expect(description).toContain('unreachable')
  })
})
