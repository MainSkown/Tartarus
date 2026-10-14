import { describe, expect, it } from 'vitest'
import { createRequestSequence } from '@/services/request-sequence'

describe('createRequestSequence', () => {
  it('treats the newest request as current and every earlier one as stale', () => {
    const sequence = createRequestSequence()
    const first = sequence.next()
    expect(sequence.isCurrent(first)).toBe(true)
    const second = sequence.next()
    expect(sequence.isCurrent(first)).toBe(false)
    expect(sequence.isCurrent(second)).toBe(true)
  })

  it('makes every outstanding request stale when invalidated', () => {
    const sequence = createRequestSequence()
    const request = sequence.next()
    sequence.invalidate()
    expect(sequence.isCurrent(request)).toBe(false)
  })
})
