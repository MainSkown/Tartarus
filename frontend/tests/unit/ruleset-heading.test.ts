import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RulesetHeading from '@/components/RulesetHeading.vue'

describe('RulesetHeading', () => {
  it.each([
    ['cape', 'CAPE'],
    ['sigma', 'SIGMA'],
    ['unheard-of', 'UNHEARD-OF'],
  ])('labels the %s ruleset as %s', (ruleset, label) => {
    const wrapper = mount(RulesetHeading, { props: { ruleset } })
    expect(wrapper.text()).toBe(label)
    expect(wrapper.classes()).toContain('ruleset-heading')
  })
})
