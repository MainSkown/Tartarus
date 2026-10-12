import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import PlaceholderPage from '@/pages/PlaceholderPage.vue'

describe('PlaceholderPage', () => {
  it('tells the user the page is not implemented yet, in the terminal voice', () => {
    const wrapper = mount(PlaceholderPage, { global: { plugins: [Quasar] } })
    expect(wrapper.text()).toBe('> not implemented yet')
    expect(wrapper.classes()).toContain('text-mono')
  })
})
