import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AnalysisTabs from '@/components/AnalysisTabs.vue'

function mountTabs(active = 'summary') {
  return mount(AnalysisTabs, { props: { active } })
}

describe('AnalysisTabs', () => {
  it('marks the active tab as selected', () => {
    const selected = mountTabs().findAll('[aria-selected="true"]')
    expect(selected).toHaveLength(1)
    expect(selected[0]!.text()).toBe('SUMMARY')
  })

  it('disables every tab that arrives with M1b and says why', () => {
    const disabled = mountTabs().findAll('button[disabled]')
    expect(disabled.map((tab) => tab.text())).toEqual([
      'PROCESSES',
      'TIMELINE',
      'EVENTS',
      'NETWORK',
      'ARTIFACTS',
      'DETECTIONS',
      'NOTES',
    ])
    expect(disabled[0]!.attributes('title')).toBe('Arrives with M1b')
  })

  it('emits the key of the summary tab when it is clicked', async () => {
    const wrapper = mountTabs('processes')
    await wrapper.find('button:not([disabled])').trigger('click')
    expect(wrapper.emitted('select')).toEqual([['summary']])
  })

  it('does not emit for a disabled tab', async () => {
    const wrapper = mountTabs()
    await wrapper.find('button[disabled]').trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
  })
})
