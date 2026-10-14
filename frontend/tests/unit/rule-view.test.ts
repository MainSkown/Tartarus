import { describe, expect, it } from 'vitest'
import {
  RULE_LEVELS,
  filterRules,
  reloadSummary,
  severityOfLevel,
  sortRules,
  shortPath,
  toggleBlockedReason,
  validityMeta,
} from '@/services/rule-view'
import { RULES, ruleFixture } from './rules-fixtures'

const ids = (rules: { id: string }[]) => rules.map((rule) => rule.id)

describe('severityOfLevel', () => {
  it('maps the Sigma levels onto the severity scale, informational onto info', () => {
    expect(['informational', 'low', 'medium', 'high', 'critical'].map(severityOfLevel)).toEqual([
      'info',
      'low',
      'medium',
      'high',
      'critical',
    ])
  })

  it('has no severity for a rule without a level or with one it does not know', () => {
    expect(severityOfLevel(null)).toBeUndefined()
    expect(severityOfLevel('catastrophic')).toBeUndefined()
  })

  it('lists the levels most severe first for the filter', () => {
    expect(RULE_LEVELS).toEqual(['critical', 'high', 'medium', 'low', 'informational'])
  })
})

describe('sortRules', () => {
  it('puts the most hit first, then the most severe level, then the title', () => {
    expect(ids(sortRules(RULES))).toEqual(['b', 'c', 'd', 'f', 'e', 'a'])
  })

  it('does not reorder the list it is given', () => {
    const before = ids(RULES)
    sortRules(RULES)
    expect(ids(RULES)).toEqual(before)
  })
})

describe('filterRules', () => {
  const none = { text: '', level: null, validity: null }

  it('keeps everything when no filter is set', () => {
    expect(filterRules(RULES, none)).toHaveLength(RULES.length)
  })

  it('filters by level', () => {
    expect(ids(filterRules(RULES, { ...none, level: 'high' }))).toEqual(['c'])
  })

  it('filters by validity', () => {
    expect(ids(filterRules(RULES, { ...none, validity: 'unsupported' }))).toEqual(['f'])
  })

  it('matches the text against the title, ignoring case', () => {
    expect(ids(filterRules(RULES, { ...none, text: 'echo BROKEN' }))).toEqual(['e'])
  })

  it('matches the text against the path', () => {
    expect(ids(filterRules(RULES, { ...none, text: 'sigma/custom' }))).toEqual(['e'])
  })

  it('matches the id even when the title and path do not contain the text', () => {
    const rules = [ruleFixture({ id: 'deadbeef-0001', title: 'x', path: '/p.yml' }), ruleFixture({ id: 'other', title: 'y', path: '/q.yml' })]
    expect(ids(filterRules(rules, { ...none, text: 'DEADBEEF' }))).toEqual(['deadbeef-0001'])
  })

  it('ignores surrounding whitespace in the text', () => {
    expect(ids(filterRules(RULES, { ...none, text: '  echo  ' }))).toEqual(['e'])
  })

  it('applies every filter together', () => {
    expect(filterRules(RULES, { text: 'rule', level: 'high', validity: 'invalid' })).toEqual([])
  })
})

describe('validityMeta', () => {
  it('gives each validity a label, an icon and a status colour', () => {
    expect(validityMeta('valid')).toMatchObject({ label: 'VALID', color: '--status-success' })
    expect(validityMeta('invalid')).toMatchObject({ label: 'INVALID', color: '--status-critical' })
    expect(validityMeta('unsupported')).toMatchObject({ label: 'UNSUPPORTED', color: '--status-medium' })
    for (const validity of ['valid', 'invalid', 'unsupported'] as const) {
      expect(validityMeta(validity).icon).not.toBe('')
      expect(validityMeta(validity).active).toBe(false)
    }
  })
})

describe('toggleBlockedReason', () => {
  it('has none for a valid rule', () => {
    expect(toggleBlockedReason(ruleFixture())).toBeUndefined()
  })

  it('says an invalid rule cannot run and shows its error', () => {
    expect(toggleBlockedReason(ruleFixture({ validity: 'invalid', error: 'unknown field: Foo' }))).toBe(
      'Invalid rule, it cannot run: unknown field: Foo',
    )
  })

  it('says an unsupported rule cannot run', () => {
    expect(toggleBlockedReason(ruleFixture({ validity: 'unsupported', error: 'aggregation not supported' }))).toBe(
      'Unsupported rule, the engine cannot run it: aggregation not supported',
    )
  })

  it('copes with a missing error', () => {
    expect(toggleBlockedReason(ruleFixture({ validity: 'invalid', error: null }))).toBe('Invalid rule, it cannot run')
  })
})

describe('reloadSummary', () => {
  it('counts the rules', () => {
    expect(reloadSummary([ruleFixture(), ruleFixture()])).toBe('Reloaded 2 rules')
  })

  it('says one rule in the singular', () => {
    expect(reloadSummary([ruleFixture()])).toBe('Reloaded 1 rule')
  })

  it('adds how many are invalid and unsupported, only when there are any', () => {
    expect(reloadSummary(RULES)).toBe('Reloaded 6 rules: 1 invalid, 1 unsupported')
    expect(reloadSummary([ruleFixture({ validity: 'invalid' })])).toBe('Reloaded 1 rule: 1 invalid')
  })

  it('handles an empty directory', () => {
    expect(reloadSummary([])).toBe('Reloaded 0 rules')
  })
})

describe('shortPath', () => {
  it('drops the rules directory every path starts with, so the part that tells rules apart fits', () => {
    expect(shortPath('/rules/sigma/default/dns_query/dns_query_win_x.yml')).toBe('default/dns_query/dns_query_win_x.yml')
    expect(shortPath('/rules/sigma/custom/mine.yml')).toBe('custom/mine.yml')
  })

  it('leaves a path from anywhere else whole', () => {
    expect(shortPath('/srv/other/rule.yml')).toBe('/srv/other/rule.yml')
  })
})
