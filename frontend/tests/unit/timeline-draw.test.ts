import { describe, expect, it } from 'vitest'
import type { HistogramBucket, HistogramDetection } from '@/api'
import { drawTimeline, type DrawState } from '@/services/timeline-draw'
import { GUTTER_WIDTH, MARK_SIZE, bandRect, buildScene, computeLayout, type SceneData } from '@/services/timeline-layout'
import type { TimelinePalette } from '@/services/timeline-palette'
import type { Span } from '@/services/timeline-scale'
import { eventFixture } from './events-fixtures'
import { RecordingContext, type Op } from './recording-context'

const PALETTE: TimelinePalette = {
  background: 'bg',
  grid: 'grid',
  axisText: 'axis-text',
  labelText: 'label-text',
  text: 'text',
  onAccent: 'on-accent',
  accent: 'accent',
  accentLight: 'accent-light',
  fontMono: 'mono',
  lane: { process: 'c-process', file: 'c-file', registry: 'c-registry', network: 'c-network', memory: 'c-memory', api: 'c-api' },
  severity: { info: 's-info', low: 's-low', medium: 's-medium', high: 's-high', critical: 's-critical' },
}

const LAYOUT = computeLayout(GUTTER_WIDTH + 1000, 260)
const VIEW: Span = { start: 0, end: 1000 }
const NO_STATE: DrawState = { band: null, brushLabel: null, hover: null, selectedId: null, selectedX: null, stale: false }

function paint(data: SceneData | undefined, state: Partial<DrawState> = {}) {
  const ctx = new RecordingContext()
  const scene = buildScene({ layout: LAYOUT, view: VIEW, data })
  drawTimeline(ctx as unknown as CanvasRenderingContext2D, scene, { ...NO_STATE, ...state }, PALETTE)
  return ctx.ops
}

const event = (time: number, lane: string, id: string) => eventFixture({ id, time: new Date(time).toISOString(), lane })
const bucket = (time: number, byLane: Record<string, number>): HistogramBucket => ({ time: new Date(time).toISOString(), total: 1, by_lane: byLane })
const alert = (time: number, severity: HistogramDetection['severity']): HistogramDetection => ({ time: new Date(time).toISOString(), id: 'd', name: 'rule', severity, ruleset: 'cape' })
const fillRects = (ops: Op[], color: string) => ops.filter((op) => op.name === 'fillRect' && op.fillStyle === color)

describe('painting the timeline', () => {
  it('starts by filling the whole canvas with the surface colour', () => {
    const [first] = paint(undefined)
    expect(first).toMatchObject({ name: 'fillRect', fillStyle: 'bg', args: [0, 0, LAYOUT.width, LAYOUT.height] })
  })

  it('uses only colours of the palette, never one of its own', () => {
    const data: SceneData = {
      mode: 'events',
      events: [event(100, 'file', 'a'), ...Array.from({ length: 6 }, (_, index) => event(500 + index, 'api', `c${index}`))],
      detections: [alert(300, 'high')],
    }
    const bars: SceneData = { mode: 'buckets', buckets: [bucket(100, { file: 5 })], intervalMs: 100, detections: [] }
    const known = new Set([...Object.values(PALETTE).filter((value) => typeof value === 'string'), ...Object.values(PALETTE.lane), ...Object.values(PALETTE.severity)])
    for (const scene of [data, bars]) {
      const ops = paint(scene, { band: bandRect({ start: 100, end: 500 }, VIEW, LAYOUT), selectedId: 'a', selectedX: GUTTER_WIDTH + 100, hover: { kind: 'plot' }, brushLabel: 'x' })
      for (const op of ops) {
        if (op.fillStyle) expect(known, `fillStyle ${op.fillStyle}`).toContain(op.fillStyle)
        if (op.strokeStyle) expect(known, `strokeStyle ${op.strokeStyle}`).toContain(op.strokeStyle)
      }
    }
  })
})

