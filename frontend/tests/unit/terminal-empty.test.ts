import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import TerminalEmpty from '@/components/TerminalEmpty.vue'

describe('TerminalEmpty', () => {
  it('renders the default message in the terminal prompt style', () => {
    const wrapper = mount(TerminalEmpty, { global: { plugins: [Quasar] } })
    expect(wrapper.text()).toBe('> not implemented yet')
    expect(wrapper.classes()).toContain('text-mono')
  })

  it('renders a custom message, for a real empty state later', () => {
    const wrapper = mount(TerminalEmpty, {
      global: { plugins: [Quasar] },
      props: { message: 'no events match' },
    })
    expect(wrapper.text()).toBe('> no events match')
  })
})
