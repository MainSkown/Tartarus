import { afterEach, beforeEach } from 'vitest'
import { i18n, type MessageKey } from '@/i18n'
import { ANALYSIS_TABS, type AnalysisTab } from '@/services/analysis-tabs'

export const UNBUILT_TAB = 'later'
const UNBUILT_LABEL_KEY = 'analysis.tabs.later' as MessageKey

/**
 * Lists a tab that is not built yet for the tests in the file that calls this, as the registry
 * did for every tab before its milestone: the mechanism (disabled, says when it arrives, falls
 * back to the summary) outlives the last real tab that used it.
 */
export function listUnbuiltTab(overrides: Partial<AnalysisTab> = {}): void {
  const tab: AnalysisTab = { key: UNBUILT_TAB, labelKey: UNBUILT_LABEL_KEY, available: false, arrivesWith: 'M9', ...overrides }
  beforeEach(() => {
    i18n.global.mergeLocaleMessage('en-US', { analysis: { tabs: { later: 'LATER' } } })
    ANALYSIS_TABS.push(tab)
  })
  afterEach(() => {
    ANALYSIS_TABS.splice(ANALYSIS_TABS.indexOf(tab), 1)
  })
}
