import { describe, expect, it } from 'vitest'
import { isQuietFailure, quietOn } from '@/services/quiet-statuses'

const responseWith = (status: number) => ({ status }) as Response

describe('isQuietFailure', () => {
  it('is true when the request listed the status of the response', () => {
    expect(isQuietFailure(responseWith(404), quietOn(404, 409))).toBe(true)
    expect(isQuietFailure(responseWith(409), quietOn(404, 409))).toBe(true)
  })

  it('is false for any other status', () => {
    expect(isQuietFailure(responseWith(500), quietOn(404))).toBe(false)
  })

  it('is false when the request listed nothing or there was no response', () => {
    expect(isQuietFailure(responseWith(404), undefined)).toBe(false)
    expect(isQuietFailure(responseWith(404), {})).toBe(false)
    expect(isQuietFailure(undefined, quietOn(404))).toBe(false)
  })
})
