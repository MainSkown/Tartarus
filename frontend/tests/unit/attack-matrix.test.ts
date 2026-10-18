import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import AttackMatrix from '@/components/AttackMatrix.vue'
import { ATTACK_MATRIX } from './detections-fixtures'

function mountMatrix() {
  return mount(AttackMatrix, { global: { plugins: [Quasar] }, props: { matrix: ATTACK_MATRIX } })
}

describe('AttackMatrix', () => {
  it('has one column per tactic, in the order given', () => {
    const names = mountMatrix()
      .findAll('.attack-tactic__name')
      .map((name) => name.text())
    expect(names).toEqual(['Execution', 'Privilege Escalation', 'Stealth', 'Command and Control', 'Unknown'])
  })

  it('shows the name, the id and the hit count of a technique', () => {
    const cell = mountMatrix().findAll('.attack-cell')[1]!
    expect(cell.text()).toContain('Process Injection')
    expect(cell.text()).toContain('T1055')
    expect(cell.find('.attack-cell__count').text()).toBe('2')
  })

  it('colours a cell with its severity and says the severity in words', () => {
    const cell = mountMatrix().findAll('.attack-cell')[1]!
    expect(cell.attributes('style')).toContain('--status-critical')
    expect(cell.attributes('aria-label')).toContain('critical')
  })

  it('shows a technique without a name by its id alone', () => {
    const cell = mountMatrix().findAll('.attack-cell').at(-1)!
    expect(cell.find('.attack-cell__name').exists()).toBe(false)
    expect(cell.text()).toContain('T1999')
  })

  it('reads a named technique cell as id, name, hits and severity', () => {
    const cell = mountMatrix().findAll('.attack-cell')[1]!
    expect(cell.attributes('aria-label')).toBe('T1055, Process Injection, 2 hits, critical severity')
  })

  it('reads an unnamed technique cell as id, hits and severity', () => {
    const cell = mountMatrix().findAll('.attack-cell').at(-1)!
    expect(cell.attributes('aria-label')).toBe('T1999, 1 hit, low severity')
  })

  it('tells which technique was clicked', async () => {
    const wrapper = mountMatrix()
    await wrapper.findAll('.attack-cell')[1]!.trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ id: 'T1055' })
  })

  it('names the ATT&CK version the ids come from', () => {
    expect(mountMatrix().text()).toContain('ATT&CK v19.2')
  })
})
