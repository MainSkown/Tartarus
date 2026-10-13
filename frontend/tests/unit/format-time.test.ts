import { describe, expect, it } from 'vitest'
import { formatTimestamp } from '@/services/format-time'

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
