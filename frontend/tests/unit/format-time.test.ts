import { describe, expect, it } from 'vitest'
import { formatClockTime, formatPreciseTimestamp, formatTimestamp } from '@/services/format-time'

describe('formatTimestamp', () => {
  it('writes the instant as UTC to the second, whatever the offset it was sent with', () => {
    expect(formatTimestamp('2026-10-13T12:00:05.123+02:00')).toBe('2026-10-13 10:00:05 UTC')
  })

  it('zero-pads every field', () => {
    expect(formatTimestamp('2026-01-02T03:04:05Z')).toBe('2026-01-02 03:04:05 UTC')
  })

  it('returns the input unchanged when it is not a date', () => {
    expect(formatTimestamp('not a date')).toBe('not a date')
  })
})

describe('formatClockTime', () => {
  it('writes the UTC time of day to the millisecond', () => {
    expect(formatClockTime('2026-10-13T12:00:01.25Z')).toBe('12:00:01.250')
  })

  it('converts an offset to UTC and pads every field', () => {
    expect(formatClockTime('2026-10-13T03:04:05.006+02:00')).toBe('01:04:05.006')
  })

  it('returns the input unchanged when it is not a date', () => {
    expect(formatClockTime('later')).toBe('later')
  })
})

describe('formatPreciseTimestamp', () => {
  it('writes the date and the time of day to the millisecond, in UTC', () => {
    expect(formatPreciseTimestamp('2026-10-13T12:00:01.25+02:00')).toBe('2026-10-13 10:00:01.250 UTC')
  })

  it('returns the input unchanged when it is not a date', () => {
    expect(formatPreciseTimestamp('later')).toBe('later')
  })
})
