import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import type { RuleRead } from '@/api'
import RulesTable from '@/components/RulesTable.vue'
import { RULES, ruleFixture } from './rules-fixtures'

function mountTable(props: Partial<InstanceType<typeof RulesTable>['$props']> = {}) {
  return mount(RulesTable, {
    global: { plugins: [Quasar] },
    props: { rules: RULES, selectedId: undefined, togglingIds: new Set<string>(), ...props },
  })
}

const rows = (wrapper: ReturnType<typeof mountTable>) => wrapper.findAll('tbody tr')

describe('RulesTable columns', () => {
  it('has the columns of the spec, in order', () => {
    const headers = mountTable().findAll('thead th').map((th) => th.text())
    expect(headers).toEqual(['ENABLED', 'TITLE', 'LEVEL', 'LOGSOURCE', 'STATUS', 'PATH', 'HITS'])
  })

  it('lists one row per rule in the order given', () => {
    const titles = rows(mountTable()).map((row) => row.find('[data-cell="title"]').text())
    expect(titles).toEqual(RULES.map((rule) => rule.title))
  })

  it('shows the level as a severity badge, informational as INFO', () => {
    const wrapper = mountTable()
    const level = (index: number) => rows(wrapper)[index]!.find('[data-cell="level"]')
    expect(level(1).find('.severity-badge').text()).toContain('CRITICAL')
    expect(level(5).find('.severity-badge').text()).toContain('INFO')
  })

  it('shows a dash for a rule without a level', () => {
    const cell = rows(mountTable())[3]!.find('[data-cell="level"]')
    expect(cell.find('.severity-badge').exists()).toBe(false)
    expect(cell.text()).toBe('–')
  })

  it('shows the logsource category, or a dash when the rule has none', () => {
    const wrapper = mountTable()
    expect(rows(wrapper)[0]!.find('[data-cell="logsource"]').text()).toBe('create_remote_thread')
    expect(rows(wrapper)[5]!.find('[data-cell="logsource"]').text()).toBe('–')
  })

  it('shows the validity as a status badge', () => {
    const wrapper = mountTable()
    const badge = (index: number) => rows(wrapper)[index]!.find('[data-cell="validity"] .status-badge').text()
    expect(badge(0)).toContain('VALID')
    expect(badge(4)).toContain('INVALID')
    expect(badge(5)).toContain('UNSUPPORTED')
  })

  it('shows the hits with thousands separators, zero muted', () => {
    const wrapper = mountTable({ rules: [ruleFixture({ hits: 12345 }), ruleFixture({ id: 'z', hits: 0 })] })
    const [many, none] = rows(wrapper).map((row) => row.find('[data-cell="hits"]'))
    expect(many!.text()).toBe('12,345')
    expect(none!.text()).toBe('0')
    expect(none!.classes()).toContain('cell-empty')
    expect(many!.classes()).not.toContain('cell-empty')
  })

  it('shows the path without the shared rules directory', () => {
    const row = rows(mountTable())[4]!
    expect(row.find('[data-cell="path"]').text()).toBe('custom/echo.yml')
  })

  it('keeps a long title and a long path on one line, whole text in the title attribute', () => {
    const rule: RuleRead = ruleFixture({ title: 'T'.repeat(200), path: `/rules/sigma/custom/${'d/'.repeat(80)}x.yml` })
    const row = rows(mountTable({ rules: [rule] }))[0]!
    expect(row.find('[data-cell="title"] .cell-text').attributes('title')).toBe(rule.title)
    expect(row.find('[data-cell="path"] .cell-text').attributes('title')).toBe(rule.path)
  })
})

describe('RulesTable enabled switch', () => {
  const switchOf = (wrapper: ReturnType<typeof mountTable>, index: number) => rows(wrapper)[index]!.find('input[type="checkbox"]')

  it('is on for an enabled rule and off for a disabled one', () => {
    const wrapper = mountTable()
    expect((switchOf(wrapper, 0).element as HTMLInputElement).checked).toBe(true)
    expect((switchOf(wrapper, 5).element as HTMLInputElement).checked).toBe(false)
  })

  it('is a labelled switch', () => {
    const control = switchOf(mountTable(), 1)
    expect(control.attributes('role')).toBe('switch')
    expect(control.attributes('aria-label')).toBe('Enabled: Bravo rule')
  })

  it('asks to flip the rule when it is clicked', async () => {
    const wrapper = mountTable()
    await switchOf(wrapper, 1).setValue(false)
    expect(wrapper.emitted('toggle')).toEqual([['b', false]])
  })

  it('does not open the row', async () => {
    const wrapper = mountTable()
    await switchOf(wrapper, 1).trigger('click')
    await switchOf(wrapper, 1).trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toBeUndefined()
  })

  it.each([4, 5])('is locked for the invalid or unsupported rule at row %i, with the reason readable', (index) => {
    const wrapper = mountTable()
    const control = switchOf(wrapper, index)
    expect(control.attributes('disabled')).toBeDefined()
    const reasonId = control.attributes('aria-describedby')!
    expect(wrapper.find(`#${reasonId}`).text()).toContain('cannot run')
    expect(wrapper.find(`#${reasonId}`).text()).toContain(RULES[index]!.error!)
  })

  it('has no reason to read for a valid rule', () => {
    expect(switchOf(mountTable(), 0).attributes('aria-describedby')).toBeUndefined()
  })

  it('is locked while that rule is being saved', () => {
    const wrapper = mountTable({ togglingIds: new Set(['b']) })
    expect(switchOf(wrapper, 1).attributes('disabled')).toBeDefined()
    expect(switchOf(wrapper, 0).attributes('disabled')).toBeUndefined()
  })
})

describe('RulesTable rows', () => {
  it('opens a rule when its row is clicked or Enter is pressed on it', async () => {
    const wrapper = mountTable()
    await rows(wrapper)[2]!.trigger('click')
    await rows(wrapper)[3]!.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toEqual([['c'], ['d']])
  })

  it('makes every row reachable by keyboard', () => {
    for (const row of rows(mountTable())) expect(row.attributes('tabindex')).toBe('0')
  })

  it('marks the selected row', () => {
    const wrapper = mountTable({ selectedId: 'c' })
    expect(rows(wrapper).map((row) => row.attributes('aria-current'))).toEqual([undefined, undefined, 'true', undefined, undefined, undefined])
    expect(rows(wrapper)[2]!.classes()).toContain('rule-row--selected')
  })

  it('looks disabled for a rule that is switched off, not for one that is on', () => {
    const wrapper = mountTable()
    expect(rows(wrapper)[0]!.classes()).not.toContain('rule-row--disabled')
    expect(rows(wrapper)[4]!.classes()).toContain('rule-row--disabled')
  })
})
