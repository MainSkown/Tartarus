import type { Event, HistogramBucket, HistogramDetection, Severity } from '@/api'
import { compareSeverity } from '@/services/analysis-status'
import { formatCount } from '@/services/format-number'
import { LANE_ORDER } from '@/services/lanes'
import { ticksFor, type Tick } from '@/services/timeline-axis'
import { isWithin, spanLength, timeToX, type Span } from '@/services/timeline-scale'

/** Above this many events in view the timeline draws the histogram's count bars instead of one mark per event (M3 decision 11). */
export const AGGREGATION_THRESHOLD = 2000

export const GUTTER_WIDTH = 104
export const DETECTION_TRACK_HEIGHT = 24
export const AXIS_HEIGHT = 26
export const MIN_LANE_HEIGHT = 24
export const MARK_SIZE = 8
/** The box a count mark is drawn in: wide enough for three digits, so it is also its hit target. */
export const CLUSTER_SIZE = { width: 22, height: 16 }
/** Events in one lane that are closer than a mark are drawn as overlapping marks up to this many, and as one count mark beyond. */
export const OVERLAP_LIMIT = 3
export const OVERLAP_OFFSET = 5
export const MARK_RING = 2
const BAR_GAP = 1
const BAR_LANE_PADDING = 4
const MIN_BAR_HEIGHT = 2
const LABEL_CHAR_WIDTH = 6
const LABEL_PADDING = 6
const NEUTRAL_LANE = 'api'

export type SceneSource = 'events' | 'buckets'

export function sourceFor(eventsInView: number): SceneSource {
  return eventsInView > AGGREGATION_THRESHOLD ? 'buckets' : 'events'
}

export interface LaneRow {
  lane: string
  top: number
  height: number
  centre: number
}

export interface Layout {
  width: number
  height: number
  /** Left edge of the plot, where the lane labels end. */
  gutter: number
  plotWidth: number
  detectionTrack: { top: number; height: number; centre: number }
  lanes: LaneRow[]
  axis: { top: number; height: number }
}

export function computeLayout(width: number, height: number): Layout {
  const laneHeight = Math.max(MIN_LANE_HEIGHT, Math.floor((height - DETECTION_TRACK_HEIGHT - AXIS_HEIGHT) / LANE_ORDER.length))
  const lanes = LANE_ORDER.map((lane, index) => {
    const top = DETECTION_TRACK_HEIGHT + index * laneHeight
    return { lane, top, height: laneHeight, centre: top + laneHeight / 2 }
  })
  const axisTop = DETECTION_TRACK_HEIGHT + LANE_ORDER.length * laneHeight
  return {
    width,
    height: axisTop + AXIS_HEIGHT,
    gutter: GUTTER_WIDTH,
    plotWidth: Math.max(1, width - GUTTER_WIDTH),
    detectionTrack: { top: 0, height: DETECTION_TRACK_HEIGHT, centre: DETECTION_TRACK_HEIGHT / 2 },
    lanes,
    axis: { top: axisTop, height: AXIS_HEIGHT },
  }
}

function laneRow(layout: Layout, lane: string | null): LaneRow {
  const known = layout.lanes.find((row) => row.lane === lane)
  return known ?? layout.lanes.find((row) => row.lane === NEUTRAL_LANE)!
}

function canvasX(time: number, view: Span, layout: Layout): number {
  return layout.gutter + timeToX(time, view, layout.plotWidth)
}

export interface EventMark {
  kind: 'event'
  id: string
  x: number
  y: number
  lane: string
  time: number
  event: Event
}

export interface ClusterMark {
  kind: 'cluster'
  x: number
  y: number
  lane: string
  count: number
  ids: string[]
  start: number
  end: number
  events: Event[]
}

export type Mark = EventMark | ClusterMark

interface Placed {
  event: Event
  time: number
  x: number
}

function byTimeThenSequence(a: Placed, b: Placed): number {
  return a.time - b.time || (a.event.sequence ?? Infinity) - (b.event.sequence ?? Infinity)
}

function overlappedMarks(group: Placed[], row: LaneRow): EventMark[] {
  let previousX = -Infinity
  return group.map(({ event, time, x }) => {
    previousX = Math.max(x, previousX + OVERLAP_OFFSET)
    return { kind: 'event', id: event.id, x: previousX, y: row.centre, lane: row.lane, time, event }
  })
}

