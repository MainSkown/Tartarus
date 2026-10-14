import { mount } from '@vue/test-utils'
import { Quasar } from 'quasar'
import { describe, expect, it } from 'vitest'
import RuleDetailPane from '@/components/RuleDetailPane.vue'
import { RULES, RULE_YAML, ruleDetailFixture, ruleFixture } from './rules-fixtures'

type Props = InstanceType<typeof RuleDetailPane>['$props']

function mountPane(props: Partial<Props> = {}) {
  return mount(RuleDetailPane, {
    global: { plugins: [Quasar] },
    props: { rule: ruleFixture(), detail: ruleDetailFixture(), loading: false, error: undefined, ...props },
  })
}

describe('RuleDetailPane', () => {
  it('shows the rule: title, level, validity, description and where it comes from', () => {
    const wrapper = mountPane()
    expect(wrapper.find('.pane-heading').text()).toBe('RULE')
    expect(wrapper.find('.rule-detail__title').text()).toBe('Suspicious Remote Thread Creation')
    expect(wrapper.find('.severity-badge').text()).toContain('HIGH')
    expect(wrapper.find('.status-badge').text()).toContain('VALID')
    expect(wrapper.text()).toContain('Detects a remote thread created in a process that rarely receives one')
    expect(wrapper.find('.rule-detail__facts').text()).toContain('create_remote_thread')
    expect(wrapper.find('.rule-detail__facts').text()).toContain('/rules/sigma/default/create_remote_thread/')
    expect(wrapper.find('.rule-detail__facts').text()).toContain('attack.t1055')
  })

  it('shows the yaml read-only in a code block that scrolls and can be focused', () => {
    const code = mountPane().find('pre.code-block.rule-detail__yaml')
    expect(code.text()).toBe(RULE_YAML.trimEnd())
    expect(code.attributes('tabindex')).toBe('0')
    expect(code.attributes('aria-label')).toBe('Rule YAML')
  })

  it('has a button that copies the yaml', () => {
    const copy = mountPane().findAllComponents({ name: 'CopyButton' }).find((button) => button.props('what') === 'rule YAML')
    expect(copy?.props('text')).toBe(RULE_YAML)
  })

  it('copies the id and the path too', () => {
    const whats = mountPane().findAllComponents({ name: 'CopyButton' }).map((button) => button.props('what'))
    expect(whats).toEqual(expect.arrayContaining(['rule id', 'rule path', 'rule YAML']))
  })

  it('shows no error for a valid rule', () => {
    expect(mountPane().find('.rule-detail__error').exists()).toBe(false)
  })

  it.each([
    ['invalid', 'unknown field: Foo', RULES[4]!],
    ['unsupported', 'aggregation conditions (count(), near) are not supported', RULES[5]!],
  ])('shows the error of an %s rule prominently as an alert', (validity, error, rule) => {
    const wrapper = mountPane({ rule, detail: ruleDetailFixture({ ...rule }) })
    const alert = wrapper.find('.rule-detail__error')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain(validity.toUpperCase())
    expect(alert.text()).toContain(error)
  })

  it('still shows the yaml of an invalid rule beside its error', () => {
    const rule = RULES[4]!
    const wrapper = mountPane({ rule, detail: ruleDetailFixture({ ...rule, yaml: 'title: [broken' }) })
    expect(wrapper.find('.rule-detail__yaml').text()).toBe('title: [broken')
  })

  it('shows the header at once and a loader in place of the yaml while the file is read', () => {
    const wrapper = mountPane({ detail: undefined, loading: true })
    expect(wrapper.find('.rule-detail__title').text()).toBe('Suspicious Remote Thread Creation')
    expect(wrapper.find('.loader').exists()).toBe(true)
    expect(wrapper.find('.rule-detail__yaml').exists()).toBe(false)
  })

  it('says why the yaml is missing and offers a retry', async () => {
    const wrapper = mountPane({ detail: undefined, error: 'The file of rule rule-1 is not available' })
    expect(wrapper.text()).toContain('failed to load: The file of rule rule-1 is not available')
    await wrapper.find('.retry-btn').trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('asks to be closed', async () => {
    const wrapper = mountPane()
    await wrapper.find('.rule-detail__close').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('shows no level badge and says so when the rule has no description', () => {
    const wrapper = mountPane({ rule: ruleFixture({ level: null, logsource_category: null, description: null }) })
    expect(wrapper.find('.severity-badge').exists()).toBe(false)
    expect(wrapper.text()).toContain('no description')
  })
})
