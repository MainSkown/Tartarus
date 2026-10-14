import { describe, expect, it } from 'vitest'
import type { Event, HistogramBucket, HistogramDetection } from '@/api'
import {
  AGGREGATION_THRESHOLD,
  AXIS_HEIGHT,
  CLUSTER_SIZE,
  DETECTION_TRACK_HEIGHT,
  GUTTER_WIDTH,
  MARK_SIZE,
  MIN_LANE_HEIGHT,
  OVERLAP_LIMIT,
  OVERLAP_OFFSET,
  bandRect,
  barsFor,
  buildScene,
  computeLayout,
  detectionMarks,
  markEvents,
  sourceFor,
  type ClusterMark,
  type EventMark,
} from '@/services/timeline-layout'
import { LANE_ORDER } from '@/services/lanes'
import type { Span } from '@/services/timeline-scale'
import { eventFixture } from './events-fixtures'

// One pixel per millisecond: the plot is 1000 px wide over a 1000 ms view.
const LAYOUT = computeLayout(GUTTER_WIDTH + 1000, 260)
const VIEW: Span = { start: 0, end: 1000 }

function eventAt(time: number, lane: string | null = 'file', id = `e${time}-${lane}`): Event {
  return eventFixture({ id, time: new Date(time).toISOString(), lane })
}

function marksOf(events: Event[], view = VIEW, layout = LAYOUT) {
  return markEvents(events, view, layout)
}

function idsOf(marks: ReturnType<typeof markEvents>): string[] {
  return marks.flatMap((mark) => (mark.kind === 'event' ? [mark.id] : mark.ids))
}

describe('the layout', () => {
  it('stacks a detection track, the six lanes in design-system order and the axis, filling the height', () => {
    expect(LAYOUT.gutter).toBe(GUTTER_WIDTH)
    expect(LAYOUT.plotWidth).toBe(1000)
    expect(LAYOUT.detectionTrack.top).toBe(0)
    expect(LAYOUT.detectionTrack.height).toBe(DETECTION_TRACK_HEIGHT)
    expect(LAYOUT.lanes.map((lane) => lane.lane)).toEqual(LANE_ORDER)
    expect(LAYOUT.lanes[0]!.top).toBe(DETECTION_TRACK_HEIGHT)
    for (let index = 1; index < LAYOUT.lanes.length; index++) {
      expect(LAYOUT.lanes[index]!.top).toBe(LAYOUT.lanes[index - 1]!.top + LAYOUT.lanes[index - 1]!.height)
    }
    const last = LAYOUT.lanes[LAYOUT.lanes.length - 1]!
    expect(LAYOUT.axis.top).toBe(last.top + last.height)
    expect(LAYOUT.axis.top + LAYOUT.axis.height).toBeLessThanOrEqual(260)
    expect(LAYOUT.axis.height).toBe(AXIS_HEIGHT)
    expect(LAYOUT.height).toBe(260)
  })

  it('centres each lane vertically in its row', () => {
    for (const lane of LAYOUT.lanes) expect(lane.centre).toBe(lane.top + lane.height / 2)
  })

  it('never makes a lane shorter than the minimum, growing the canvas instead', () => {
    const tiny = computeLayout(500, 50)
    for (const lane of tiny.lanes) expect(lane.height).toBe(MIN_LANE_HEIGHT)
    expect(tiny.height).toBe(DETECTION_TRACK_HEIGHT + 6 * MIN_LANE_HEIGHT + AXIS_HEIGHT)
  })

  it('keeps a plot of at least one pixel on a canvas narrower than the gutter', () => {
    expect(computeLayout(1, 260).plotWidth).toBe(1)
    expect(computeLayout(0, 260).plotWidth).toBe(1)
  })
})

describe('when to aggregate', () => {
  it('draws events up to 2000 and buckets above', () => {
    expect(AGGREGATION_THRESHOLD).toBe(2000)
    expect(sourceFor(0)).toBe('events')
    expect(sourceFor(2000)).toBe('events')
    expect(sourceFor(2001)).toBe('buckets')
  })
})

