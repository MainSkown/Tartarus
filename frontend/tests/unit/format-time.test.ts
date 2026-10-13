import { describe, expect, it } from 'vitest'
import { formatTimestamp } from '@/services/format-time'

describe('formatTimestamp', () => {
  it('renders an instant as local date and minute', () => {
    const instant = new Date(2026, 9, 12, 14, 3, 59)
    expect(formatTimestamp(instant.toISOString())).toBe('2026-10-12 14:03')
  })

  it('zero-pads month, day, hour and minute', () => {
    const instant = new Date(2026, 0, 2, 3, 4)
    expect(formatTimestamp(instant.toISOString())).toBe('2026-01-02 03:04')
  })

  it('returns the input unchanged when it is not a date', () => {
    expect(formatTimestamp('not a date')).toBe('not a date')
  })
})
