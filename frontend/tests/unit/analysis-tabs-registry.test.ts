import { describe, expect, it } from 'vitest'
import {
  ANALYSIS_TABS,
  DEFAULT_TAB,
  LIVE_TAB,
  isLiveStatus,
  listedTabs,
  nextLiveSession,
  selectableTab,
} from '@/services/analysis-tabs'
import { ANALYSIS_STATUSES } from '@/services/analysis-status'
import { analysisWithStatus } from './analysis-fixtures'

describe('listedTabs', () => {
  it('leaves LIVE out unless a live session is on', () => {
    expect(listedTabs(false).map((tab) => tab.key)).not.toContain(LIVE_TAB)
  })

  it('lists LIVE first, labelled LIVE, during a live session', () => {
    const [first] = listedTabs(true)
    expect(first).toMatchObject({ key: LIVE_TAB, label: 'LIVE', available: true })
  })

  it('keeps the other tabs in their order either way', () => {
    const others = listedTabs(true).slice(1).map((tab) => tab.key)
    expect(others).toEqual(listedTabs(false).map((tab) => tab.key))
    expect(others).toEqual(ANALYSIS_TABS.filter((tab) => tab.key !== LIVE_TAB).map((tab) => tab.key))
  })
})

describe('isLiveStatus', () => {
  it.each(['queued', 'starting', 'running', 'processing', 'ingesting'] as const)('is true while %s', (status) => {
    expect(isLiveStatus(status)).toBe(true)
  })

  it.each(['done', 'failed', 'report_failed', 'cancelled'] as const)('is false once %s', (status) => {
    expect(isLiveStatus(status)).toBe(false)
  })

  it('covers every status', () => {
    expect(ANALYSIS_STATUSES.filter(isLiveStatus)).toHaveLength(5)
  })
})

describe('selectableTab', () => {
  it('falls back to the default for LIVE outside a live session', () => {
    expect(selectableTab(LIVE_TAB)).toBe(DEFAULT_TAB)
    expect(selectableTab(LIVE_TAB, false)).toBe(DEFAULT_TAB)
  })

  it('selects LIVE during a live session', () => {
    expect(selectableTab(LIVE_TAB, true)).toBe(LIVE_TAB)
  })

  it('still falls back for a tab that is not built, whatever the session', () => {
    expect(selectableTab('events', true)).toBe(DEFAULT_TAB)
  })
})

describe('nextLiveSession', () => {
  const running = analysisWithStatus('running')
  const done = analysisWithStatus('done')

  it('starts when an active analysis is opened with no tab or on LIVE', () => {
    expect(nextLiveSession(false, undefined, running)).toBe(true)
    expect(nextLiveSession(false, LIVE_TAB, running)).toBe(true)
  })

  it('starts for a queued analysis as well', () => {
    expect(nextLiveSession(false, undefined, analysisWithStatus('queued'))).toBe(true)
  })

  it('never starts for an analysis opened already finished', () => {
    expect(nextLiveSession(false, undefined, done)).toBe(false)
    expect(nextLiveSession(false, LIVE_TAB, done)).toBe(false)
  })

  it('stays on when the analysis finishes during the session', () => {
    expect(nextLiveSession(true, undefined, done)).toBe(true)
    expect(nextLiveSession(true, LIVE_TAB, done)).toBe(true)
  })

  it('ends when the user picks another tab', () => {
    expect(nextLiveSession(true, 'summary', running)).toBe(false)
    expect(nextLiveSession(true, 'processes', done)).toBe(false)
  })

  it('does not start on an active analysis when the user opened another tab', () => {
    expect(nextLiveSession(false, 'summary', running)).toBe(false)
  })

  it('waits for the analysis to load', () => {
    expect(nextLiveSession(false, undefined, undefined)).toBe(false)
    expect(nextLiveSession(true, undefined, undefined)).toBe(true)
  })
})
