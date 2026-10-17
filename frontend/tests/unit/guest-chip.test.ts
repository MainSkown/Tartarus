import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GuestChip from '@/components/GuestChip.vue'

describe('GuestChip', () => {
  it('shows the guest name and each badge', () => {
    const wrapper = mount(GuestChip, { props: { name: 'lab1', badges: ['DEFENDER OFF', 'DECOYS'] } })
    expect(wrapper.find('.guest-chip__name').text()).toBe('lab1')
    expect(wrapper.findAll('.guest-chip__badge').map((badge) => badge.text())).toEqual(['DEFENDER OFF', 'DECOYS'])
  })

  it('shows the bare name for a guest with no badges, such as one deleted since', () => {
    const wrapper = mount(GuestChip, { props: { name: 'lab9', badges: [] } })
    expect(wrapper.find('.guest-chip__name').text()).toBe('lab9')
    expect(wrapper.find('.guest-chip__badge').exists()).toBe(false)
  })

  it('keeps the whole name reachable when it is cut off', () => {
    const name = `lab-${'x'.repeat(60)}`
    expect(mount(GuestChip, { props: { name } }).find('.guest-chip__name').attributes('title')).toBe(name)
  })

  it.each([null, undefined, ''])('renders nothing for the name %j, as on an analysis from before guests', (name) => {
    expect(mount(GuestChip, { props: { name } }).find('.guest-chip').exists()).toBe(false)
  })
})
