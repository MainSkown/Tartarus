import { formatDuration } from '@/services/format-duration'
import type { Span } from '@/services/timeline-scale'
import { spanLength } from '@/services/timeline-scale'

export interface Tick {
  time: number
  label: string
}

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR
export const TICK_STEPS_MS = [
  1, 2, 5, 10, 20, 50, 100, 200, 500,
  SECOND, 2 * SECOND, 5 * SECOND, 10 * SECOND, 15 * SECOND, 30 * SECOND,
  MINUTE, 2 * MINUTE, 5 * MINUTE, 10 * MINUTE, 15 * MINUTE, 30 * MINUTE,
  HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR,
  DAY,
]
/** Wide enough for the longest label (`HH:mm:ss.SSS` in the mono axis font) with air on both sides. */
export const MIN_TICK_DISTANCE_PX = 90

const pad = (value: number, length = 2): string => String(value).padStart(length, '0')

/** The smallest step whose ticks are at least `minDistancePx` apart on a canvas `width` wide showing `spanMs`. */
export function tickStep(spanMs: number, width: number, minDistancePx = MIN_TICK_DISTANCE_PX): number {
  const longest = TICK_STEPS_MS[TICK_STEPS_MS.length - 1]!
  if (width <= 0) return longest
  if (spanMs <= 0) return TICK_STEPS_MS[0]!
  const wanted = (minDistancePx / width) * spanMs
  return TICK_STEPS_MS.find((step) => step >= wanted) ?? longest
}

/** A tick label in UTC with just the precision `stepMs` needs, so neighbouring labels differ in what they show. */
export function formatTickLabel(time: number, stepMs: number): string {
  const date = new Date(time)
  const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`
  const hourMinute = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`
  const seconds = `${hourMinute}:${pad(date.getUTCSeconds())}`
  const milliseconds = pad(date.getUTCMilliseconds(), 3)
  if (stepMs >= DAY) return day
  if (stepMs >= MINUTE) return hourMinute
  if (stepMs >= SECOND) return seconds
  if (stepMs >= 100) return `${seconds}.${milliseconds.slice(0, 1)}`
  if (stepMs >= 10) return `${seconds}.${milliseconds.slice(0, 2)}`
  return `${seconds}.${milliseconds}`
}

/** The ticks inside `view`, at multiples of the chosen step counted from the epoch (so a step of a minute lands on :00). */
export function ticksFor(view: Span, width: number, minDistancePx = MIN_TICK_DISTANCE_PX): Tick[] {
  if (width <= 0 || spanLength(view) <= 0) return []
  const step = tickStep(spanLength(view), width, minDistancePx)
  const ticks: Tick[] = []
  for (let time = Math.ceil(view.start / step) * step; time <= view.end; time += step) {
    ticks.push({ time, label: formatTickLabel(time, step) })
  }
  return ticks
}

/** A length of time with the unit that keeps it short: `250 ms`, `3.25 s`, `42.5 s`, `4m 12s`. */
export function formatSpanLength(ms: number): string {
  if (ms < SECOND) return `${Math.round(ms)} ms`
  if (ms < 10 * SECOND) return `${(ms / SECOND).toFixed(2)} s`
  if (ms < MINUTE) return `${(ms / SECOND).toFixed(1)} s`
  return formatDuration(ms / SECOND)
}

function instantText(time: number, withDay: boolean): string {
  const iso = new Date(time).toISOString()
  return withDay ? `${iso.slice(0, 10)} ${iso.slice(11, 23)}` : iso.slice(11, 23)
}

/** `2026-10-13 15:39:50.100 - 15:40:40.317 UTC · 50.2 s`; the second day is named only when the range crosses midnight. */
export function formatVisibleRange(view: Span): string {
  if (!Number.isFinite(view.start) || !Number.isFinite(view.end)) return ''
  const crossesDays = new Date(view.start).toISOString().slice(0, 10) !== new Date(view.end).toISOString().slice(0, 10)
  return `${instantText(view.start, true)} - ${instantText(view.end, crossesDays)} UTC · ${formatSpanLength(spanLength(view))}`
}

/** `15:39:50.100 - 15:39:53.350 · 3.25 s`, what is shown on the axis while a range is being brushed. */
export function formatBrushLabel(span: Span): string {
  return `${instantText(span.start, false)} - ${instantText(span.end, false)} · ${formatSpanLength(spanLength(span))}`
}
