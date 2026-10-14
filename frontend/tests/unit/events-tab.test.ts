import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import EventsTab from '@/components/tabs/EventsTab.vue'
import { useQueryStateStore } from '@/stores/query-state'
import { analysisWithStatus } from './analysis-fixtures'

function mountTab() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useQueryStateStore()
  const wrapper = mount(EventsTab, { props: { analysis: analysisWithStatus('done') }, global: { plugins: [pinia] } })
  return { wrapper, store }
}

describe('EventsTab placeholder', () => {
  it('says the table is built next', () => {
    expect(mountTab().wrapper.text()).toContain('the events table is built next')
  })

  it('shows the filter the bar has built as the search request would carry it', async () => {
    const { wrapper, store } = mountTab()
    expect(JSON.parse(wrapper.find('pre.code-block').text())).toEqual({})

    store.setText('lane:file')
    store.addChip({ field: 'process.name', value: 'cmd.exe', negate: true })
    await wrapper.vm.$nextTick()
    expect(JSON.parse(wrapper.find('pre.code-block').text())).toEqual({
      query: 'lane:file',
      filters: [{ field: 'process.name', value: 'cmd.exe', negate: true }],
    })
  })
})
