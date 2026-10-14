import { describe, expect, it } from 'vitest'
import { DRAG_THRESHOLD_PX, createGesture, type GestureContext } from '@/services/timeline-gesture'
import type { Hit } from '@/services/timeline-hit-test'

const GUTTER = 104
const FULL = { start: 0, end: 100_000 }
const base: GestureContext = { view: { start: 10_000, end: 20_000 }, full: FULL, plotWidth: 1000, gutter: GUTTER, chip: null }
const at = (plotX: number): number => GUTTER + plotX

function gesture(context: Partial<GestureContext> = {}) {
  return createGesture(() => ({ ...base, ...context }))
}

const PLOT: Hit = { kind: 'plot' }
const AXIS: Hit = { kind: 'axis' }

describe('a press on the plot', () => {
  it('released where it started is a click on what was under it', () => {
    const g = gesture()
    const mark: Hit = { kind: 'detection', detection: { id: 'd', x: 0, y: 0, time: 0, name: null, severity: 'high', ruleset: null } }
    g.down(mark, at(100), 50)
    expect(g.mode).toBe('press')
    expect(g.up(at(100))).toEqual({ type: 'click', hit: mark })
    expect(g.mode).toBe('idle')
  })

  it('is still a click after a movement smaller than the drag threshold', () => {
    const g = gesture()
    g.down(PLOT, at(100), 50)
    expect(g.move(at(100) + DRAG_THRESHOLD_PX - 1, 52)).toBeUndefined()
    expect(g.up(at(100) + DRAG_THRESHOLD_PX - 1)).toEqual({ type: 'click', hit: PLOT })
  })

  it('turns into a pan once the pointer moves the threshold, counting from where it was pressed', () => {
    const g = gesture()
    g.down(PLOT, at(100), 50)
    expect(g.move(at(100) + DRAG_THRESHOLD_PX, 50)).toEqual({ type: 'pan', dx: DRAG_THRESHOLD_PX })
    expect(g.mode).toBe('pan')
  })

  it('then pans by the movement since the last move', () => {
    const g = gesture()
    g.down(PLOT, at(100), 50)
    g.move(at(110), 50)
    expect(g.move(at(125), 50)).toEqual({ type: 'pan', dx: 15 })
    expect(g.move(at(120), 50)).toEqual({ type: 'pan', dx: -5 })
  })

  it('is not a click when released after a pan, even on a mark', () => {
    const g = gesture()
    g.down({ kind: 'bar', bar: { lane: 'file', start: 0, end: 1, count: 1, x: 0, width: 1, y: 0, height: 1, label: null } }, at(100), 50)
    g.move(at(140), 50)
    expect(g.up(at(140))).toBeUndefined()
    expect(g.mode).toBe('idle')
  })

  it('also pans when the drag goes vertical, by the horizontal part only', () => {
    const g = gesture()
    g.down(PLOT, at(100), 50)
    expect(g.move(at(100), 80)).toEqual({ type: 'pan', dx: 0 })
  })
})

describe('a press on the axis', () => {
  it('brushes: each move previews the time between the press and the pointer', () => {
    const g = gesture()
    g.down(AXIS, at(100), 250)
    expect(g.mode).toBe('brush')
    expect(g.move(at(300), 250)).toEqual({ type: 'brush', span: { start: 11_000, end: 13_000 } })
    expect(g.move(at(50), 250)).toEqual({ type: 'brush', span: { start: 10_500, end: 11_000 } })
  })

  it('ends with the brushed span', () => {
    const g = gesture()
    g.down(AXIS, at(100), 250)
    g.move(at(300), 250)
    expect(g.up(at(300))).toEqual({ type: 'brush-end', span: { start: 11_000, end: 13_000 } })
    expect(g.mode).toBe('idle')
  })

  it('previews nothing while the drag is under the minimum, and ends with nothing: a click on the axis', () => {
    const g = gesture()
    g.down(AXIS, at(100), 250)
    expect(g.move(at(101), 250)).toEqual({ type: 'brush', span: null })
    expect(g.up(at(101))).toEqual({ type: 'brush-end', span: null })
  })

  it('stops at the visible range when the pointer leaves the plot', () => {
    const g = gesture()
    g.down(AXIS, at(500), 250)
    expect(g.move(at(5000), 250)).toEqual({ type: 'brush', span: { start: 15_000, end: 20_000 } })
    expect(g.move(10, 250)).toEqual({ type: 'brush', span: { start: 10_000, end: 15_000 } })
  })
})

describe('a press on a handle of the time-range chip', () => {
  const chip = { start: 12_000, end: 16_000 }

  it('moves that end: each move previews the changed range', () => {
    const g = gesture({ chip })
    g.down({ kind: 'handle', handle: 'start' }, at(200), 250)
    expect(g.mode).toBe('handle')
    expect(g.move(at(150), 250)).toEqual({ type: 'handle', handle: 'start', span: { start: 11_500, end: 16_000 } })
  })

  it('ends with the final range', () => {
    const g = gesture({ chip })
    g.down({ kind: 'handle', handle: 'end' }, at(600), 250)
    g.move(at(800), 250)
    expect(g.up(at(800))).toEqual({ type: 'handle-end', handle: 'end', span: { start: 12_000, end: 18_000 } })
  })

  it('changes nothing when pressed and released in place', () => {
    const g = gesture({ chip })
    g.down({ kind: 'handle', handle: 'end' }, at(600), 250)
    expect(g.up(at(600))).toBeUndefined()
  })

  it('does nothing without a chip to move', () => {
    const g = gesture({ chip: null })
    g.down({ kind: 'handle', handle: 'end' }, at(600), 250)
    expect(g.mode).toBe('idle')
  })
})

describe('what starts nothing', () => {
  it('is a press on the gutter or outside the canvas', () => {
    const g = gesture()
    g.down({ kind: 'gutter' }, 10, 50)
    expect(g.mode).toBe('idle')
    g.down(null, -5, 50)
    expect(g.mode).toBe('idle')
    expect(g.move(30, 50)).toBeUndefined()
    expect(g.up(30)).toBeUndefined()
  })

  it('is a move or a release with nothing pressed', () => {
    const g = gesture()
    expect(g.move(at(10), 10)).toBeUndefined()
    expect(g.up(at(10))).toBeUndefined()
  })
})

describe('cancelling', () => {
  it('ends a brush in progress and ignores the rest of the drag', () => {
    const g = gesture()
    g.down(AXIS, at(100), 250)
    g.move(at(300), 250)
    expect(g.cancel()).toEqual({ type: 'cancel' })
    expect(g.move(at(400), 250)).toBeUndefined()
    expect(g.up(at(400))).toBeUndefined()
  })

  it('ends a pan or a handle drag', () => {
    const g = gesture({ chip: { start: 12_000, end: 16_000 } })
    g.down(PLOT, at(100), 50)
    g.move(at(200), 50)
    expect(g.cancel()).toEqual({ type: 'cancel' })
    g.down({ kind: 'handle', handle: 'start' }, at(200), 250)
    g.move(at(100), 250)
    expect(g.cancel()).toEqual({ type: 'cancel' })
  })

  it('has nothing to cancel when idle, or when only pressed', () => {
    const g = gesture()
    expect(g.cancel()).toBeUndefined()
    g.down(PLOT, at(100), 50)
    expect(g.cancel()).toBeUndefined()
    expect(g.up(at(100))).toBeUndefined()
  })
})
