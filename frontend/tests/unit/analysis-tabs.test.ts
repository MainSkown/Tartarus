import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AnalysisTabs from '@/components/AnalysisTabs.vue'
import { listUnbuiltTab, UNBUILT_TAB } from './unbuilt-tab'

listUnbuiltTab()

function mountTabs(active = 'summary', live = false) {
  return mount(AnalysisTabs, { props: { active, live } })
}

describe('AnalysisTabs', () => {
  it('marks the active tab as selected', () => {
    const selected = mountTabs().findAll('[aria-selected="true"]')
    expect(selected).toHaveLength(1)
    expect(selected[0]!.text()).toBe('SUMMARY')
  })

  it('keeps SUMMARY marked, and marks no disabled tab, when the active tab is not built yet', () => {
    const selected = mountTabs(UNBUILT_TAB).findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['SUMMARY'])
  })

  it('keeps SUMMARY marked for a tab name that does not exist', () => {
    const selected = mountTabs('bogus').findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['SUMMARY'])
  })

  it('enables the built tabs and disables the ones that arrive later, saying when', () => {
    const wrapper = mountTabs()
    const enabled = wrapper.findAll('button:not([disabled])').map((tab) => tab.text())
    expect(enabled).toEqual(['SUMMARY', 'PROCESSES', 'TIMELINE', 'EVENTS', 'NETWORK', 'ARTIFACTS', 'DETECTIONS', 'NOTES'])

    const disabled = wrapper.findAll('button[disabled]')
    expect(disabled.map((tab) => [tab.text(), tab.attributes('title')])).toEqual([
      ['LATER', 'Arrives with M9'],
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

  it('has no LIVE tab outside a live session', () => {
    expect(mountTabs().findAll('button').map((tab) => tab.text())).not.toContain('LIVE')
  })

  it('lists LIVE first, enabled, during a live session', () => {
    const tabs = mountTabs('summary', true).findAll('button')
    expect(tabs[0]!.text()).toBe('LIVE')
    expect(tabs[0]!.attributes('disabled')).toBeUndefined()
  })

  it('marks LIVE selected when it is the active tab of a live session', () => {
    const selected = mountTabs('live', true).findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['LIVE'])
  })

  it('marks SUMMARY, not LIVE, when LIVE is asked for outside a live session', () => {
    const selected = mountTabs('live', false).findAll('[aria-selected="true"]')
    expect(selected.map((tab) => tab.text())).toEqual(['SUMMARY'])
  })

  it('emits live when LIVE is clicked', async () => {
    const wrapper = mountTabs('summary', true)
    await wrapper.findAll('button')[0]!.trigger('click')
    expect(wrapper.emitted('select')).toEqual([['live']])
  })
})