describe('marks', () => {
  it('puts one event at its time in the row of its lane', () => {
    const [mark] = marksOf([eventAt(100, 'registry')]) as EventMark[]
    expect(mark!.kind).toBe('event')
    expect(mark!.x).toBe(GUTTER_WIDTH + 100)
    expect(mark!.y).toBe(LAYOUT.lanes[LANE_ORDER.indexOf('registry')]!.centre)
    expect(mark!.lane).toBe('registry')
  })

  it('gives each lane its own row, in order', () => {
    const marks = marksOf(LANE_ORDER.map((lane) => eventAt(500, lane)))
    expect(marks.map((mark) => mark.y)).toEqual(LAYOUT.lanes.map((lane) => lane.centre))
  })

  it('draws an event with no lane or an unknown one in the neutral api lane', () => {
    const marks = marksOf([eventAt(100, null, 'a'), eventAt(300, 'unknown', 'b')])
    expect(marks.map((mark) => mark.lane)).toEqual(['api', 'api'])
  })

  it('leaves events at least a mark apart as separate marks', () => {
    const marks = marksOf([eventAt(100), eventAt(100 + MARK_SIZE)])
    expect(marks.map((mark) => mark.kind)).toEqual(['event', 'event'])
    expect(marks[1]!.x - marks[0]!.x).toBe(MARK_SIZE)
  })

  it('overlaps events closer than a mark, pushing each at least the offset past the one before', () => {
    const marks = marksOf([eventAt(100), eventAt(101), eventAt(102)]) as EventMark[]
    expect(marks.map((mark) => mark.kind)).toEqual(['event', 'event', 'event'])
    expect(marks.map((mark) => mark.x)).toEqual([GUTTER_WIDTH + 100, GUTTER_WIDTH + 100 + OVERLAP_OFFSET, GUTTER_WIDTH + 100 + 2 * OVERLAP_OFFSET])
  })

  it('fans out events that share a timestamp, so there are visibly several', () => {
    const marks = marksOf([eventAt(400, 'file', 'a'), eventAt(400, 'file', 'b'), eventAt(400, 'file', 'c')]) as EventMark[]
    expect(new Set(marks.map((mark) => mark.x)).size).toBe(3)
    expect(marks.map((mark) => mark.id)).toEqual(['a', 'b', 'c'])
  })

  it('collapses more than the overlap limit into one count mark in the middle of them', () => {
    const events = Array.from({ length: OVERLAP_LIMIT + 1 }, (_, index) => eventAt(100 + index, 'file', `e${index}`))
    const [mark, ...rest] = marksOf(events) as ClusterMark[]
    expect(rest).toEqual([])
    expect(mark!.kind).toBe('cluster')
    expect(mark!.count).toBe(OVERLAP_LIMIT + 1)
    expect(mark!.ids).toEqual(['e0', 'e1', 'e2', 'e3'])
    expect(mark!.x).toBe(GUTTER_WIDTH + 101.5)
    expect(mark!.start).toBe(100)
    expect(mark!.end).toBe(103)
  })

  describe('count marks that would overlap', () => {
    const run = (first: number, lane = 'api'): Event[] => Array.from({ length: 5 }, (_, index) => eventAt(first + index, lane, `${lane}-${first}-${index}`))

    it('are merged into one, so their numbers stay readable', () => {
      const [only, ...rest] = marksOf([...run(100), ...run(115)]) as ClusterMark[]
      expect(rest).toEqual([])
      expect(only!.count).toBe(10)
      expect(only!.start).toBe(100)
      expect(only!.end).toBe(119)
    })

    it('stay apart when their boxes do not touch', () => {
      const marks = marksOf([...run(100), ...run(100 + CLUSTER_SIZE.width + 20)]) as ClusterMark[]
      expect(marks.map((mark) => mark.count)).toEqual([5, 5])
    })

    it('are merged only within one box width of the first, so a long dense run becomes a row of boxes, not one huge one', () => {
      const dense = Array.from({ length: 8 }, (_, group) => run(100 + group * 12)).flat()
      const marks = marksOf(dense) as ClusterMark[]
      expect(marks.length).toBeGreaterThan(2)
      expect(marks.reduce((sum, mark) => sum + mark.count, 0)).toBe(dense.length)
      for (let index = 1; index < marks.length; index++) expect(marks[index]!.x - marks[index - 1]!.x).toBeGreaterThanOrEqual(CLUSTER_SIZE.width / 2)
    })

    it('take in the single marks their box would cover, so no mark sits half under a box', () => {
      const marks = marksOf([eventAt(95, 'api', 'before'), ...run(100), eventAt(112, 'api', 'after')]) as ClusterMark[]
      expect(marks).toHaveLength(1)
      expect(marks[0]!.ids).toContain('before')
      expect(marks[0]!.ids).toContain('after')
    })

    it('leave single marks that are clear of the box alone', () => {
      const marks = marksOf([eventAt(60, 'api', 'far'), ...run(100)])
      expect(marks.map((mark) => mark.kind)).toEqual(['event', 'cluster'])
    })

    it('never leave a mark and a count mark drawn over each other, however dense the lane', () => {
      let seed = 11
      const random = () => (seed = (seed * 48271) % 2147483647) / 2147483647
      const events = Array.from({ length: 2500 }, (_, index) => eventAt(Math.floor(random() * 1000), 'api', `r${index}`))
      const marks = marksOf(events).sort((a, b) => a.x - b.x)
      const reach = (mark: (typeof marks)[number]) => (mark.kind === 'cluster' ? CLUSTER_SIZE.width / 2 : MARK_SIZE / 2)
      for (let index = 1; index < marks.length; index++) {
        const [left, right] = [marks[index - 1]!, marks[index]!]
        if (left.kind === 'cluster' || right.kind === 'cluster') expect(right.x - reach(right)).toBeGreaterThanOrEqual(left.x + reach(left) - 0.001)
      }
      expect(idsOf(marks).sort()).toEqual(events.map((event) => event.id).sort())
    })

    it('stay in their own lane', () => {
      const marks = marksOf([...run(100, 'api'), ...run(105, 'file')]) as ClusterMark[]
      expect(marks.map((mark) => [mark.lane, mark.count])).toEqual([['file', 5], ['api', 5]])
    })
  })

  it('collapses a hundred events at one instant, which no zoom can separate', () => {
    const events = Array.from({ length: 100 }, (_, index) => eventAt(500, 'api', `e${index}`))
    const marks = marksOf(events) as ClusterMark[]
    expect(marks).toHaveLength(1)
    expect(marks[0]!.count).toBe(100)
    expect(marks[0]!.start).toBe(marks[0]!.end)
  })

  it('does not mix lanes in a cluster', () => {
    const events = [eventAt(100, 'file', 'a'), eventAt(100, 'registry', 'b'), eventAt(101, 'file', 'c')]
    expect(marksOf(events)).toHaveLength(3)
  })

  it('does not depend on the order the events come in', () => {
    const events = [eventAt(300, 'file', 'c'), eventAt(100, 'file', 'a'), eventAt(200, 'file', 'b')]
    expect(idsOf(marksOf(events))).toEqual(['a', 'b', 'c'])
  })

  it('skips events outside the view and keeps those exactly on its ends', () => {
    const events = [eventAt(-1, 'file', 'before'), eventAt(0, 'file', 'start'), eventAt(1000, 'file', 'end'), eventAt(1001, 'file', 'after')]
    expect(idsOf(marksOf(events))).toEqual(['start', 'end'])
  })

  it('is empty without events', () => {
    expect(marksOf([])).toEqual([])
  })

  it('never hides an event: every one is in exactly one mark, however dense', () => {
    let seed = 7
    const random = () => (seed = (seed * 48271) % 2147483647) / 2147483647
    const events = Array.from({ length: 3000 }, (_, index) => eventAt(Math.floor(random() * 1000), LANE_ORDER[index % 3], `r${index}`))
    const ids = idsOf(marksOf(events))
    expect(ids.sort()).toEqual(events.map((event) => event.id).sort())
  })

  it('still loses nothing on a one pixel plot', () => {
    const narrow = computeLayout(GUTTER_WIDTH + 1, 260)
    const events = Array.from({ length: 20 }, (_, index) => eventAt(index * 40, 'file', `e${index}`))
    const marks = markEvents(events, VIEW, narrow)
    expect(idsOf(marks).sort()).toEqual(events.map((event) => event.id).sort())
    for (const mark of marks) expect(Number.isFinite(mark.x)).toBe(true)
  })

  it('places events a few milliseconds apart in a view of a few milliseconds', () => {
    const view: Span = { start: 1000, end: 1010 }
    const marks = markEvents([eventAt(1002, 'file', 'a'), eventAt(1008, 'file', 'b')], view, LAYOUT)
    expect(marks[1]!.x - marks[0]!.x).toBeCloseTo(600, 6)
  })

  it('is empty for a view with no length', () => {
    expect(markEvents([eventAt(5)], { start: 5, end: 5 }, LAYOUT).length).toBeLessThanOrEqual(1)
  })
})