function countMark(group: Placed[], row: LaneRow): ClusterMark {
  const first = group[0]!
  const last = group[group.length - 1]!
  return {
    kind: 'cluster',
    x: (first.x + last.x) / 2,
    y: row.centre,
    lane: row.lane,
    count: group.length,
    ids: group.map(({ event }) => event.id),
    start: first.time,
    end: last.time,
    events: group.map(({ event }) => event),
  }
}

function groupsWithinAMark(placed: Placed[]): Placed[][] {
  const groups: Placed[][] = []
  let anchorX = -Infinity
  for (const item of placed) {
    if (groups.length > 0 && item.x - anchorX < MARK_SIZE) {
      groups[groups.length - 1]!.push(item)
    } else {
      groups.push([item])
      anchorX = item.x
    }
  }
  return groups
}

const MARK_REACH = MARK_SIZE / 2 + MARK_RING

function isCountGroup(group: Placed[]): boolean {
  return group.length > OVERLAP_LIMIT
}

function leftEdge(group: Placed[]): number {
  const first = group[0]!.x
  return isCountGroup(group) ? (first + group[group.length - 1]!.x) / 2 - CLUSTER_SIZE.width / 2 : first - MARK_REACH
}

function rightEdge(group: Placed[]): number {
  const last = group[group.length - 1]!.x
  return isCountGroup(group) ? (group[0]!.x + last) / 2 + CLUSTER_SIZE.width / 2 : last + (group.length - 1) * OVERLAP_OFFSET + MARK_REACH
}

/**
 * A count mark is a box wider than the group window, so it could sit over its neighbours. Walking
 * left to right, a group the box of the one before reaches joins it, and a count group takes in the
 * groups before it that its own box reaches, so no drawn mark overlaps a count mark.
 */
function mergeOverlappingCountGroups(groups: Placed[][]): Placed[][] {
  const merged: Placed[][] = []
  for (const group of groups) {
    const previous = merged[merged.length - 1]
    if (previous && isCountGroup(previous) && leftEdge(group) < rightEdge(previous)) {
      merged[merged.length - 1] = [...previous, ...group]
      continue
    }
    let current = group
    if (isCountGroup(current)) while (merged.length > 0 && rightEdge(merged[merged.length - 1]!) > leftEdge(current)) current = [...merged.pop()!, ...current]
    merged.push(current)
  }
  return merged
}

/**
 * The marks of a view's events, lane by lane in the fixed order. Within a lane, events are grouped
 * left to right: an event joins the group while it is less than a mark width (`MARK_SIZE`) from the
 * group's first event. A group of up to `OVERLAP_LIMIT` stays as separate marks (each at least
 * `OVERLAP_OFFSET` past the one before, drawn with a ring), a bigger one collapses into one count
 * mark, and count marks whose boxes would overlap become one. Every event is in exactly one mark,
 * so nothing the data holds is ever hidden.
 */
export function markEvents(events: Event[], view: Span, layout: Layout): Mark[] {
  const byLane = new Map<string, Placed[]>()
  for (const event of events) {
    const time = Date.parse(event.time)
    if (!isWithin(view, time)) continue
    const lane = laneRow(layout, event.lane).lane
    const placed = byLane.get(lane) ?? []
    placed.push({ event, time, x: canvasX(time, view, layout) })
    byLane.set(lane, placed)
  }
  return layout.lanes.flatMap((row) => {
    const placed = (byLane.get(row.lane) ?? []).sort(byTimeThenSequence)
    return mergeOverlappingCountGroups(groupsWithinAMark(placed)).flatMap((group): Mark[] => (group.length > OVERLAP_LIMIT ? [countMark(group, row)] : overlappedMarks(group, row)))
  })
}

export interface Bar {
  lane: string
  start: number
  end: number
  count: number
  x: number
  width: number
  y: number
  height: number
  /** The count as text when the bar is wide enough to hold it. */
  label: string | null
}

function countsByLane(bucket: HistogramBucket, layout: Layout): Map<string, number> {
  const counts = new Map<string, number>()
  for (const [lane, count] of Object.entries(bucket.by_lane)) {
    const row = laneRow(layout, lane).lane
    counts.set(row, (counts.get(row) ?? 0) + count)
  }
  return counts
}

