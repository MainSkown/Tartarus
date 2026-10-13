import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import ProcessTreeList from '@/components/ProcessTreeList.vue'
import SeverityBadge from '@/components/SeverityBadge.vue'
import { sampleTree } from './process-fixtures'

const { roots } = sampleTree()
const ROOT = roots[0]!.entity_id
const CHILD = roots[0]!.children[0]!.entity_id

function mountTree(selectedId: string | undefined = ROOT) {
  return mount(ProcessTreeList, { global: { plugins: [Quasar] }, props: { roots, selectedId } })
}

describe('ProcessTreeList', () => {
  it('shows every process, children indented under their parent, all expanded', () => {
    const wrapper = mountTree()

    const rows = wrapper.findAll('.q-tree__node-header').map((row) => row.text())
    expect(rows[0]).toContain('benign.exe (9708)')
    expect(rows[1]).toContain('cmd.exe (2476)')
    expect(wrapper.findAll('.q-tree__children .q-tree__node-header')).toHaveLength(1)
  })

  it('shows the worst severity and the detection count of each process with detections', () => {
    const wrapper = mountTree()

    const badges = wrapper.findAllComponents(SeverityBadge)
    expect(badges.map((badge) => badge.props())).toEqual([
      { severity: 'high', count: 5 },
      { severity: 'medium', count: 2 },
    ])
  })

  it('marks the selected process', () => {
    const wrapper = mountTree(CHILD)

    const selected = wrapper.findAll('.q-tree__node--selected')
    expect(selected).toHaveLength(1)
    expect(selected[0]!.text()).toContain('cmd.exe (2476)')
  })

  it('asks for the process whose row was clicked', async () => {
    const wrapper = mountTree()

    await wrapper.findAll('.q-tree__node-header')[1]!.trigger('click')

    expect(wrapper.emitted('select')).toEqual([[CHILD]])
  })

  it('keeps the selection when the selected row is clicked again', async () => {
    const wrapper = mountTree()

    await wrapper.findAll('.q-tree__node-header')[0]!.trigger('click')

    expect(wrapper.emitted('select')).toBeUndefined()
  })
})
