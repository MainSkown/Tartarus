import { describe, expect, it } from 'vitest'
import type { HistogramBucket, HistogramDetection } from '@/api'
import { CLUSTER_HIT_RADIUS, DETECTION_HIT_RADIUS, HANDLE_GRAB, MARK_HIT_RADIUS, MIN_BAR_HIT_WIDTH, hitTest } from '@/services/timeline-hit-test'
import { GUTTER_WIDTH, OVERLAP_OFFSET, bandRect, buildScene, computeLayout, type ClusterMark, type SceneData } from '@/services/timeline-layout'
import { LANE_ORDER } from '@/services/lanes'
import type { Span } from '@/services/timeline-scale'
import { eventFixture } from './events-fixtures'

const LAYOUT = computeLayout(GUTTER_WIDTH + 1000, 260)
const VIEW: Span = { start: 0, end: 1000 }
const laneY = (lane: string): number => LAYOUT.lanes[LANE_ORDER.indexOf(lane)]!.centre
const px = (time: number): number => GUTTER_WIDTH + time

function event(time: number, lane: string, id: string) {
  return eventFixture({ id, time: new Date(time).toISOString(), lane })
}

function sceneOf(data: SceneData | undefined) {
  return buildScene({ layout: LAYOUT, view: VIEW, data })
}

function bucket(time: number, byLane: Record<string, number>): HistogramBucket {
  return { time: new Date(time).toISOString(), total: Object.values(byLane).reduce((a, b) => a + b, 0), by_lane: byLane }
}

function detection(time: number, severity: HistogramDetection['severity'], id: string): HistogramDetection {
  return { time: new Date(time).toISOString(), id, name: id, severity, ruleset: 'cape' }
}

describe('hitting an event mark', () => {
  const scene = sceneOf({ mode: 'events', events: [event(300, 'file', 'a'), event(600, 'network', 'b')], detections: [] })

  it('finds the mark under the pointer', () => {
    expect(hitTest(scene, null, px(300), laneY('file'))).toMatchObject({ kind: 'mark', mark: { id: 'a' } })
  })

  it('accepts a pointer a little off the mark, in x up to the hit radius', () => {
    expect(hitTest(scene, null, px(300) + MARK_HIT_RADIUS, laneY('file'))).toMatchObject({ kind: 'mark' })
    expect(hitTest(scene, null, px(300) + MARK_HIT_RADIUS + 1, laneY('file'))).toMatchObject({ kind: 'plot' })
  })

  it('accepts any height inside the lane row, so a thin row is easy to aim at', () => {
    const row = LAYOUT.lanes[LANE_ORDER.indexOf('file')]!
    expect(hitTest(scene, null, px(300), row.top + 1)).toMatchObject({ kind: 'mark' })
    expect(hitTest(scene, null, px(300), row.top + row.height - 1)).toMatchObject({ kind: 'mark' })
  })

  it('does not hit a mark from another lane', () => {
    expect(hitTest(scene, null, px(300), laneY('registry'))).toMatchObject({ kind: 'plot' })
  })

  it('picks the nearest of overlapping marks, and the one drawn last on a tie', () => {
    const overlapped = sceneOf({ mode: 'events', events: [event(300, 'file', 'a'), event(300, 'file', 'b'), event(300, 'file', 'c')], detections: [] })
    expect(hitTest(overlapped, null, px(300), laneY('file'))).toMatchObject({ mark: { id: 'a' } })
    expect(hitTest(overlapped, null, px(300) + OVERLAP_OFFSET, laneY('file'))).toMatchObject({ mark: { id: 'b' } })
    expect(hitTest(overlapped, null, px(300) + 2 * OVERLAP_OFFSET, laneY('file'))).toMatchObject({ mark: { id: 'c' } })
    expect(hitTest(overlapped, null, px(300) + OVERLAP_OFFSET / 2, laneY('file'))).toMatchObject({ mark: { id: 'b' } })
  })
})

describe('hitting a count mark', () => {
  const events = Array.from({ length: 6 }, (_, index) => event(300 + index, 'api', `e${index}`))
  const scene = sceneOf({ mode: 'events', events, detections: [] })

  it('finds the cluster with all its events', () => {
    const hit = hitTest(scene, null, px(302.5), laneY('api'))
    expect(hit).toMatchObject({ kind: 'cluster', mark: { count: 6 } })
  })

  it('lets a single mark drawn over the count mark be hit, not the count mark under it', () => {
    const mixed = sceneOf({ mode: 'events', events, detections: [] })
    const [box] = mixed.marks as ClusterMark[]
    mixed.marks.push({ kind: 'event', id: 'lone', x: box!.x + 7, y: box!.y, lane: 'api', time: 0, event: events[0]! })
    expect(hitTest(mixed, null, box!.x + 7, laneY('api'))).toMatchObject({ kind: 'mark', mark: { id: 'lone' } })
    expect(hitTest(mixed, null, box!.x + 3, laneY('api'))).toMatchObject({ kind: 'mark', mark: { id: 'lone' } })
    expect(hitTest(mixed, null, box!.x - 5, laneY('api'))).toMatchObject({ kind: 'cluster' })
  })

  it('has a wider target than a single mark', () => {
    expect(CLUSTER_HIT_RADIUS).toBeGreaterThan(MARK_HIT_RADIUS)
    expect(hitTest(scene, null, px(302.5) + CLUSTER_HIT_RADIUS, laneY('api'))).toMatchObject({ kind: 'cluster' })
  })
})

