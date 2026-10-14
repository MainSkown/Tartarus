import { describe, expect, it } from 'vitest'
import {
  MIN_SPAN_MS,
  activePreset,
  applyPreset,
  centreOn,
  clampView,
  intersect,
  isWithin,
  jumpTo,
  paddedFullSpan,
  panByFraction,
  panByPixels,
  spanLength,
  timeToX,
  wheelZoomFactor,
  xToTime,
  zoomAround,
  type Span,
} from '@/services/timeline-scale'

const FULL: Span = { start: 1_000_000, end: 1_100_000 }
const WIDTH = 1000

describe('time and x', () => {
  const view: Span = { start: 1000, end: 2000 }

  it.each([
    [1000, 0],
    [1500, 500],
    [2000, 1000],
    [500, -500],
    [2500, 1500],
  ])('puts time %d at x %d on a 1000 px canvas over one second', (time, x) => {
    expect(timeToX(time, view, 1000)).toBe(x)
  })

  it('is undone by xToTime', () => {
    for (const x of [0, 1, 333, 1000]) expect(timeToX(xToTime(x, view, 1000), view, 1000)).toBeCloseTo(x, 9)
  })

  it('maps a one pixel wide canvas without dividing by zero', () => {
    expect(timeToX(1500, view, 1)).toBe(0.5)
    expect(xToTime(1, view, 1)).toBe(2000)
  })

  it('maps nothing on a zero wide canvas or a zero long view', () => {
    expect(xToTime(10, view, 0)).toBe(1000)
    expect(timeToX(5, { start: 5, end: 5 }, 100)).toBe(0)
  })
})

describe('padding the full range', () => {
  it('adds one percent each side', () => {
    expect(paddedFullSpan(0, 100_000)).toEqual({ start: -1000, end: 101_000 })
  })

  it('gives a single instant a one second span centred on it', () => {
    expect(paddedFullSpan(5000, 5000)).toEqual({ start: 4500, end: 5500 })
  })

  it('widens a very short range to at least one second', () => {
    const span = paddedFullSpan(10_000, 10_100)
    expect(spanLength(span)).toBe(1000)
    expect(span.start).toBe(9550)
  })
})

describe('clamping a view into the full range', () => {
  it.each<[string, Span, Span]>([
    ['leaves a view inside alone', { start: 1_010_000, end: 1_020_000 }, { start: 1_010_000, end: 1_020_000 }],
    ['shifts a view that starts before', { start: 990_000, end: 1_000_000 + 10_000 }, { start: 1_000_000, end: 1_020_000 }],
    ['shifts a view that ends after', { start: 1_090_000, end: 1_110_000 }, { start: 1_080_000, end: 1_100_000 }],
    ['caps a view longer than the full range', { start: 0, end: 5_000_000 }, FULL],
    ['widens a view shorter than the minimum', { start: 1_050_000, end: 1_050_001 }, { start: 1_050_000, end: 1_050_000 + MIN_SPAN_MS }],
  ])('%s', (_name, view, expected) => {
    expect(clampView(view, FULL)).toEqual(expected)
  })

  it('keeps the minimum at the very end of the range', () => {
    expect(clampView({ start: FULL.end, end: FULL.end }, FULL)).toEqual({ start: FULL.end - MIN_SPAN_MS, end: FULL.end })
  })

  it('has a minimum of 10 ms', () => {
    expect(MIN_SPAN_MS).toBe(10)
  })
})

describe('zooming around the cursor', () => {
  const view: Span = { start: 1_000_000, end: 1_040_000 }

  it('keeps the time under the cursor where it was', () => {
    const cursor = 1_010_000
    const zoomed = zoomAround(view, FULL, cursor, 0.5)
    expect(spanLength(zoomed)).toBe(20_000)
    expect(timeToX(cursor, zoomed, WIDTH)).toBeCloseTo(timeToX(cursor, view, WIDTH), 6)
  })

  it('zooms out by a factor above one, up to the full range', () => {
    expect(spanLength(zoomAround(view, FULL, 1_020_000, 2))).toBe(80_000)
    expect(zoomAround(view, FULL, 1_020_000, 100)).toEqual(FULL)
  })

  it('stops at the minimum span', () => {
    const tiny = zoomAround({ start: 1_000_000, end: 1_000_100 }, FULL, 1_000_050, 0.0001)
    expect(spanLength(tiny)).toBe(MIN_SPAN_MS)
  })

  it('stays inside the full range when the cursor is at an edge', () => {
    const zoomed = zoomAround({ start: FULL.start, end: FULL.start + 40_000 }, FULL, FULL.start, 0.25)
    expect(zoomed.start).toBe(FULL.start)
    expect(spanLength(zoomed)).toBe(10_000)
  })

  it('turns wheel travel into a factor: down zooms out, up zooms in, symmetric', () => {
    expect(wheelZoomFactor(100)).toBeGreaterThan(1)
    expect(wheelZoomFactor(-100)).toBeLessThan(1)
    expect(wheelZoomFactor(100) * wheelZoomFactor(-100)).toBeCloseTo(1, 9)
    expect(wheelZoomFactor(0)).toBe(1)
  })

  it('limits one wheel notch so a huge delta does not jump to the extremes', () => {
    expect(wheelZoomFactor(100_000)).toBeLessThanOrEqual(2)
    expect(wheelZoomFactor(-100_000)).toBeGreaterThanOrEqual(0.5)
  })
})

