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

  it('keeps SUMMARY marked, and marks no disabled tab, when the active tab is not built yet', () => {
    const selected = mountTabs('events').findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['SUMMARY'])
  })

  it('keeps SUMMARY marked for a tab name that does not exist', () => {
    const selected = mountTabs('bogus').findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['SUMMARY'])
  })

  it('enables the four exploring tabs and disables the ones that arrive later, saying when', () => {
    const wrapper = mountTabs()
    const enabled = wrapper.findAll('button:not([disabled])').map((tab) => tab.text())
    expect(enabled).toEqual(['SUMMARY', 'PROCESSES', 'NETWORK', 'ARTIFACTS', 'DETECTIONS'])

    const disabled = wrapper.findAll('button[disabled]')
    expect(disabled.map((tab) => [tab.text(), tab.attributes('title')])).toEqual([
      ['TIMELINE', 'Arrives with M3'],
      ['EVENTS', 'Arrives with M3'],
      ['NOTES', 'Arrives with M4'],
    ])
  })

  it('marks an enabled tab as selected when it is the active one', () => {
    const selected = mountTabs('network').findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['NETWORK'])
  })

  it('emits the key of the tab that is clicked', async () => {
    const wrapper = mountTabs()
    await wrapper.findAll('button:not([disabled])')[1]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([['processes']])
  })

  it('does not emit for a disabled tab', async () => {
    const wrapper = mountTabs()
    await wrapper.find('button[disabled]').trigger('click')
    expect(wrapper.emitted('select')).toBeUndefined()
  })
})
