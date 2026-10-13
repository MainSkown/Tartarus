import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import ProcessViewSwitch from '@/components/ProcessViewSwitch.vue'

function mountSwitch(mode: 'graph' | 'tree' = 'graph', total = 2) {
  return mount(ProcessViewSwitch, { global: { plugins: [Quasar] }, props: { modelValue: mode, total } })
}

describe('ProcessViewSwitch', () => {
  it('shows how many processes there are, small and gray', () => {
    const wrapper = mountSwitch('graph', 341)

    expect(wrapper.get('.process-view-switch__count').text()).toBe('341 processes')
  })

  it('says "1 process" for a single one', () => {
    expect(mountSwitch('graph', 1).get('.process-view-switch__count').text()).toBe('1 process')
  })

  it('offers the graph and the tree and asks for the one that was clicked', async () => {
    const wrapper = mountSwitch('graph')
    const buttons = wrapper.findAll('.q-btn-toggle button')
    expect(buttons.map((button) => button.text())).toEqual(['GRAPH', 'TREE'])

    await buttons[1]!.trigger('click')

    expect(wrapper.emitted('update:modelValue')).toEqual([['tree']])
  })
})
