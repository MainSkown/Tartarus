import { describe, expect, it } from 'vitest'
import { ANALYSIS_STATUSES } from '@/services/analysis-status'
import { hasDesktop, phaseAfterClose, phaseAfterGuacdError, phaseForRun, phaseMessage, retryLabel } from '@/services/desktop-close'

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

  it('reads a normal close after a picture as the end of the run', () => {
    expect(phaseAfterClose(1000, true)).toBe('run-ended')
  })

  it('reads a normal close before any picture as a desktop that never came up', () => {
    expect(phaseAfterClose(1000, false)).toBe('unavailable')
  })
})

describe('phaseAfterGuacdError', () => {
  it('is an unavailable desktop before a picture and the end of the run after', () => {
    expect(phaseAfterGuacdError(false)).toBe('unavailable')
    expect(phaseAfterGuacdError(true)).toBe('run-ended')
  })
})

describe('retryLabel', () => {
  it.each([
    ['timeout', '[RETRY]'],
    ['unreachable', '[RETRY]'],
    ['unavailable', '[RETRY]'],
    ['failed', '[RECONNECT]'],
  ] as const)('offers %s the button %s', (phase, label) => {
    expect(retryLabel(phase)).toBe(label)
  })

  it.each(['connecting', 'waiting', 'connected', 'not-running', 'run-ended'] as const)('offers nothing while %s', (phase) => {
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

  it('says the run has ended and CAPE is on it, in one calm sentence', () => {
    expect(phaseMessage('run-ended')).toBe('The run has ended. CAPE is processing the results.')
  })

  it('speaks of the build, not the analysis, for the desktop of a guest build', () => {
    expect(phaseMessage('run-ended', '', 'build')).toBe('The build no longer shows a desktop.')
    expect(phaseMessage('not-running', '', 'build')).toContain('only available while the build is at a step that shows one')
    expect(phaseMessage('not-running', '', 'build')).not.toContain('analysis')
    expect(phaseMessage('unavailable', '', 'build')).not.toContain('analysis')
  })

  it('keeps the wording that does not mention a run for a build too', () => {
    expect(phaseMessage('connecting', '', 'build')).toBe(phaseMessage('connecting'))
    expect(phaseMessage('timeout', 'desktop not available yet', 'build')).toBe('desktop not available yet')
  })

  it('never prints NaN or undefined', () => {
    for (const phase of ['connecting', 'waiting', 'connected', 'run-ended', 'unavailable', 'not-running', 'timeout', 'unreachable', 'failed'] as const) {
      expect(phaseMessage(phase, 'x')).not.toMatch(/NaN|undefined/)
    }
  })
})

describe('phaseForRun', () => {
  const OVER = ['running', 'processing', 'ingesting', 'done'] as const

  it.each(['processing', 'ingesting', 'done'] as const)('turns the "only while it runs" message into the end of the run once the analysis is %s', (status) => {
    expect(phaseForRun('not-running', { status, endRequested: false })).toBe('run-ended')
  })

  it.each(['queued', 'starting', 'running', 'failed', 'cancelled', 'report_failed'] as const)(
    'keeps "only while it runs" for a desktop that never had a run to end (%s)',
    (status) => {
      expect(phaseForRun('not-running', { status, endRequested: false })).toBe('not-running')
    },
  )

  it('turns a dropped connection into the end of the run once END RUN was pressed', () => {
    expect(phaseForRun('failed', { status: 'running', endRequested: true })).toBe('run-ended')
  })

  it('keeps RECONNECT for a dropped connection while the run goes on and END RUN was not pressed', () => {
    expect(phaseForRun('failed', { status: 'running', endRequested: false })).toBe('failed')
  })

  it.each(['processing', 'ingesting', 'done'] as const)('turns a dropped connection into the end of the run when the analysis is %s', (status) => {
    expect(phaseForRun('failed', { status, endRequested: false })).toBe('run-ended')
  })

  it.each(OVER)('leaves a connected desktop alone while %s', (status) => {
    expect(phaseForRun('connected', { status, endRequested: true })).toBe('connected')
  })

  it.each(['connecting', 'waiting', 'timeout', 'unreachable', 'unavailable', 'run-ended'] as const)('leaves %s as it is', (phase) => {
    for (const status of ANALYSIS_STATUSES) expect(phaseForRun(phase, { status, endRequested: true })).toBe(phase)
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
