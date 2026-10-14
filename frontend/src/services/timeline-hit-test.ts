import type { RangeHandle } from '@/services/timeline-brush'
import { CLUSTER_SIZE, MARK_SIZE, type Band, type Bar, type ClusterMark, type DetectionMark, type EventMark, type Scene } from '@/services/timeline-layout'

export const MARK_HIT_RADIUS = MARK_SIZE / 2 + 2
export const CLUSTER_HIT_RADIUS = CLUSTER_SIZE.width / 2
export const DETECTION_HIT_RADIUS = 7
export const HANDLE_GRAB = 6
export const MIN_BAR_HIT_WIDTH = 4

export type Hit =
  | { kind: 'mark'; mark: EventMark }
  | { kind: 'cluster'; mark: ClusterMark }
  | { kind: 'bar'; bar: Bar }
  | { kind: 'detection'; detection: DetectionMark }
  | { kind: 'handle'; handle: RangeHandle }
  | { kind: 'axis' }
  | { kind: 'plot' }
  | { kind: 'gutter' }

/** The candidate nearest in x within `reach`; on a tie the later one, which is the one drawn on top. */
function nearestInX<T extends { x: number }>(candidates: T[], x: number, reach: (candidate: T) => number): T | undefined {
  let best: T | undefined
  let bestDistance = Infinity
  for (const candidate of candidates) {
    const distance = Math.abs(candidate.x - x)
    if (distance <= reach(candidate) && distance <= bestDistance) {
      best = candidate
      bestDistance = distance
    }
  }
  return best
}

function handleAt(band: Band | null, x: number): RangeHandle | undefined {
  if (band === null) return undefined
  const start = band.startVisible ? Math.abs(x - band.x0) : Infinity
  const end = band.endVisible ? Math.abs(x - band.x1) : Infinity
  if (Math.min(start, end) > HANDLE_GRAB) return undefined
  return start < end ? 'start' : 'end'
}

function barAt(bars: Bar[], x: number, lane: string): Bar | undefined {
  return bars.find((bar) => {
    const slack = Math.max(0, (MIN_BAR_HIT_WIDTH - bar.width) / 2)
    return bar.lane === lane && x >= bar.x - slack && x <= bar.x + bar.width + slack
  })
}

/** What is under a pointer at (`x`, `y`) in canvas pixels, from the drawn geometry alone; null outside the canvas. */
export function hitTest(scene: Scene, band: Band | null, x: number, y: number): Hit | null {
  const { layout } = scene
  if (x < 0 || y < 0 || x > layout.width || y > layout.height) return null
  if (x < layout.gutter) return { kind: 'gutter' }

  if (y >= layout.axis.top) {
    const handle = handleAt(band, x)
    return handle ? { kind: 'handle', handle } : { kind: 'axis' }
  }

  if (y < layout.detectionTrack.top + layout.detectionTrack.height) {
    const detection = nearestInX(scene.detections, x, () => DETECTION_HIT_RADIUS)
    return detection ? { kind: 'detection', detection } : { kind: 'plot' }
  }

  const row = layout.lanes.find((lane) => y >= lane.top && y < lane.top + lane.height)
  if (!row) return { kind: 'plot' }
  // Count marks are drawn first, so a single mark over one is what the pointer sees and is tried first.
  const inLane = scene.marks.filter((candidate) => candidate.lane === row.lane)
  const single = nearestInX(inLane.filter((candidate): candidate is EventMark => candidate.kind === 'event'), x, () => MARK_HIT_RADIUS)
  if (single) return { kind: 'mark', mark: single }
  const cluster = nearestInX(inLane.filter((candidate): candidate is ClusterMark => candidate.kind === 'cluster'), x, () => CLUSTER_HIT_RADIUS)
  if (cluster) return { kind: 'cluster', mark: cluster }
  const bar = barAt(scene.bars, x, row.lane)
  return bar ? { kind: 'bar', bar } : { kind: 'plot' }
}
