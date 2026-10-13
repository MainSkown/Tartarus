export interface AnalysisTab {
  key: string
  label: string
  available: boolean
}

export const DEFAULT_TAB = 'summary'

// M1b builds the remaining tabs; until then they show disabled so the workspace already has its shape.
export const ANALYSIS_TABS: AnalysisTab[] = [
  { key: DEFAULT_TAB, label: 'SUMMARY', available: true },
  ...['processes', 'timeline', 'events', 'network', 'artifacts', 'detections', 'notes'].map((key) => ({
    key,
    label: key.toUpperCase(),
    available: false,
  })),
]

/** The tab to mark selected: the requested one only if it is built, otherwise the default. */
export function selectableTab(key: string): string {
  return ANALYSIS_TABS.some((tab) => tab.key === key && tab.available) ? key : DEFAULT_TAB
}