function bucket(time: number, byLane: Record<string, number>): HistogramBucket {
  return { time: new Date(time).toISOString(), total: Object.values(byLane).reduce((sum, count) => sum + count, 0), by_lane: byLane }
}

describe('bars', () => {
  const buckets = [bucket(0, { file: 10, api: 100 }), bucket(100, { file: 5 }), bucket(200, { api: 50, unknown: 25 })]

  it('draws one bar per lane per bucket that has events there', () => {
    const bars = barsFor(buckets, 100, VIEW, LAYOUT)
    expect(bars.map((bar) => [bar.lane, bar.start, bar.count])).toEqual([
      ['file', 0, 10],
      ['api', 0, 100],
      ['file', 100, 5],
      ['api', 200, 75],
    ])
  })

  it('counts a lane the layout does not have in the api lane', () => {
    expect(barsFor(buckets, 100, VIEW, LAYOUT).find((bar) => bar.start === 200)!.count).toBe(75)
  })

  it('spans the bucket in x, less a pixel of gap', () => {
    const [bar] = barsFor([bucket(100, { file: 1 })], 100, VIEW, LAYOUT)
    expect(bar!.x).toBe(GUTTER_WIDTH + 100)
    expect(bar!.width).toBe(99)
    expect(bar!.end).toBe(200)
  })

  it('scales the height of each lane to its own busiest bucket, so a quiet lane is still readable', () => {
    const bars = barsFor(buckets, 100, VIEW, LAYOUT)
    const file = bars.filter((bar) => bar.lane === 'file')
    const api = bars.filter((bar) => bar.lane === 'api')
    expect(file[0]!.height).toBeGreaterThan(file[1]!.height)
    expect(file[0]!.height).toBeCloseTo(api[0]!.height, 6)
    expect(file[1]!.height / file[0]!.height).toBeCloseTo(0.5, 1)
  })

  it('rises from the bottom of the lane and stays inside the row', () => {
    for (const bar of barsFor(buckets, 100, VIEW, LAYOUT)) {
      const row = LAYOUT.lanes[LANE_ORDER.indexOf(bar.lane)]!
      expect(bar.y).toBeGreaterThanOrEqual(row.top)
      expect(bar.y + bar.height).toBeLessThanOrEqual(row.top + row.height)
    }
  })

  it('gives even a count of one a visible bar', () => {
    const bars = barsFor([bucket(0, { file: 1, api: 100000 })], 100, VIEW, LAYOUT)
    expect(bars.find((bar) => bar.lane === 'file')!.height).toBeGreaterThanOrEqual(2)
  })

  it('clips a bucket that runs past the view to the plot', () => {
    const [bar] = barsFor([bucket(950, { file: 1 })], 100, VIEW, LAYOUT)
    expect(bar!.x + bar!.width).toBeLessThanOrEqual(GUTTER_WIDTH + 1000)
    const [early] = barsFor([bucket(-50, { file: 1 })], 100, VIEW, LAYOUT)
    expect(early!.x).toBeGreaterThanOrEqual(GUTTER_WIDTH)
  })

  it('leaves out buckets wholly outside the view and buckets with nothing in them', () => {
    expect(barsFor([bucket(2000, { file: 5 }), bucket(300, {})], 100, VIEW, LAYOUT)).toEqual([])
  })

  it('labels a bar with its count only when it is wide enough to hold the number', () => {
    const wide = barsFor([bucket(0, { file: 1234 })], 100, VIEW, LAYOUT)[0]!
    expect(wide.label).toBe('1,234')
    const narrow = barsFor([bucket(0, { file: 1234 })], 5, VIEW, LAYOUT)[0]!
    expect(narrow.label).toBeNull()
  })

  it('is empty without buckets', () => {
    expect(barsFor([], 100, VIEW, LAYOUT)).toEqual([])
  })
})

