import { describe, expect, it } from 'vitest'
import { NO_EVENTS } from '@/services/range-override'
import { tableRangeFor } from '@/services/timeline-table-range'
import type { Span } from '@/services/timeline-scale'

const iso = (ms: number): string => new Date(ms).toISOString()
const FULL: Span = { start: 1_000_000, end: 1_100_000 }

describe('the range the table below the timeline is restricted to', () => {
  it('is nothing before there is a view or a full range', () => {
    expect(tableRangeFor(null, FULL, null)).toBeNull()
    expect(tableRangeFor(FULL, null, null)).toBeNull()
  })

  it('adds no restriction at the fit view, with or without a chip: the shared range applies as it is', () => {
    expect(tableRangeFor(FULL, FULL, null)).toBeNull()
    expect(tableRangeFor(FULL, FULL, { from: iso(1_020_000), to: iso(1_030_000) })).toBeNull()
  })

  it('is the visible range when zoomed in and there is no chip', () => {
    const view = { start: 1_020_000, end: 1_030_000 }
    expect(tableRangeFor(view, FULL, null)).toEqual({ from: iso(1_020_000), to: iso(1_030_000) })
  })

  it('is the part of the visible range that the chip covers', () => {
    const view = { start: 1_020_000, end: 1_040_000 }
    expect(tableRangeFor(view, FULL, { from: iso(1_030_000), to: iso(1_090_000) })).toEqual({ from: iso(1_030_000), to: iso(1_040_000) })
    expect(tableRangeFor(view, FULL, { from: iso(1_000_000), to: iso(1_025_000) })).toEqual({ from: iso(1_020_000), to: iso(1_025_000) })
  })

  it('is the visible range when the chip covers all of it', () => {
    const view = { start: 1_020_000, end: 1_040_000 }
    expect(tableRangeFor(view, FULL, { from: iso(1_000_000), to: iso(1_090_000) })).toEqual({ from: iso(1_020_000), to: iso(1_040_000) })
  })

  it('reads a chip with one end as running to the end of the analysis', () => {
    const view = { start: 1_020_000, end: 1_040_000 }
    expect(tableRangeFor(view, FULL, { from: iso(1_030_000), to: null })).toEqual({ from: iso(1_030_000), to: iso(1_040_000) })
    expect(tableRangeFor(view, FULL, { from: null, to: iso(1_030_000) })).toEqual({ from: iso(1_020_000), to: iso(1_030_000) })
  })

  it('has no event in it when the visible range and the chip do not meet', () => {
    const view = { start: 1_020_000, end: 1_030_000 }
    expect(tableRangeFor(view, FULL, { from: iso(1_050_000), to: iso(1_060_000) })).toBe(NO_EVENTS)
  })

  it('ignores a chip that cannot be read', () => {
    const view = { start: 1_020_000, end: 1_030_000 }
    expect(tableRangeFor(view, FULL, { from: 'garbage', to: null })).toEqual({ from: iso(1_020_000), to: iso(1_030_000) })
  })

  it('rounds the view outward to whole milliseconds', () => {
    expect(tableRangeFor({ start: 1_020_000.4, end: 1_030_000.6 }, FULL, null)).toEqual({ from: iso(1_020_000), to: iso(1_030_001) })
  })
})
