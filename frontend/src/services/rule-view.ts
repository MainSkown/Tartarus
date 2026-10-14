import type { RuleRead, Severity, Validity } from '@/api'
import { compareSeverity, type AnalysisStatusMeta } from '@/services/analysis-status'

/** Most severe first, the order the level filter lists them in. */
export const RULE_LEVELS = ['critical', 'high', 'medium', 'low', 'informational'] as const

export const VALIDITIES: Validity[] = ['valid', 'invalid', 'unsupported']

export interface RuleFilters {
  text: string
  level: string | null
  validity: Validity | null
}

type ValidityMeta = Pick<AnalysisStatusMeta, 'label' | 'color' | 'icon' | 'active'>

const VALIDITY_META: Record<Validity, ValidityMeta> = {
  valid: { label: 'VALID', color: '--status-success', icon: 'check_circle', active: false },
  invalid: { label: 'INVALID', color: '--status-critical', icon: 'error_outline', active: false },
  unsupported: { label: 'UNSUPPORTED', color: '--status-medium', icon: 'block', active: false },
}

const SEVERITY_BY_LEVEL: Record<(typeof RULE_LEVELS)[number], Severity> = {
  critical: 'critical',
  high: 'high',
  medium: 'medium',
  low: 'low',
  informational: 'info',
}

export function validityMeta(validity: Validity): ValidityMeta {
  return VALIDITY_META[validity]
}

/** A rule without a level, or one the scale does not know, has no severity to show. */
export function severityOfLevel(level: string | null): Severity | undefined {
  return (SEVERITY_BY_LEVEL as Record<string, Severity | undefined>)[level ?? '']
}

function compareLevels(a: string | null, b: string | null): number {
  const [first, second] = [severityOfLevel(a), severityOfLevel(b)]
  if (first === undefined || second === undefined) return Number(first !== undefined) - Number(second !== undefined)
  return compareSeverity(first, second)
}

/** Most hit first, then most severe, then by title, so the rules that matter lead the table. */
export function sortRules(rules: readonly RuleRead[]): RuleRead[] {
  return [...rules].sort(
    (a, b) =>
      b.hits - a.hits || compareLevels(b.level, a.level) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id),
  )
}

export function filterRules(rules: readonly RuleRead[], { text, level, validity }: RuleFilters): RuleRead[] {
  const needle = text.trim().toLowerCase()
  return rules.filter(
    (rule) =>
      (level === null || rule.level === level) &&
      (validity === null || rule.validity === validity) &&
      (needle === '' || [rule.title, rule.path, rule.id].some((field) => field.toLowerCase().includes(needle))),
  )
}

/** Why a rule's enabled switch is locked, or `undefined` when the analyst may flip it. */
export function toggleBlockedReason(rule: RuleRead): string | undefined {
  const because = rule.error ? `: ${rule.error}` : ''
  if (rule.validity === 'invalid') return `Invalid rule, it cannot run${because}`
  if (rule.validity === 'unsupported') return `Unsupported rule, the engine cannot run it${because}`
  return undefined
}

export function reloadSummary(rules: readonly RuleRead[]): string {
  const count = (validity: Validity) => rules.filter((rule) => rule.validity === validity).length
  const problems = (['invalid', 'unsupported'] as const)
    .filter((validity) => count(validity) > 0)
    .map((validity) => `${count(validity)} ${validity}`)
  const loaded = `Reloaded ${rules.length} ${rules.length === 1 ? 'rule' : 'rules'}`
  return problems.length > 0 ? `${loaded}: ${problems.join(', ')}` : loaded
}

const RULES_DIRECTORY = '/rules/sigma/'

/** A rule's path without the directory all of them share; the full path stays in the tooltip and the detail. */
export function shortPath(path: string): string {
  return path.startsWith(RULES_DIRECTORY) ? path.slice(RULES_DIRECTORY.length) : path
}
