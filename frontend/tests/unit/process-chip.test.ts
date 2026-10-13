import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ProcessChip from '@/components/ProcessChip.vue'

describe('ProcessChip', () => {
  it('shows the name and the pid', () => {
    const wrapper = mount(ProcessChip, { props: { process: { pid: 9708, name: 'benign.exe' } } })
    expect(wrapper.text()).toBe('benign.exe (9708)')
  })

  it('shows just the pid when the name is not known', () => {
    const wrapper = mount(ProcessChip, { props: { process: { pid: 42, name: null } } })
    expect(wrapper.text()).toBe('pid 42')
  })

  it('shows a dash for an event with no process', () => {
    const wrapper = mount(ProcessChip, { props: { process: null } })
    expect(wrapper.text()).toBe('–')
  })

  it('keeps a long name on one line and puts the full text in the title', () => {
    const name = `${'x'.repeat(80)}.exe`
    const wrapper = mount(ProcessChip, { props: { process: { pid: 1, name } } })
    expect(wrapper.attributes('title')).toBe(`${name} (1)`)
  })
})
