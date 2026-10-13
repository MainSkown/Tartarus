import { describe, expect, it } from 'vitest'
import { formatCount } from '@/services/format-number'

describe('formatCount', () => {
  it('groups thousands with a comma', () => {
    expect(formatCount(12431)).toBe('12,431')
    expect(formatCount(1234567)).toBe('1,234,567')
  })

  it('leaves a small number as it is', () => {
    expect(formatCount(0)).toBe('0')
    expect(formatCount(999)).toBe('999')
  })
})
