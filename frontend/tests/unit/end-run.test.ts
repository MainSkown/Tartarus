import { describe, expect, it } from 'vitest'
import { ANALYSIS_STATUSES } from '@/services/analysis-status'
import { endRunLabel, endRunPhase, endRunTitle, type EndRunInput } from '@/services/end-run'

const READY: EndRunInput = { status: 'running', monitorUp: true, confirming: false, ending: false, cooling: false }

describe('endRunPhase', () => {
  it('is ready for a running analysis whose monitor is up', () => {
    expect(endRunPhase(READY)).toBe('ready')
  })

  it.each(ANALYSIS_STATUSES.filter((status) => status !== 'running'))('is hidden while the analysis is %s, whatever else is going on', (status) => {
    expect(endRunPhase({ ...READY, status })).toBe('hidden')
    expect(endRunPhase({ ...READY, status, ending: true, confirming: true })).toBe('hidden')
  })

  it('waits until the monitor has started in the guest', () => {
    expect(endRunPhase({ ...READY, monitorUp: false })).toBe('waiting')
  })

  it('waits again for a moment after the server said the guest has not started', () => {
    expect(endRunPhase({ ...READY, cooling: true })).toBe('waiting')
  })

  it('is confirming while the dialog is open', () => {
    expect(endRunPhase({ ...READY, confirming: true })).toBe('confirming')
  })

  it('is ending once the server accepted, even if the feed lost the monitor meanwhile', () => {
    expect(endRunPhase({ ...READY, ending: true })).toBe('ending')
    expect(endRunPhase({ ...READY, ending: true, monitorUp: false })).toBe('ending')
  })
})

describe('endRunLabel', () => {
  it.each([
    ['waiting', 'END RUN'],
    ['ready', 'END RUN'],
    ['confirming', 'END RUN'],
    ['ending', 'ENDING...'],
  ] as const)('writes %s as %s', (phase, label) => {
    expect(endRunLabel(phase)).toBe(label)
  })
})

describe('endRunTitle', () => {
  it('explains why the button is disabled while waiting for the monitor', () => {
    expect(endRunTitle('waiting')).toMatch(/not started in the guest yet/)
  })

  it('says what the button does when it is ready', () => {
    expect(endRunTitle('ready')).toMatch(/stops the guest/i)
  })

  it('says the guest is stopping while ending', () => {
    expect(endRunTitle('ending')).toMatch(/stopping/)
  })
})