describe('marks', () => {
  const data: SceneData = { mode: 'events', events: [event(300, 'file', 'a')], detections: [] }

  it('are squares of the mark size in the lane colour', () => {
    const squares = fillRects(paint(data), 'c-file')
    expect(squares).toHaveLength(1)
    expect(squares[0]!.args.slice(2)).toEqual([MARK_SIZE, MARK_SIZE])
  })

  it('have a ring of the surface colour two pixels wide, drawn before the mark', () => {
    const ops = paint(data)
    const markIndex = ops.findIndex((op) => op.name === 'fillRect' && op.fillStyle === 'c-file')
    const ring = ops.slice(0, markIndex).filter((op) => op.name === 'fillRect' && op.fillStyle === 'bg').at(-1)!
    expect(ring.args.slice(2)).toEqual([MARK_SIZE + 4, MARK_SIZE + 4])
  })

  it('are clipped to the plot so they never run over the gutter', () => {
    const marks = fillRects(paint(data), 'c-file')
    expect(marks.every((op) => op.inClip)).toBe(true)
  })

  it('draw count marks under single marks, so every single mark stays visible', () => {
    const events = Array.from({ length: 5 }, (_, index) => event(500 + index, 'api', `c${index}`))
    const scene = buildScene({ layout: LAYOUT, view: VIEW, data: { mode: 'events', events, detections: [] } })
    const [box] = scene.marks
    scene.marks.unshift({ kind: 'event', id: 'lone', x: box!.x + 6, y: box!.y, lane: 'api', time: 0, event: events[0]! })
    const ctx = new RecordingContext()
    drawTimeline(ctx as unknown as CanvasRenderingContext2D, scene, NO_STATE, PALETTE)
    const frame = ctx.ops.findIndex((op) => op.name === 'strokeRect' && op.strokeStyle === 'c-api')
    const single = ctx.ops.findIndex((op) => op.name === 'fillRect' && op.fillStyle === 'c-api' && op.args[2] === MARK_SIZE)
    expect(frame).toBeGreaterThan(-1)
    expect(single).toBeGreaterThan(frame)
  })

  it('draw a count mark as a dark box framed in the lane colour, so marks over it keep their own look', () => {
    const events = Array.from({ length: 5 }, (_, index) => event(500 + index, 'api', `c${index}`))
    const ops = paint({ mode: 'events', events, detections: [] })
    const frames = ops.filter((op) => op.name === 'strokeRect' && op.strokeStyle === 'c-api')
    expect(frames).toHaveLength(1)
    expect(fillRects(ops, 'c-api')).toHaveLength(0)
  })

  it('show the number of events of a count mark in the text colour', () => {
    const events = Array.from({ length: 5 }, (_, index) => event(500 + index, 'api', `c${index}`))
    const texts = paint({ mode: 'events', events, detections: [] }).filter((op) => op.name === 'fillText' && op.fillStyle === 'text')
    expect(texts.map((op) => op.args[0])).toEqual(['5'])
  })

  it('shorten a count above 999 so it fits the box', () => {
    const events = Array.from({ length: 1500 }, (_, index) => event(500, 'api', `c${index}`))
    const texts = paint({ mode: 'events', events, detections: [] }).filter((op) => op.name === 'fillText' && op.fillStyle === 'text')
    expect(texts.map((op) => op.args[0])).toEqual(['1.5k'])
  })
})

describe('bars', () => {
  const data: SceneData = { mode: 'buckets', buckets: [bucket(100, { file: 1500 }), bucket(300, { file: 3 })], intervalMs: 100, detections: [] }

  it('are filled in the lane colour', () => {
    expect(fillRects(paint(data), 'c-file')).toHaveLength(2)
  })

  it('carry the count inside the bar in the on-accent colour when the bar is tall enough', () => {
    const texts = paint(data).filter((op) => op.name === 'fillText' && op.fillStyle === 'on-accent')
    expect(texts.map((op) => op.args[0])).toEqual(['1,500'])
  })

  it('carry the count above a bar too short to hold it, in a colour that shows on the lane background', () => {
    const texts = paint(data).filter((op) => op.name === 'fillText' && op.fillStyle === 'label-text')
    expect(texts.map((op) => op.args[0])).toEqual(['3'])
  })
})

describe('detections', () => {
  it('are triangles in the severity colour with a surface-coloured ring under them', () => {
    const ops = paint({ mode: 'events', events: [], detections: [alert(300, 'critical')] })
    const filled = ops.findIndex((op) => op.name === 'fill' && op.fillStyle === 's-critical')
    const ring = ops.findIndex((op) => op.name === 'fill' && op.fillStyle === 'bg')
    expect(filled).toBeGreaterThan(-1)
    expect(ring).toBeGreaterThan(-1)
    expect(ring).toBeLessThan(filled)
  })
})

