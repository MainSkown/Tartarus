import type { FilterChip } from '@/api'
import { isSameFilter } from '@/services/query-url'

export type FacetChipAction = { kind: 'add'; chip: FilterChip } | { kind: 'remove'; index: number } | { kind: 'toggle'; index: number }

/**
 * What choosing a facet value does to the chips. A value with no chip gets one in the direction
 * asked. A marked value is undone by choosing it the way it is marked, or by a plain click either
 * way; only "filter out" on an included value turns it around. `chips` must name fields canonically
 * (an alias resolved to its catalog name) so a chip typed as `proc:cmd.exe` counts as `process.name`.
 */
export function facetChipAction(chips: FilterChip[], field: string, value: string, negate: boolean): FacetChipAction {
  const wanted: FilterChip = { field, value, negate }
  const index = chips.findIndex((chip) => isSameFilter(chip, wanted))
  if (index < 0) return { kind: 'add', chip: wanted }
  const existing = chips[index]!
  return negate && !existing.negate ? { kind: 'toggle', index } : { kind: 'remove', index }
}

export function facetValueMark(chips: FilterChip[], field: string, value: string): 'included' | 'excluded' | undefined {
  const chip = chips.find((known) => isSameFilter(known, { field, value, negate: false }))
  if (!chip) return undefined
  return chip.negate ? 'excluded' : 'included'
}
