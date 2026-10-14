import { afterEach, beforeEach } from 'vitest'
import { ANALYSIS_TABS, type AnalysisTab } from '@/services/analysis-tabs'

export const UNBUILT_TAB = 'later'

/**
 * Lists a tab that is not built yet for the tests in the file that calls this, as the registry
 * did for every tab before its milestone: the mechanism (disabled, says when it arrives, falls
 * back to the summary) outlives the last real tab that used it.
 */
export function listUnbuiltTab(overrides: Partial<AnalysisTab> = {}): void {
  const tab: AnalysisTab = { key: UNBUILT_TAB, label: 'LATER', available: false, arrivesWith: 'M9', ...overrides }
  beforeEach(() => {
    ANALYSIS_TABS.push(tab)
  })
  afterEach(() => {
    ANALYSIS_TABS.splice(ANALYSIS_TABS.indexOf(tab), 1)
  })
}