describe('panning', () => {
  const view: Span = { start: 1_040_000, end: 1_060_000 }

  it('moves the view earlier when the content is dragged right', () => {
    expect(panByPixels(view, FULL, 100, WIDTH)).toEqual({ start: 1_038_000, end: 1_058_000 })
  })

  it('moves the view later when the content is dragged left', () => {
    expect(panByPixels(view, FULL, -100, WIDTH)).toEqual({ start: 1_042_000, end: 1_062_000 })
  })

  it('stops at both ends of the full range without changing the length', () => {
    expect(panByPixels(view, FULL, 100_000, WIDTH)).toEqual({ start: FULL.start, end: FULL.start + 20_000 })
    expect(panByPixels(view, FULL, -100_000, WIDTH)).toEqual({ start: FULL.end - 20_000, end: FULL.end })
  })

  it('does nothing on a zero wide canvas', () => {
    expect(panByPixels(view, FULL, 50, 0)).toEqual(view)
  })

  it('pans by a fraction of the view for the arrow keys', () => {
    expect(panByFraction(view, FULL, 0.25)).toEqual({ start: 1_045_000, end: 1_065_000 })
    expect(panByFraction(view, FULL, -0.25)).toEqual({ start: 1_035_000, end: 1_055_000 })
  })

  it('jumps to the start or the end keeping the length', () => {
    expect(jumpTo(view, FULL, 'start')).toEqual({ start: FULL.start, end: FULL.start + 20_000 })
    expect(jumpTo(view, FULL, 'end')).toEqual({ start: FULL.end - 20_000, end: FULL.end })
  })

  it('centres a time without changing the length', () => {
    expect(centreOn(view, FULL, 1_010_000)).toEqual({ start: 1_000_000, end: 1_020_000 })
    expect(centreOn(view, FULL, 1_000_000)).toEqual({ start: FULL.start, end: FULL.start + 20_000 })
  })
})

describe('zoom presets', () => {
  const view: Span = { start: 1_040_000, end: 1_080_000 }

  it('fit is the full range', () => {
    expect(applyPreset('fit', view, FULL)).toEqual(FULL)
  })

  it.each([
    ['1m', 60_000],
    ['10s', 10_000],
    ['1s', 1000],
  ] as const)('%s is that long and centred on the current view centre', (preset, length) => {
    const zoomed = applyPreset(preset, view, FULL)
    expect(spanLength(zoomed)).toBe(length)
    expect((zoomed.start + zoomed.end) / 2).toBe(1_060_000)
  })

  it('centres on a focus time when one is given', () => {
    const zoomed = applyPreset('10s', view, FULL, 1_020_000)
    expect(zoomed).toEqual({ start: 1_015_000, end: 1_025_000 })
  })

  it('stays inside the range when the focus is near an edge', () => {
    expect(applyPreset('10s', view, FULL, FULL.start)).toEqual({ start: FULL.start, end: FULL.start + 10_000 })
  })

  it('is the full range when the analysis is shorter than the preset', () => {
    const short: Span = { start: 0, end: 5000 }
    expect(applyPreset('1m', { start: 0, end: 1000 }, short)).toEqual(short)
  })

  it('tells which preset a view is', () => {
    expect(activePreset(FULL, FULL)).toBe('fit')
    expect(activePreset({ start: 1_000_000, end: 1_010_000 }, FULL)).toBe('10s')
    expect(activePreset({ start: 1_000_000, end: 1_060_000 }, FULL)).toBe('1m')
    expect(activePreset({ start: 1_000_000, end: 1_001_000 }, FULL)).toBe('1s')
    expect(activePreset({ start: 1_000_000, end: 1_007_000 }, FULL)).toBeNull()
  })

  it('calls a short analysis fit before any other preset', () => {
    const short: Span = { start: 0, end: 5000 }
    expect(activePreset(short, short)).toBe('fit')
  })
})

describe('ranges', () => {
  it('intersects overlapping spans', () => {
    expect(intersect({ start: 0, end: 10 }, { start: 5, end: 20 })).toEqual({ start: 5, end: 10 })
    expect(intersect({ start: 0, end: 10 }, { start: 2, end: 3 })).toEqual({ start: 2, end: 3 })
  })

  it('treats spans that only touch as one instant, both ends being inclusive', () => {
    expect(intersect({ start: 0, end: 10 }, { start: 10, end: 20 })).toEqual({ start: 10, end: 10 })
  })

  it('has no intersection for disjoint spans', () => {
    expect(intersect({ start: 0, end: 10 }, { start: 11, end: 20 })).toBeNull()
  })

  it('says whether a time is inside a span, with an optional margin', () => {
    const span: Span = { start: 100, end: 200 }
    expect(isWithin(span, 100)).toBe(true)
    expect(isWithin(span, 200)).toBe(true)
    expect(isWithin(span, 99)).toBe(false)
    expect(isWithin(span, 95, 10)).toBe(true)
    expect(isWithin(span, 211, 10)).toBe(false)
  })
})

describe('widths of one pixel', () => {
  it('zooms and pans without producing NaN', () => {
    const view = zoomAround(FULL, FULL, 1_050_000, 0.5)
    const panned = panByPixels(view, FULL, 1, 1)
    for (const value of [view.start, view.end, panned.start, panned.end]) expect(Number.isFinite(value)).toBe(true)
  })
})