describe('hitting a count bar', () => {
  const scene = sceneOf({ mode: 'buckets', buckets: [bucket(200, { file: 10 }), bucket(300, { file: 4, api: 7 })], intervalMs: 100, detections: [] })

  it('finds the bar in its lane over the bucket', () => {
    expect(hitTest(scene, null, px(250), laneY('file'))).toMatchObject({ kind: 'bar', bar: { lane: 'file', start: 200, count: 10 } })
    expect(hitTest(scene, null, px(350), laneY('api'))).toMatchObject({ kind: 'bar', bar: { lane: 'api', start: 300, count: 7 } })
  })

  it('hits a short bar from anywhere in the lane row, not only on its fill', () => {
    const row = LAYOUT.lanes[LANE_ORDER.indexOf('file')]!
    expect(hitTest(scene, null, px(350), row.top + 1)).toMatchObject({ kind: 'bar', bar: { count: 4 } })
  })

  it('finds nothing over a bucket without events in that lane or between buckets', () => {
    expect(hitTest(scene, null, px(250), laneY('registry'))).toMatchObject({ kind: 'plot' })
    expect(hitTest(scene, null, px(800), laneY('file'))).toMatchObject({ kind: 'plot' })
  })

  it('has a minimum target width for a bar a pixel wide', () => {
    const narrow = sceneOf({ mode: 'buckets', buckets: [bucket(500, { file: 3 })], intervalMs: 1, detections: [] })
    const bar = narrow.bars[0]!
    expect(bar.width).toBeLessThan(MIN_BAR_HIT_WIDTH)
    expect(hitTest(narrow, null, bar.x + bar.width / 2 + MIN_BAR_HIT_WIDTH / 2 - 0.5, laneY('file'))).toMatchObject({ kind: 'bar' })
  })
})

describe('hitting a detection', () => {
  const scene = sceneOf({ mode: 'events', events: [], detections: [detection(400, 'low', 'l'), detection(400, 'critical', 'c'), detection(700, 'high', 'h')] })
  const trackY = LAYOUT.detectionTrack.centre

  it('finds the triangle on the top track', () => {
    expect(hitTest(scene, null, px(700), trackY)).toMatchObject({ kind: 'detection', detection: { id: 'h' } })
  })

  it('prefers the most severe where several overlap', () => {
    expect(hitTest(scene, null, px(400), trackY)).toMatchObject({ detection: { id: 'c' } })
  })

  it('has a reach of its radius in x and the whole track in y', () => {
    expect(hitTest(scene, null, px(700) + DETECTION_HIT_RADIUS, 1)).toMatchObject({ kind: 'detection' })
    expect(hitTest(scene, null, px(700) + DETECTION_HIT_RADIUS + 1, trackY)).toMatchObject({ kind: 'plot' })
  })
})

describe('the time-range handles', () => {
  const band = bandRect({ start: 200, end: 600 }, VIEW, LAYOUT)
  const scene = sceneOf(undefined)
  const axisY = LAYOUT.axis.top + LAYOUT.axis.height / 2

  it('are grabbed on the axis row near each end', () => {
    expect(hitTest(scene, band, px(200) + HANDLE_GRAB - 1, axisY)).toEqual({ kind: 'handle', handle: 'start' })
    expect(hitTest(scene, band, px(600) - HANDLE_GRAB + 1, axisY)).toEqual({ kind: 'handle', handle: 'end' })
  })

  it('are not grabbed away from the axis row', () => {
    expect(hitTest(scene, band, px(200), laneY('file'))).toMatchObject({ kind: 'plot' })
  })

  it('go to the nearer end when the band is narrower than two grabs', () => {
    const narrow = bandRect({ start: 500, end: 508 }, VIEW, LAYOUT)
    expect(hitTest(scene, narrow, px(501), axisY)).toEqual({ kind: 'handle', handle: 'start' })
    expect(hitTest(scene, narrow, px(507), axisY)).toEqual({ kind: 'handle', handle: 'end' })
  })

  it('are not there when the end is cut off by the view', () => {
    const cut = bandRect({ start: -100, end: 600 }, VIEW, LAYOUT)
    expect(hitTest(scene, cut, px(0), axisY)).toEqual({ kind: 'axis' })
  })
})

describe('everything else', () => {
  const scene = sceneOf(undefined)

  it('is the axis on the axis row, for a brush to start', () => {
    expect(hitTest(scene, null, px(500), LAYOUT.axis.top + 5)).toEqual({ kind: 'axis' })
  })

  it('is the gutter left of the plot', () => {
    expect(hitTest(scene, null, 10, laneY('file'))).toEqual({ kind: 'gutter' })
  })

  it('is the plot on an empty spot of a lane or the detection track, for a pan to start', () => {
    expect(hitTest(scene, null, px(500), laneY('file'))).toEqual({ kind: 'plot' })
    expect(hitTest(scene, null, px(500), 5)).toEqual({ kind: 'plot' })
  })

  it('is nothing outside the canvas', () => {
    expect(hitTest(scene, null, -1, 10)).toBeNull()
    expect(hitTest(scene, null, 10, -1)).toBeNull()
    expect(hitTest(scene, null, LAYOUT.width + 1, 10)).toBeNull()
    expect(hitTest(scene, null, 500, LAYOUT.height + 1)).toBeNull()
  })

  it('works on a canvas one pixel wide', () => {
    const narrow = computeLayout(1, 260)
    const tiny = buildScene({ layout: narrow, view: VIEW, data: { mode: 'events', events: [event(500, 'file', 'a')], detections: [] } })
    expect(hitTest(tiny, null, 0, 100)).toEqual({ kind: 'gutter' })
  })
})
