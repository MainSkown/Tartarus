import { describe, expect, it } from 'vitest'
import type { FilterChip } from '@/api'
import { facetChipAction, facetValueMark } from '@/services/facet-actions'

const CMD: FilterChip = { field: 'process.name', value: 'cmd.exe', negate: false }
const NOT_API: FilterChip = { field: 'api.name', value: 'NtDelayExecution', negate: true }

describe('facetChipAction', () => {
  it('adds a chip for a value that has none, in the direction asked', () => {
    expect(facetChipAction([], 'process.name', 'cmd.exe', false)).toEqual({ kind: 'add', chip: CMD })
    expect(facetChipAction([], 'process.name', 'cmd.exe', true)).toEqual({ kind: 'add', chip: { ...CMD, negate: true } })
  })

  it('removes the chip when an included value is chosen again', () => {
    expect(facetChipAction([NOT_API, CMD], 'process.name', 'cmd.exe', false)).toEqual({ kind: 'remove', index: 1 })
  })

  it('removes the chip when a negated value is chosen again to filter out', () => {
    expect(facetChipAction([NOT_API], 'api.name', 'NtDelayExecution', true)).toEqual({ kind: 'remove', index: 0 })
  })

  it('removes the chip when a negated value is clicked plainly, as the marked value is the thing to undo', () => {
    expect(facetChipAction([NOT_API], 'api.name', 'NtDelayExecution', false)).toEqual({ kind: 'remove', index: 0 })
  })

  it('turns an included value into a filter out when asked to filter it out', () => {
    expect(facetChipAction([CMD], 'process.name', 'cmd.exe', true)).toEqual({ kind: 'add', chip: { ...CMD, negate: true } })
  })

  it('does not mistake the same value of another field for the chip', () => {
    expect(facetChipAction([{ ...CMD, field: 'process.parent.name' }], 'process.name', 'cmd.exe', false).kind).toBe('add')
  })
})

describe('facetValueMark', () => {
  it('says whether a value is included, filtered out or untouched', () => {
    expect(facetValueMark([CMD, NOT_API], 'process.name', 'cmd.exe')).toBe('included')
    expect(facetValueMark([CMD, NOT_API], 'api.name', 'NtDelayExecution')).toBe('excluded')
    expect(facetValueMark([CMD, NOT_API], 'api.name', 'NtOpenFile')).toBeUndefined()
  })
})
