import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import RelatedEventList from '@/components/RelatedEventList.vue'
import { eventFixture } from './events-fixtures'

const ITEMS = [
  eventFixture({ id: 'r1', time: '2026-10-13T15:39:34.123Z', lane: 'file', action: 'file-written', summary: 'cmd.exe wrote a.ps1' }),
  eventFixture({ id: 'r2', time: '2026-10-13T15:39:35.500Z', lane: 'api', action: 'NtWriteFile', summary: 'NtWriteFile → 0' }),
]

function mountList(total = 2, title = 'REFERENCES') {
  return mount(RelatedEventList, { props: { title, listing: { items: ITEMS, total } }, global: { plugins: [Quasar] } })
}

describe('RelatedEventList', () => {
  it('has the title with how many events there are', () => {
    expect(mountList().find('.related-list__heading').text()).toContain('REFERENCES')
    expect(mountList().find('.related-list__heading').text()).toContain('2')
  })

  it('says how many of the total are shown when the list was cut', () => {
    expect(mountList(120).find('.related-list__heading').text()).toContain('showing 2 of 120')
  })

  it('shows the time, the lane icon, the action and the summary of each event', () => {
    const row = mountList().findAll('.related-event')[0]!
    expect(row.text()).toContain('15:39:34.123')
    expect(row.find('.q-icon').text()).toBe('description')
    expect(row.text()).toContain('file-written')
    expect(row.text()).toContain('cmd.exe wrote a.ps1')
  })

  it('opens the event that is clicked', async () => {
    const wrapper = mountList()
    await wrapper.findAll('.related-event')[1]!.trigger('click')
    expect(wrapper.emitted('open')).toEqual([['r2']])
  })

  it('shows nothing for an empty list', () => {
    const wrapper = mount(RelatedEventList, { props: { title: 'X', listing: { items: [], total: 0 } }, global: { plugins: [Quasar] } })
    expect(wrapper.html()).toBe('<!--v-if-->')
  })
})
