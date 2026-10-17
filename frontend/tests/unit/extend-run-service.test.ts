import { describe, expect, it } from 'vitest'
import { EXTEND_LABEL, EXTEND_STEP_S, LONGEST_RUN_S, extendTitle } from '@/services/extend-run'

describe('extend-run constants', () => {
  it('steps by a minute, up to the 20 minutes CAPE allows an interactive run', () => {
    expect(EXTEND_STEP_S).toBe(60)
    expect(LONGEST_RUN_S).toBe(1200)
  })

  it('labels the button with its step', () => {
    expect(EXTEND_LABEL).toBe('+60S')
  })
})

describe('extendTitle', () => {
  it('explains the step when the run can still be extended', () => {
    expect(extendTitle(false)).toBe('Adds 60 seconds to the run')
  })

  it('explains the limit when the run is at its longest', () => {
    expect(extendTitle(true)).toBe('The run is already at its longest (20 minutes)')
  })
})
