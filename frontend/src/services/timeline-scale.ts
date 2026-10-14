/** A stretch of time in epoch milliseconds, both ends inclusive; the unit every timeline service works in. */
export interface Span {
  start: number
  end: number
}

export type ZoomPreset = 'fit' | '1m' | '10s' | '1s'

export const MIN_SPAN_MS = 10
const MIN_FULL_SPAN_MS = 1000
const FULL_SPAN_PADDING = 0.01
const WHEEL_SENSITIVITY = 0.0015
const MAX_WHEEL_FACTOR = 2
const PRESET_TOLERANCE_MS = 1

const PRESET_LENGTH_MS: Record<Exclude<ZoomPreset, 'fit'>, number> = { '1m': 60_000, '10s': 10_000, '1s': 1000 }
/** `fit` first: a short analysis that a longer preset would also fill is called fit. */
export const ZOOM_PRESETS: ZoomPreset[] = ['fit', '1m', '10s', '1s']

export function spanLength(span: Span): number {
  return span.end - span.start
}

export function timeToX(time: number, view: Span, width: number): number {
  const length = spanLength(view)
  return length === 0 ? 0 : ((time - view.start) / length) * width
}

export function xToTime(x: number, view: Span, width: number): number {
  return width <= 0 ? view.start : view.start + (x / width) * spanLength(view)
}

/** The range an analysis is drawn over: its first and last event with a little air, and never narrower than a second. */
export function paddedFullSpan(first: number, last: number): Span {
  const length = Math.max(MIN_FULL_SPAN_MS, (last - first) * (1 + 2 * FULL_SPAN_PADDING))
  const centre = (first + last) / 2
  return { start: centre - length / 2, end: centre + length / 2 }
}

function boundedLength(length: number, full: Span): number {
  const fullLength = spanLength(full)
  return Math.min(fullLength, Math.max(Math.min(MIN_SPAN_MS, fullLength), length))
}

function placed(start: number, length: number, full: Span): Span {
  const clamped = Math.min(Math.max(start, full.start), full.end - length)
  return { start: clamped, end: clamped + length }
}

/** `view` kept inside `full`: no longer than it, no shorter than the minimum, shifted rather than cut at an edge. */
export function clampView(view: Span, full: Span): Span {
  const length = boundedLength(spanLength(view), full)
  return placed(view.start, length, full)
}

/** `factor` is the new length over the old one, so below one zooms in; the time under the cursor stays under it. */
export function zoomAround(view: Span, full: Span, cursorTime: number, factor: number): Span {
  const length = spanLength(view)
  const nextLength = boundedLength(length * factor, full)
  const cursorShare = length === 0 ? 0.5 : (cursorTime - view.start) / length
  return placed(cursorTime - cursorShare * nextLength, nextLength, full)
}

/** One wheel step as a zoom factor: scrolling down zooms out. Capped so a large delta cannot jump to an extreme. */
export function wheelZoomFactor(deltaY: number): number {
  return Math.min(MAX_WHEEL_FACTOR, Math.max(1 / MAX_WHEEL_FACTOR, Math.exp(deltaY * WHEEL_SENSITIVITY)))
}

/** Dragging the content right shows earlier time. */
export function panByPixels(view: Span, full: Span, dx: number, width: number): Span {
  if (width <= 0) return view
  return panByFraction(view, full, -dx / width)
}

export function panByFraction(view: Span, full: Span, fraction: number): Span {
  return clampView({ start: view.start + fraction * spanLength(view), end: view.end + fraction * spanLength(view) }, full)
}

export function jumpTo(view: Span, full: Span, edge: 'start' | 'end'): Span {
  const length = spanLength(view)
  return edge === 'start' ? placed(full.start, length, full) : placed(full.end - length, length, full)
}

export function centreOn(view: Span, full: Span, time: number): Span {
  const length = spanLength(view)
  return placed(time - length / 2, length, full)
}

/** The preset's view, centred on `focus` when given and otherwise on the centre of the current view. */
export function applyPreset(preset: ZoomPreset, view: Span, full: Span, focus?: number): Span {
  if (preset === 'fit') return full
  const length = boundedLength(PRESET_LENGTH_MS[preset], full)
  const centre = focus ?? (view.start + view.end) / 2
  return placed(centre - length / 2, length, full)
}

function nearly(a: number, b: number): boolean {
  return Math.abs(a - b) <= PRESET_TOLERANCE_MS
}

/** The preset a view amounts to, or null for a view the wheel or a drag made. */
export function activePreset(view: Span, full: Span): ZoomPreset | null {
  if (nearly(view.start, full.start) && nearly(view.end, full.end)) return 'fit'
  return ZOOM_PRESETS.find((preset) => preset !== 'fit' && nearly(spanLength(view), PRESET_LENGTH_MS[preset])) ?? null
}

/** The overlap of two spans, a single instant when they only touch; null when they are apart. */
export function intersect(a: Span, b: Span): Span | null {
  const start = Math.max(a.start, b.start)
  const end = Math.min(a.end, b.end)
  return start <= end ? { start, end } : null
}

export function isWithin(span: Span, time: number, margin = 0): boolean {
  return time >= span.start - margin && time <= span.end + margin
}
