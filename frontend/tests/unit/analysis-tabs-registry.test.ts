import { describe, expect, it } from 'vitest'
import type { MessageKey } from '@/i18n'
import {
  ANALYSIS_TABS,
  arrivalNote,
  DEFAULT_TAB,
  LIVE_TAB,
  isLiveStatus,
  isUsableBeforeDone,
  isQueryableTab,
  listedTabs,
  nextLiveSession,
  selectableTab,
} from '@/services/analysis-tabs'
import { ANALYSIS_STATUSES } from '@/services/analysis-status'
import { analysisWithStatus } from './analysis-fixtures'
import { listUnbuiltTab, UNBUILT_TAB } from './unbuilt-tab'

listUnbuiltTab()

describe('listedTabs', () => {
  it('leaves LIVE out unless a live session is on', () => {
    expect(listedTabs(false).map((tab) => tab.key)).not.toContain(LIVE_TAB)
  })

  it('lists LIVE first, labelled LIVE, during a live session', () => {
    const [first] = listedTabs(true)
    expect(first).toMatchObject({ key: LIVE_TAB, labelKey: 'analysis.tabs.live', available: true })
  })

  it('keeps the other tabs in their order either way', () => {
    const others = listedTabs(true).slice(1).map((tab) => tab.key)
    expect(others).toEqual(listedTabs(false).map((tab) => tab.key))
    expect(others).toEqual(ANALYSIS_TABS.filter((tab) => tab.key !== LIVE_TAB).map((tab) => tab.key))
  })
})

describe('queryable tabs', () => {
  it('are the timeline and the events tab, the two the query bar filters', () => {
    expect(ANALYSIS_TABS.filter((tab) => tab.queryable).map((tab) => tab.key)).toEqual(['timeline', 'events'])
  })

  it('is told by key, false for a tab that does not exist', () => {
    expect(isQueryableTab('events')).toBe(true)
    expect(isQueryableTab('network')).toBe(false)
    expect(isQueryableTab('nope')).toBe(false)
  })
})

describe('tabs usable before the analysis is done', () => {
  it('are only the Notes tab: the other views read data that exists once the run is ingested', () => {
    expect(ANALYSIS_TABS.filter((tab) => isUsableBeforeDone(tab.key)).map((tab) => tab.key)).toEqual(['notes'])
  })

  it('is false for a tab that does not exist', () => {
    expect(isUsableBeforeDone('nope')).toBe(false)
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
    expect(selectableTab(UNBUILT_TAB, true)).toBe(DEFAULT_TAB)
  })
})

describe('nextLiveSession', () => {
  const running = analysisWithStatus('running')
  const done = analysisWithStatus('done')

  it.each(['queued', 'starting', 'running', 'processing', 'ingesting'] as const)(
    'starts for an analysis that is %s',
    (status) => {
      expect(nextLiveSession(false, analysisWithStatus(status))).toBe(true)
    },
  )

  it('never starts for an analysis opened already finished', () => {
    expect(nextLiveSession(false, done)).toBe(false)
  })

  it('stays on when the analysis finishes during the session, so the user can come back to it', () => {
    expect(nextLiveSession(true, done)).toBe(true)
    expect(nextLiveSession(true, running)).toBe(true)
  })

  it('keeps its state until the analysis has loaded', () => {
    expect(nextLiveSession(true, undefined)).toBe(true)
    expect(nextLiveSession(false, undefined)).toBe(false)
  })
})

describe('arrivalNote', () => {
  it('says which milestone builds a tab that is not available yet', () => {
    ANALYSIS_TABS.push({ key: 'later', labelKey: 'analysis.tabs.later' as MessageKey, available: false, arrivesWith: 'M9' })
    expect(arrivalNote('later')).toBe('later arrives with M9')
    ANALYSIS_TABS.pop()
  })

  it('says the tab arrives later when no milestone is named', () => {
    ANALYSIS_TABS.push({ key: 'someday', labelKey: 'analysis.tabs.later' as MessageKey, available: false })
    expect(arrivalNote('someday')).toBe('someday arrives later')
    ANALYSIS_TABS.pop()
  })
})