function detection(time: number, severity: HistogramDetection['severity'], id = `d${time}`): HistogramDetection {
  return { time: new Date(time).toISOString(), id, name: `rule ${id}`, severity, ruleset: 'cape' }
}

describe('detection marks', () => {
  it('sit on the detection track at their time', () => {
    const [mark] = detectionMarks([detection(250, 'high')], VIEW, LAYOUT)
    expect(mark!.x).toBe(GUTTER_WIDTH + 250)
    expect(mark!.y).toBe(LAYOUT.detectionTrack.centre)
    expect(mark!.severity).toBe('high')
  })

  it('are ordered so the most severe is drawn last, on top of an overlap', () => {
    const marks = detectionMarks([detection(100, 'critical', 'c'), detection(100, 'low', 'l'), detection(100, 'high', 'h')], VIEW, LAYOUT)
    expect(marks.map((mark) => mark.id)).toEqual(['l', 'h', 'c'])
  })

  it('count a detection without a severity as informational', () => {
    expect(detectionMarks([detection(100, null)], VIEW, LAYOUT)[0]!.severity).toBe('info')
  })

  it('skip those outside the view', () => {
    expect(detectionMarks([detection(-5, 'high'), detection(1005, 'high')], VIEW, LAYOUT)).toEqual([])
  })
})

