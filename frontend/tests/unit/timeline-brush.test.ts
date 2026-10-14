import { describe, expect, it } from 'vitest'
import { MIN_BRUSH_MS, MIN_BRUSH_PX, brushSpan, moveHandle, queryRangeToSpan, spanToQueryRange } from '@/services/timeline-brush'
import type { Span } from '@/services/timeline-scale'

const VIEW: Span = { start: 10_000, end: 20_000 }
const FULL: Span = { start: 0, end: 100_000 }
const WIDTH = 1000

describe('brushing a range on the axis', () => {
  it('turns a drag into the time between its two ends', () => {
    expect(brushSpan(100, 300, VIEW, WIDTH)).toEqual({ start: 11_000, end: 13_000 })
  })

  it('orders a drag to the left', () => {
    expect(brushSpan(300, 100, VIEW, WIDTH)).toEqual({ start: 11_000, end: 13_000 })
  })

  it('clamps a drag past either edge of the canvas to the visible range', () => {
    expect(brushSpan(500, 5000, VIEW, WIDTH)).toEqual({ start: 15_000, end: 20_000 })
    expect(brushSpan(500, -400, VIEW, WIDTH)).toEqual({ start: 10_000, end: 15_000 })
  })

  it('is not a brush when the pointer barely moved: that is a click', () => {
    expect(brushSpan(100, 100 + MIN_BRUSH_PX - 1, VIEW, WIDTH)).toBeNull()
    expect(brushSpan(100, 100 + MIN_BRUSH_PX, VIEW, WIDTH)).not.toBeNull()
  })

  it('rounds outward to whole milliseconds so the band covers what was dragged', () => {
    expect(brushSpan(0, 3, { start: 0, end: 1000 }, 1000)).toEqual({ start: 0, end: 3 })
    expect(brushSpan(1, 4.5, { start: 0, end: 1000 }, 1000)).toEqual({ start: 1, end: 5 })
  })

  it('keeps at least a millisecond at a deep zoom', () => {
    const deep: Span = { start: 5000, end: 5010 }
    const span = brushSpan(500, 500 + MIN_BRUSH_PX, deep, WIDTH)!
    expect(span.end - span.start).toBeGreaterThanOrEqual(MIN_BRUSH_MS)
  })

  it('works on a canvas one pixel wide, where almost nothing is a brush', () => {
    expect(brushSpan(0, 1, VIEW, 1)).toBeNull()
  })

  it('stays inside the full range even when the view is stale beyond it', () => {
    expect(brushSpan(0, 1000, { start: -5000, end: 5000 }, 1000, FULL)).toEqual({ start: 0, end: 5000 })
  })
})

describe('dragging a handle of the existing range', () => {
  const span: Span = { start: 12_000, end: 16_000 }

  it('moves the start to the pointer', () => {
    expect(moveHandle(span, 'start', 150, VIEW, WIDTH)).toEqual({ start: 11_500, end: 16_000 })
  })

  it('moves the end to the pointer', () => {
    expect(moveHandle(span, 'end', 900, VIEW, WIDTH)).toEqual({ start: 12_000, end: 19_000 })
  })

  it('cannot push the start past the end: they keep the minimum width and the dragged one stops', () => {
    expect(moveHandle(span, 'start', 900, VIEW, WIDTH)).toEqual({ start: 16_000 - MIN_BRUSH_MS, end: 16_000 })
    expect(moveHandle(span, 'end', 0, VIEW, WIDTH)).toEqual({ start: 12_000, end: 12_000 + MIN_BRUSH_MS })
  })

  it('clamps to the visible range at the canvas edges', () => {
    expect(moveHandle(span, 'start', -300, VIEW, WIDTH)).toEqual({ start: 10_000, end: 16_000 })
    expect(moveHandle(span, 'end', 5000, VIEW, WIDTH)).toEqual({ start: 12_000, end: 20_000 })
  })
})

describe('the range as query state', () => {
  it('writes ISO instants to the millisecond', () => {
    const start = Date.parse('2026-10-13T15:39:50.100Z')
    expect(spanToQueryRange({ start, end: start + 1234 })).toEqual({ from: '2026-10-13T15:39:50.100Z', to: '2026-10-13T15:39:51.334Z' })
  })

  it('rounds fractions outward', () => {
    expect(spanToQueryRange({ start: 1000.6, end: 2000.2 })).toEqual({ from: '1970-01-01T00:00:01.000Z', to: '1970-01-01T00:00:02.001Z' })
  })

  it('reads a closed range back to the same span', () => {
    const span: Span = { start: Date.parse('2026-10-13T15:39:50.100Z'), end: Date.parse('2026-10-13T15:40:00.000Z') }
    expect(queryRangeToSpan(spanToQueryRange(span), FULL)).toEqual(span)
  })

  it('reads an open end as the end of the full range', () => {
    expect(queryRangeToSpan({ from: '1970-01-01T00:00:10.000Z', to: null }, FULL)).toEqual({ start: 10_000, end: 100_000 })
    expect(queryRangeToSpan({ from: null, to: '1970-01-01T00:00:10.000Z' }, FULL)).toEqual({ start: 0, end: 10_000 })
  })

  it('reads nothing from a range with no ends, an unreadable end or an end before the start', () => {
    expect(queryRangeToSpan({ from: null, to: null }, FULL)).toBeNull()
    expect(queryRangeToSpan({ from: 'yesterday', to: null }, FULL)).toBeNull()
    expect(queryRangeToSpan({ from: '1970-01-01T00:00:10.000Z', to: '1970-01-01T00:00:05.000Z' }, FULL)).toBeNull()
  })

  it('reads a range outside the full range as it is, to be clipped when drawn', () => {
    expect(queryRangeToSpan({ from: '1970-01-01T00:10:00.000Z', to: '1970-01-01T00:20:00.000Z' }, FULL)).toEqual({ start: 600_000, end: 1_200_000 })
  })
})