describe('the axis', () => {
  const ops = paint(undefined)
  const scene = buildScene({ layout: LAYOUT, view: VIEW, data: undefined })

  const labelsDrawn = (drawn: Op[]) => drawn.filter((op) => op.name === 'fillText' && op.fillStyle === 'axis-text').map((op) => op.args[0])

  it('labels the ticks in the axis text colour', () => {
    expect(labelsDrawn(ops).length).toBeGreaterThan(2)
    for (const label of labelsDrawn(ops)) expect(scene.ticks.map((tick) => tick.label)).toContain(label)
  })

  it('leaves out the label of a tick too near an edge for it to fit, so none is cut off, and keeps the tick mark', () => {
    const labels = labelsDrawn(ops)
    expect(labels).toEqual(scene.ticks.slice(1, -1).map((tick) => tick.label))
    const marks = ops.filter((op) => op.name === 'stroke' && op.strokeStyle === 'axis-text')
    expect(marks).toHaveLength(scene.ticks.length)
  })

  it('leaves out the labels the brush label covers', () => {
    const band = bandRect({ start: 200, end: 700 }, VIEW, LAYOUT)
    const covered = paint(undefined, { band, brushLabel: 'x'.repeat(40) })
    expect(labelsDrawn(covered).length).toBeLessThan(labelsDrawn(ops).length)
  })

  it('draws grid lines in the grid colour', () => {
    expect(ops.filter((op) => op.name === 'stroke' && op.strokeStyle === 'grid').length).toBeGreaterThan(0)
  })
})

describe('the time-range band', () => {
  const band = bandRect({ start: 200, end: 600 }, VIEW, LAYOUT)

  it('is drawn over the marks, so they and their rings are tinted alike', () => {
    const data: SceneData = { mode: 'events', events: [event(300, 'file', 'a')], detections: [] }
    const ops = paint(data, { band })
    const tint = ops.findIndex((op) => op.name === 'fillRect' && op.fillStyle === 'accent' && op.alpha < 1)
    const mark = ops.findIndex((op) => op.name === 'fillRect' && op.fillStyle === 'c-file')
    expect(tint).toBeGreaterThan(mark)
  })

  it('is a translucent fill in the accent colour', () => {
    const fills = paint(undefined, { band }).filter((op) => op.name === 'fillRect' && op.fillStyle === 'accent' && op.alpha < 1)
    expect(fills.length).toBeGreaterThan(0)
    expect(fills[0]!.args[0]).toBe(band!.x0)
    expect(fills[0]!.args[2]).toBe(band!.x1 - band!.x0)
  })

  it('has a handle at each end that is on screen', () => {
    const handles = paint(undefined, { band }).filter((op) => op.name === 'fillRect' && op.fillStyle === 'accent' && op.alpha === 1)
    expect(handles.length).toBeGreaterThanOrEqual(2)
    const cut = bandRect({ start: -100, end: 600 }, VIEW, LAYOUT)
    const cutHandles = paint(undefined, { band: cut }).filter((op) => op.name === 'fillRect' && op.fillStyle === 'accent' && op.alpha === 1)
    expect(cutHandles.length).toBeLessThan(handles.length)
  })

  it('names the brushed range on the axis', () => {
    const texts = paint(undefined, { band, brushLabel: '15:39:50.100 - 15:39:51.000 · 900 ms' }).filter((op) => op.name === 'fillText' && op.args[0] === '15:39:50.100 - 15:39:51.000 · 900 ms')
    expect(texts).toHaveLength(1)
  })
})

describe('selection and hover', () => {
  const data: SceneData = { mode: 'events', events: [event(300, 'file', 'a'), event(600, 'file', 'b')], detections: [] }

  it('rings the selected mark in the accent-light colour and marks its time with a line', () => {
    const ops = paint(data, { selectedId: 'a', selectedX: GUTTER_WIDTH + 300 })
    expect(ops.filter((op) => op.name === 'strokeRect' && op.strokeStyle === 'accent-light')).toHaveLength(1)
    expect(ops.some((op) => op.name === 'stroke' && op.strokeStyle === 'accent-light')).toBe(true)
  })

  it('rings only the selected mark', () => {
    expect(paint(data, { selectedId: 'zzz', selectedX: null }).filter((op) => op.name === 'strokeRect' && op.strokeStyle === 'accent-light')).toHaveLength(0)
  })

  it('outlines the hovered mark in the text colour', () => {
    const scene = buildScene({ layout: LAYOUT, view: VIEW, data })
    const mark = scene.marks[0]!
    const ctx = new RecordingContext()
    drawTimeline(ctx as unknown as CanvasRenderingContext2D, scene, { ...NO_STATE, hover: mark.kind === 'event' ? { kind: 'mark', mark } : null }, PALETTE)
    expect(ctx.ops.filter((op) => op.name === 'strokeRect' && op.strokeStyle === 'text')).toHaveLength(1)
  })
})

describe('while loading', () => {
  it('draws the data dimmed', () => {
    const data: SceneData = { mode: 'events', events: [event(300, 'file', 'a')], detections: [] }
    const mark = fillRects(paint(data, { stale: true }), 'c-file')[0]!
    expect(mark.alpha).toBeLessThan(1)
  })
})
