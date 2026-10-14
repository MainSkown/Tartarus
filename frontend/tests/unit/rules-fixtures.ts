import type { RuleDetail, RuleRead } from '@/api'

export function ruleFixture(overrides: Partial<RuleRead> = {}): RuleRead {
  return {
    id: 'rule-1',
    title: 'Suspicious Remote Thread Creation',
    description: 'Detects a remote thread created in a process that rarely receives one',
    level: 'high',
    status: 'test',
    tags: ['attack.stealth', 'attack.t1055'],
    logsource_category: 'create_remote_thread',
    validity: 'valid',
    error: null,
    enabled: true,
    path: '/rules/sigma/default/create_remote_thread/create_remote_thread_win_susp_target.yml',
    hits: 3,
    ...overrides,
  }
}

export const RULE_YAML = `title: Suspicious Remote Thread Creation
id: rule-1
status: test
logsource:
    category: create_remote_thread
    product: windows
detection:
    selection:
        TargetImage|endswith: '\\\\lsass.exe'
    condition: selection
level: high
`

export function ruleDetailFixture(overrides: Partial<RuleDetail> = {}): RuleDetail {
  return { ...ruleFixture(), yaml: RULE_YAML, ...overrides }
}

export const RULES: RuleRead[] = [
  ruleFixture({ id: 'a', title: 'Alpha rule', level: 'low', hits: 0, path: '/rules/sigma/default/file/alpha.yml' }),
  ruleFixture({ id: 'b', title: 'Bravo rule', level: 'critical', hits: 12 }),
  ruleFixture({ id: 'c', title: 'Charlie rule', level: 'high', hits: 12 }),
  ruleFixture({ id: 'd', title: 'Delta rule', level: null, hits: 12 }),
  ruleFixture({
    id: 'e',
    title: 'Echo broken',
    level: 'medium',
    hits: 0,
    validity: 'invalid',
    error: 'unknown field: Foo',
    enabled: false,
    path: '/rules/sigma/custom/echo.yml',
  }),
  ruleFixture({
    id: 'f',
    title: 'Foxtrot correlation',
    level: 'informational',
    hits: 5,
    validity: 'unsupported',
    error: 'aggregation conditions (count(), near) are not supported',
    enabled: false,
    logsource_category: null,
  }),
]