describe('the time-range band', () => {
  it('is the span in canvas pixels with both handles when it is inside the view', () => {
    expect(bandRect({ start: 200, end: 600 }, VIEW, LAYOUT)).toEqual({ x0: GUTTER_WIDTH + 200, x1: GUTTER_WIDTH + 600, startVisible: true, endVisible: true })
  })

  it('is cut at the plot edge, without the handle of the end that is cut', () => {
    expect(bandRect({ start: -200, end: 600 }, VIEW, LAYOUT)).toEqual({ x0: GUTTER_WIDTH, x1: GUTTER_WIDTH + 600, startVisible: false, endVisible: true })
    expect(bandRect({ start: 200, end: 5000 }, VIEW, LAYOUT)).toEqual({ x0: GUTTER_WIDTH + 200, x1: GUTTER_WIDTH + 1000, startVisible: true, endVisible: false })
  })

  it('is nothing when the span is outside the view', () => {
    expect(bandRect({ start: 2000, end: 3000 }, VIEW, LAYOUT)).toBeNull()
  })
})

describe('the scene', () => {
  it('holds marks, ticks and detections for events', () => {
    const scene = buildScene({
      layout: LAYOUT,
      view: VIEW,
      data: { mode: 'events', events: [eventAt(100)], detections: [detection(200, 'high')] },
    })
    expect(scene.source).toBe('events')
    expect(scene.marks).toHaveLength(1)
    expect(scene.bars).toEqual([])
    expect(scene.detections).toHaveLength(1)
    expect(scene.ticks.length).toBeGreaterThan(2)
    for (const tick of scene.ticks) expect(tick.x).toBe(GUTTER_WIDTH + tick.time)
  })

  it('holds bars instead of marks for buckets', () => {
    const scene = buildScene({
      layout: LAYOUT,
      view: VIEW,
      data: { mode: 'buckets', buckets: [bucket(0, { file: 3 })], intervalMs: 100, detections: [] },
    })
    expect(scene.source).toBe('buckets')
    expect(scene.marks).toEqual([])
    expect(scene.bars).toHaveLength(1)
  })

  it('is empty without data', () => {
    const scene = buildScene({ layout: LAYOUT, view: VIEW, data: undefined })
    expect(scene.marks).toEqual([])
    expect(scene.bars).toEqual([])
    expect(scene.detections).toEqual([])
  })
})
