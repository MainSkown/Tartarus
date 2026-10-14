import { describe, expect, it } from 'vitest'
import { TICK_STEPS_MS, formatBrushLabel, formatSpanLength, formatTickLabel, formatVisibleRange, tickStep, ticksFor } from '@/services/timeline-axis'

const at = (iso: string): number => Date.parse(iso)

describe('the step between ticks', () => {
  it.each([
    [50_000, 1000, 5000],
    [10, 1000, 1],
    [1000, 1000, 100],
    [60_000, 1000, 10_000],
    [3_600_000, 1000, 600_000],
    [100_000, 500, 30_000],
  ])('is the smallest nice step that keeps ticks 90 px apart: %d ms over %d px -> %d ms', (span, width, step) => {
    expect(tickStep(span, width)).toBe(step)
  })

  it('never goes below one millisecond or above the longest step', () => {
    expect(tickStep(1, 10_000)).toBe(TICK_STEPS_MS[0])
    expect(tickStep(1e12, 100)).toBe(TICK_STEPS_MS[TICK_STEPS_MS.length - 1])
  })

  it('is the longest step when there is no width or no time to divide', () => {
    expect(tickStep(1000, 0)).toBe(TICK_STEPS_MS[TICK_STEPS_MS.length - 1])
    expect(tickStep(0, 1000)).toBe(TICK_STEPS_MS[0])
  })

  it('lists its steps in strictly increasing order', () => {
    for (let index = 1; index < TICK_STEPS_MS.length; index++) {
      const larger = TICK_STEPS_MS[index]!
      const smaller = TICK_STEPS_MS[index - 1]!
      expect(larger).toBeGreaterThan(smaller)
    }
  })
})

describe('labels', () => {
  const time = at('2026-10-13T15:39:50.123Z')

  it.each([
    [86_400_000, '2026-10-13'],
    [3_600_000, '15:39'],
    [60_000, '15:39'],
    [5000, '15:39:50'],
    [1000, '15:39:50'],
    [500, '15:39:50.1'],
    [100, '15:39:50.1'],
    [50, '15:39:50.12'],
    [10, '15:39:50.12'],
    [5, '15:39:50.123'],
    [1, '15:39:50.123'],
  ])('shows a %d ms step with exactly the precision it needs: %s', (step, label) => {
    expect(formatTickLabel(time, step)).toBe(label)
  })

  it('pads every field', () => {
    expect(formatTickLabel(at('2026-01-02T03:04:05.006Z'), 1)).toBe('03:04:05.006')
  })

  it('reads UTC, whatever the viewer time zone is', () => {
    expect(formatTickLabel(at('2026-10-13T23:59:59.000Z'), 1000)).toBe('23:59:59')
  })
})

describe('the ticks of a view', () => {
  it('are at multiples of the step, inside the view, with their labels', () => {
    const start = at('2026-10-13T15:39:50.100Z')
    const ticks = ticksFor({ start, end: start + 50_000 }, 1000)
    expect(ticks.map((tick) => tick.label)).toEqual([
      '15:39:55',
      '15:40:00',
      '15:40:05',
      '15:40:10',
      '15:40:15',
      '15:40:20',
      '15:40:25',
      '15:40:30',
      '15:40:35',
      '15:40:40',
    ])
    for (const tick of ticks) {
      expect(tick.time % 5000).toBe(0)
      expect(tick.time).toBeGreaterThanOrEqual(start)
      expect(tick.time).toBeLessThanOrEqual(start + 50_000)
    }
  })

  it('include a tick exactly on either end', () => {
    expect(ticksFor({ start: 5000, end: 10_000 }, 90).map((tick) => tick.time)).toEqual([5000, 10_000])
  })

  it('are ten milliseconds apart for a ten millisecond view', () => {
    const start = at('2026-10-13T15:39:50.000Z')
    const ticks = ticksFor({ start, end: start + 10 }, 1000)
    expect(ticks.length).toBeGreaterThanOrEqual(2)
    expect(ticks[0]!.label).toBe('15:39:50.000')
    expect(ticks[1]!.time - ticks[0]!.time).toBe(1)
  })

  it('keep their labels from overlapping: at least the minimum distance apart', () => {
    const view = { start: 0, end: 123_456 }
    const ticks = ticksFor(view, 700)
    for (let index = 1; index < ticks.length; index++) {
      expect(((ticks[index]!.time - ticks[index - 1]!.time) / (view.end - view.start)) * 700).toBeGreaterThanOrEqual(90)
    }
  })

  it('are none for an empty view or a canvas without width', () => {
    expect(ticksFor({ start: 5, end: 5 }, 1000)).toEqual([])
    expect(ticksFor({ start: 0, end: 1000 }, 0)).toEqual([])
  })

  it('are a handful at most on a one pixel canvas', () => {
    expect(ticksFor({ start: 0, end: 1000 }, 1).length).toBeLessThanOrEqual(2)
  })

  it('span hours with minute labels', () => {
    const start = at('2026-10-13T10:00:00.000Z')
    const ticks = ticksFor({ start, end: start + 4 * 3_600_000 }, 1000)
    expect(ticks.length).toBeGreaterThan(2)
    expect(ticks[0]!.label).toMatch(/^\d\d:\d\d$/)
  })
})

describe('lengths of time', () => {
  it.each([
    [0, '0 ms'],
    [10, '10 ms'],
    [999.4, '999 ms'],
    [1000, '1.00 s'],
    [3250, '3.25 s'],
    [42_500, '42.5 s'],
    [60_000, '1m 0s'],
    [252_000, '4m 12s'],
    [3_900_000, '1h 5m'],
  ])('shows %d ms as %s', (ms, label) => {
    expect(formatSpanLength(ms)).toBe(label)
  })
})

describe('the visible range label', () => {
  it('names the day once, both ends to the millisecond, UTC, and the length', () => {
    const start = at('2026-10-13T15:39:50.100Z')
    expect(formatVisibleRange({ start, end: start + 50_217 })).toBe('2026-10-13 15:39:50.100 - 15:40:40.317 UTC · 50.2 s')
  })

  it('names both days when the range crosses midnight', () => {
    const start = at('2026-10-13T23:59:00.000Z')
    expect(formatVisibleRange({ start, end: start + 120_000 })).toBe('2026-10-13 23:59:00.000 - 2026-10-14 00:01:00.000 UTC · 2m 0s')
  })

  it('is empty for a range that is not a time', () => {
    expect(formatVisibleRange({ start: Number.NaN, end: 1 })).toBe('')
  })
})

describe('the label of a brushed range', () => {
  it('gives both ends to the millisecond without the day, and the length', () => {
    const start = at('2026-10-13T15:39:50.100Z')
    expect(formatBrushLabel({ start, end: start + 3250 })).toBe('15:39:50.100 - 15:39:53.350 · 3.25 s')
  })
})