function labelFor(count: number, width: number): string | null {
  const text = formatCount(count)
  return width >= text.length * LABEL_CHAR_WIDTH + LABEL_PADDING ? text : null
}

/** Count bars, one per lane and bucket, as tall as the count is large next to the lane's busiest bucket in view. */
export function barsFor(buckets: HistogramBucket[], intervalMs: number, view: Span, layout: Layout): Bar[] {
  const plotRight = layout.gutter + layout.plotWidth
  const visible = buckets
    .map((bucket) => ({ start: Date.parse(bucket.time), counts: countsByLane(bucket, layout) }))
    .filter(({ start }) => start + intervalMs >= view.start && start <= view.end)
  const laneMax = new Map<string, number>()
  for (const { counts } of visible) for (const [lane, count] of counts) laneMax.set(lane, Math.max(laneMax.get(lane) ?? 0, count))

  return visible.flatMap(({ start, counts }) => {
    const x0 = Math.max(layout.gutter, canvasX(start, view, layout))
    const x1 = Math.min(plotRight, canvasX(start + intervalMs, view, layout))
    if (x1 <= x0) return []
    const width = Math.max(1, x1 - x0 - BAR_GAP)
    return layout.lanes.flatMap((row) => {
      const count = counts.get(row.lane) ?? 0
      if (count <= 0) return []
      const available = row.height - 2 * BAR_LANE_PADDING
      const height = Math.max(MIN_BAR_HEIGHT, (count / laneMax.get(row.lane)!) * available)
      return [{ lane: row.lane, start, end: start + intervalMs, count, x: x0, width, y: row.top + row.height - BAR_LANE_PADDING - height, height, label: labelFor(count, width) }]
    })
  })
}

export interface DetectionMark {
  id: string
  x: number
  y: number
  time: number
  name: string | null
  severity: Severity
  ruleset: string | null
}

/** Detections on the top track, the most severe last so it ends up on top where they overlap. */
export function detectionMarks(detections: HistogramDetection[], view: Span, layout: Layout): DetectionMark[] {
  return detections
    .map((detection) => ({ detection, time: Date.parse(detection.time), severity: detection.severity ?? 'info' }))
    .filter(({ time }) => isWithin(view, time))
    .sort((a, b) => compareSeverity(a.severity, b.severity) || a.time - b.time)
    .map(({ detection, time, severity }) => ({
      id: detection.id,
      x: canvasX(time, view, layout),
      y: layout.detectionTrack.centre,
      time,
      name: detection.name,
      severity,
      ruleset: detection.ruleset,
    }))
}

export interface Band {
  x0: number
  x1: number
  /** Whether the span's own start is on screen, and so has a handle to drag; a start cut off by the view has none. */
  startVisible: boolean
  endVisible: boolean
}

export function bandRect(span: Span, view: Span, layout: Layout): Band | null {
  if (span.end < view.start || span.start > view.end) return null
  return {
    x0: canvasX(Math.max(span.start, view.start), view, layout),
    x1: canvasX(Math.min(span.end, view.end), view, layout),
    startVisible: span.start >= view.start,
    endVisible: span.end <= view.end,
  }
}

export type SceneData =
  | { mode: 'events'; events: Event[]; detections: HistogramDetection[] }
  | { mode: 'buckets'; buckets: HistogramBucket[]; intervalMs: number; detections: HistogramDetection[] }

export interface PlacedTick extends Tick {
  x: number
}

/** Everything that is drawn and hit-tested, in canvas pixels. */
export interface Scene {
  layout: Layout
  view: Span
  source: SceneSource
  marks: Mark[]
  bars: Bar[]
  detections: DetectionMark[]
  ticks: PlacedTick[]
}

export function buildScene(input: { layout: Layout; view: Span; data: SceneData | undefined }): Scene {
  const { layout, view, data } = input
  const ticks = ticksFor(view, layout.plotWidth).map((tick) => ({ ...tick, x: canvasX(tick.time, view, layout) }))
  const source = data?.mode ?? 'events'
  return {
    layout,
    view,
    source,
    marks: data?.mode === 'events' ? markEvents(data.events, view, layout) : [],
    bars: data?.mode === 'buckets' && spanLength(view) > 0 ? barsFor(data.buckets, data.intervalMs, view, layout) : [],
    detections: data ? detectionMarks(data.detections, view, layout) : [],
    ticks,
  }
}
