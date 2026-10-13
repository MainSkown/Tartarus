import { describe, expect, it } from 'vitest'
import { formatDuration, formatUtcTimestamp, secondsBetween } from '@/services/format-duration'

describe('formatDuration', () => {
  it.each([
    [0, '0s'],
    [5, '5s'],
    [59.6, '1m 0s'],
    [72, '1m 12s'],
    [3600, '1h 0m'],
    [3725, '1h 2m'],
  ])('formats %s seconds as %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected)
  })
})

describe('secondsBetween', () => {
  it('measures the gap between two ISO timestamps', () => {
    expect(secondsBetween('2026-10-13T10:00:00Z', '2026-10-13T10:01:12Z')).toBe(72)
  })
})

describe('formatUtcTimestamp', () => {
  it('writes the instant as UTC to the second', () => {
    expect(formatUtcTimestamp('2026-10-13T12:00:05.123+02:00')).toBe('2026-10-13 10:00:05 UTC')
  })
})
