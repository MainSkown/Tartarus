import type { QueryTimeRange } from '@/services/query-url'
import { intersect, type Span, xToTime } from '@/services/timeline-scale'

export const MIN_BRUSH_PX = 3
export const MIN_BRUSH_MS = 1

export type RangeHandle = 'start' | 'end'

function timeAtClamped(x: number, view: Span, width: number): number {
  return xToTime(Math.min(Math.max(x, 0), width), view, width)
}

/** The time a drag on the axis covers (x in the plot's own pixels), or null while it is still just a click. */
export function brushSpan(anchorX: number, currentX: number, view: Span, width: number, full?: Span): Span | null {
  if (Math.abs(currentX - anchorX) < MIN_BRUSH_PX) return null
  const a = timeAtClamped(anchorX, view, width)
  const b = timeAtClamped(currentX, view, width)
  const brushed = { start: Math.floor(Math.min(a, b)), end: Math.ceil(Math.max(a, b)) }
  const inside = full ? intersect(brushed, full) : brushed
  if (inside === null) return null
  return { start: inside.start, end: Math.max(inside.end, inside.start + MIN_BRUSH_MS) }
}

/** `span` with one end dragged to the pointer; the ends never cross, the dragged one stops a millisecond short. */
export function moveHandle(span: Span, handle: RangeHandle, x: number, view: Span, width: number): Span {
  const time = timeAtClamped(x, view, width)
  return handle === 'start'
    ? { start: Math.min(Math.floor(time), span.end - MIN_BRUSH_MS), end: span.end }
    : { start: span.start, end: Math.max(Math.ceil(time), span.start + MIN_BRUSH_MS) }
}

export function spanToQueryRange(span: Span): QueryTimeRange {
  return { from: new Date(Math.floor(span.start)).toISOString(), to: new Date(Math.ceil(span.end)).toISOString() }
}

function instant(iso: string | null): number | undefined {
  if (iso === null) return undefined
  const time = Date.parse(iso)
  return Number.isNaN(time) ? Number.NaN : time
}

/** The span a time-range chip covers; an open end runs to the end of `full`. Null when it names no usable range. */
export function queryRangeToSpan(range: QueryTimeRange, full: Span): Span | null {
  const from = instant(range.from)
  const to = instant(range.to)
  if (Number.isNaN(from) || Number.isNaN(to) || (from === undefined && to === undefined)) return null
  const span = { start: from ?? full.start, end: to ?? full.end }
  return span.start <= span.end ? span : null
}
