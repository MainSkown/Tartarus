import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import GuestStateList from '@/components/guest/GuestStateList.vue'
import { guestStateMeta } from '@/services/guest-state'
import { guestFixture } from './guest-fixtures'

function mountList(guests = [guestFixture(), guestFixture({ name: 'lab2', state: 'failed', badges: ['DEFENDER OFF'] })]) {
  return mount(GuestStateList, { global: { plugins: [Quasar] }, props: { guests } })
}

describe('GuestStateList', () => {
  it('lists every guest with its name, state and badges', () => {
    const rows = mountList().findAll('.guest-state-list__row')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('lab1')
    expect(rows[0]!.text()).toContain('READY')
    expect(rows[0]!.text()).toContain('DEFENDER ON')
    expect(rows[1]!.text()).toContain('lab2')
    expect(rows[1]!.text()).toContain('FAILED')
    expect(rows[1]!.text()).toContain('DEFENDER OFF')
  })

  it('uses the shared state look: the icon of the state beside the label', () => {
    const wrapper = mountList()
    expect(wrapper.find('li .q-icon').text()).toBe(guestStateMeta('ready').icon)
  })

  it('says so when there is no guest', () => {
    const wrapper = mountList([])
    expect(wrapper.text()).toContain('no guests')
    expect(wrapper.find('.guest-state-list__row').exists()).toBe(false)
  })

  it('shortens nothing: a long name stays whole in the title', () => {
    const name = 'a-very-long-guest-name-of-thirty-two'
    const wrapper = mountList([guestFixture({ name })])
    expect(wrapper.find('.guest-state-list__name').attributes('title')).toBe(name)
  })
})
