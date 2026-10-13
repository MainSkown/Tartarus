import { describe, expect, it } from 'vitest'
import { hasDesktop, phaseAfterClose, phaseAfterGuacdError, phaseMessage, retryLabel } from '@/services/desktop-close'

describe('phaseAfterClose', () => {
  it.each([
    [4408, false, 'timeout'],
    [4409, false, 'not-running'],
    [4404, false, 'failed'],
    [1011, false, 'unreachable'],
    [1002, true, 'failed'],
    [1006, false, 'failed'],
    [1006, true, 'failed'],
    [1001, true, 'failed'],
  ] as const)('maps close %i (connected: %s) to %s', (code, connected, phase) => {
    expect(phaseAfterClose(code, connected)).toBe(phase)
  })

  it('reads a normal close after a picture as the end of the desktop', () => {
    expect(phaseAfterClose(1000, true)).toBe('ended')
  })

  it('reads a normal close before any picture as a desktop that never came up', () => {
    expect(phaseAfterClose(1000, false)).toBe('unavailable')
  })
})

describe('phaseAfterGuacdError', () => {
  it('is an unavailable desktop before a picture and an ended one after', () => {
    expect(phaseAfterGuacdError(false)).toBe('unavailable')
    expect(phaseAfterGuacdError(true)).toBe('ended')
  })
})

describe('retryLabel', () => {
  it.each([
    ['timeout', '[RETRY]'],
    ['unreachable', '[RETRY]'],
    ['unavailable', '[RETRY]'],
    ['ended', '[RECONNECT]'],
    ['failed', '[RECONNECT]'],
  ] as const)('offers %s the button %s', (phase, label) => {
    expect(retryLabel(phase)).toBe(label)
  })

  it.each(['connecting', 'waiting', 'connected', 'not-running'] as const)('offers nothing while %s', (phase) => {
    expect(retryLabel(phase)).toBeUndefined()
  })
})

describe('phaseMessage', () => {
  it('shows the reason the server gave for a desktop that is not there yet', () => {
    expect(phaseMessage('timeout', 'desktop not available yet')).toBe('desktop not available yet')
  })

  it('falls back to its own wording when the server gave no reason', () => {
    expect(phaseMessage('timeout', '')).toContain('not available yet')
  })

  it('says the desktop only exists while the analysis runs', () => {
    expect(phaseMessage('not-running')).toContain('only available while the analysis runs')
  })

  it('never prints NaN or undefined', () => {
    for (const phase of ['connecting', 'waiting', 'connected', 'ended', 'unavailable', 'not-running', 'timeout', 'unreachable', 'failed'] as const) {
      expect(phaseMessage(phase, 'x')).not.toMatch(/NaN|undefined/)
    }
  })
})

describe('hasDesktop', () => {
  it.each([
    ['starting', true],
    ['running', true],
    ['queued', false],
    ['processing', false],
    ['ingesting', false],
    ['done', false],
    ['failed', false],
    ['cancelled', false],
  ] as const)('says %s is %s', (status, expected) => {
    expect(hasDesktop(status)).toBe(expected)
  })
})
