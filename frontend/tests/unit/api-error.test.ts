import { describe, expect, it } from 'vitest'
import { errorMessage, genericErrorMessage } from '@/services/api-error'

describe('errorMessage', () => {
  it("reads the message of the backend's error envelope", () => {
    expect(errorMessage({ error: { message: 'Analysis 9 not found' } })).toBe('Analysis 9 not found')
  })

  it.each([undefined, null, {}, { error: {} }, { error: { message: 7 } }, 'boom'])(
    'falls back to the generic message for %j',
    (error) => {
      expect(errorMessage(error)).toBe(genericErrorMessage())
    },
  )
})
