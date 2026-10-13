import { describe, expect, it } from 'vitest'
import { TAB_VIEWS } from '@/components/tabs'
import { ANALYSIS_TABS, DEFAULT_TAB } from '@/services/analysis-tabs'

describe('TAB_VIEWS', () => {
  it('has a view for every enabled tab except the summary, and for nothing else', () => {
    const enabled = ANALYSIS_TABS.filter((tab) => tab.available && tab.key !== DEFAULT_TAB).map((tab) => tab.key)
    expect(Object.keys(TAB_VIEWS).sort()).toEqual([...enabled].sort())
  })
})
