import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GuestOptionRow from '@/components/GuestOptionRow.vue'

const READY = { name: 'lab1', badges: ['DEFENDER OFF'], profileName: 'Windows 11', disabled: false }

describe('GuestOptionRow', () => {
  it('shows the guest chip and the profile name', () => {
    const wrapper = mount(GuestOptionRow, { props: { option: READY } })
    expect(wrapper.find('.guest-chip__name').text()).toBe('lab1')
    expect(wrapper.find('.guest-chip__badge').text()).toBe('DEFENDER OFF')
    expect(wrapper.find('.guest-option-row__profile').text()).toBe('Windows 11')
    expect(wrapper.find('.guest-option-row__reason').exists()).toBe(false)
  })

  it('gives the reason a guest cannot be chosen', () => {
    const wrapper = mount(GuestOptionRow, { props: { option: { ...READY, disabled: true, reason: 'building' } } })
    expect(wrapper.find('.guest-option-row__reason').text()).toBe('building')
  })

  it('leaves the profile out while the profiles have not loaded', () => {
    const wrapper = mount(GuestOptionRow, { props: { option: { ...READY, profileName: undefined } } })
    expect(wrapper.find('.guest-option-row__profile').exists()).toBe(false)
  })

  it('marks a guest that is running or has a queued analysis as busy', () => {
    const wrapper = mount(GuestOptionRow, { props: { option: { ...READY, busy: true } } })
    expect(wrapper.find('.guest-option-row__busy').text()).toBe('busy')
  })

  it('shows no busy marker for a free guest', () => {
    const wrapper = mount(GuestOptionRow, { props: { option: READY } })
    expect(wrapper.find('.guest-option-row__busy').exists()).toBe(false)
  })
})
